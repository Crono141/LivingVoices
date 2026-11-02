"""Speakers of no playable race (2026-10-13): 1,550 lines the plan left to the narrator. Cast by the producer's rules
into race_cast.json (overnight.as_generated renders them from there):
  approved clones       Rexxar (own WC3), Anachronos <- Sartharion, Zhareem <- Xevozz, Parshah <- Ikiss, Remulos <-
                        WC3 Keeper of the Grove, Mog'dorg <- WC3 ogre; Freya / Chu'a'lor / Hydraxis with the calm setting
                        (style clip as emotion at 0.7); the Bone Witch with her pauses capped
  their WC3 kind        banshees, dryads, keepers of the grove; every ogre <- the WC3 ogre
  imps                  the goblin voice of round 1's "current" (Detective Snap Snagglebolt's pack voice)
  children              the Children's Week orphans and Chromie: boys from young Anduin placed by race, girls from an
                        approved girl of their race, shifted (child_voice, one pass)
  designed              centaurs (as orcs), giants, beasts, robots and everyone else: Gemma casts from the profile and
                        the creature's MODEL (the form the player sees), Voice Design makes the voice (card 1)
  flesh golems          Patchwerk's voice (the producer's pick of Patchwerk, Meathook and WC3's abomination)
Run from data/:  ../.venv/bin/python ../tools/unknown_cast.py cast     (references, casting, children; Gemma)
                          ~/ComfyUI/venv/bin/python ../tools/unknown_cast.py design   (Voice Design, card 1)
                          ../.venv/bin/python ../tools/unknown_cast.py release  (held lines back into the queue)
"""
import csv, json, os, re, shutil, sqlite3, subprocess, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
MODELS = 'unknown_models.json'                 # npc -> {name, lines, models} (creature model files, from the client)
APPROVED = {   # name -> (reference, settings)
    'Rexxar': ('clone_refs/rexxar.flac', {}),
    'Anachronos': ('clone_refs/sartharion.flac', {}),
    'Wind Trader Zhareem': ('clone_refs/xevozz.flac', {}),
    'Parshah': ('clone_refs/ikiss.flac', {}),
    'Keeper Remulos': ('clone_refs/keeper_of_the_grove.flac', {}),
    "Mog'dorg the Wizened": ('clone_refs/wc3_ogre.flac', {}),
    'Avatar of Freya': ('clone_refs/freya.flac', {'emotion_mode': 'clip', 'alpha_fixed': 0.7}),
    "Chu'a'lor": ('clone_refs/blackheart.flac', {'emotion_mode': 'clip', 'alpha_fixed': 0.7}),
    'Duke Hydraxis': ('clone_refs/hydross.flac', {'emotion_mode': 'clip', 'alpha_fixed': 0.7}),
    'The Bone Witch': ('clone_refs/sara_calm1.flac', {'pause_cap': True}),
}
ORPHANS = {'Orcish Orphan': ('male', 'orc'), 'Human Orphan': ('male', 'human'), 'Blood Elf Orphan': ('female', 'blood elf'),
           'Draenei Orphan': ('female', 'draenei'), 'Oracle Orphan': ('male', 'gnome'), 'Wolvar Orphan': ('male', 'orc'),
           'Chromie': ('female', 'gnome')}
IMP_VOICE_NPC = '37172'          # Detective Snap Snagglebolt: round 1's goblin "A_current"

def form(models):
    m = (models or ['creature'])[0]
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', m).replace('_', ' ').lower()

def category(c, u):
    m = (u['models'] or ['?'])[0]
    if u['name'] in APPROVED: return 'approved'
    if u['name'] in ORPHANS: return 'child'
    if re.match(r'centaur', m, re.I): return 'centaur'
    if re.fullmatch(r'imp', m, re.I): return 'imp'
    if re.search(r'banshee', m, re.I): return 'wc3:banshee'
    if re.search(r'dryad', m, re.I): return 'wc3:dryad'
    if re.search(r'keeperofthegrove', m, re.I): return 'wc3:keeper'
    if re.search(r'ogre', m, re.I): return 'ogre'
    if re.search(r'fleshgolem|abomination', m, re.I): return 'golem'
    return 'design'

def refs():
    import voice_sources_test as vst, glob
    from mpqget import MPQ
    T = LV.SCRATCH
    if not os.path.exists('clone_refs/sara_calm1.flac'):        # the Bone Witch's approved take came from this one
        clips = glob.glob(f'{T}/srcclips/sara/*')
        wow = vst.wow_voiced({'Sara'}); texts = {f"{T}/srcclips/sara/{f.rsplit(chr(92), 1)[1]}": t for _, f, t in wow.get('Sara', [])}
        vst.assemble(vst.calm(clips, texts, skip_broken=False), 'clone_refs/sara_calm1.flac', ordered=True)
    if not os.path.exists('clone_refs/wc3_dryad.flac'):
        out = f'{T}/bank/wc3_dryad'; os.makedirs(out, exist_ok=True)
        w = MPQ(f'{T}/war3.mpq')
        for f in w.read('(listfile)').decode('latin1').split('\r\n'):
            if f.lower().startswith('units\\nightelf\\dryad\\') and f.lower().endswith('.wav') and not re.search(r'(Death|Attack|Hit)\d*\.wav$', f, re.I):
                open(f"{out}/{f.rsplit(chr(92), 1)[1]}", 'wb').write(w.read(f))
        w.close()
        vst.assemble(vst.calm(glob.glob(f'{out}/*'), {}), 'clone_refs/wc3_dryad.flac', ordered=True)
    print('references ready')

CAST_HINT = {'centaur': 'Voice them as an orc would sound: deep and gravelly (the producer: centaurs get orc voices).',
             'design': 'Their body is the creature form given; let it shape the voice (size, breath, rasp), but they speak '
                       'clear English. A beast or animal speaks with something of that animal in the voice.'}
# not a playable race: the house accents (dwarves Scottish, trolls Caribbean...) do not apply -- Gemma gave two Ancients
# a Scottish lilt (2026-10-13). And the plan has no sex for these speakers: the profile's own words decide, else Gemma.
NO_ACCENT = ('They are not of a playable race: give them no regional accent unless the profile or their words call '
             'for one.')

# (2026-10-18, the producer, pack recording beside ours) speakers of these kinds that DO have pack recordings are cast
# the same way: the packs voiced furbolgs, ogres, tuskarr, murlocs, dryads, ethereals and the vrykul as plain humans,
# and ours won every kind but the forest trolls (their pack voices kept). The plan's race codes name the kinds.
PACK_VOICED_RECAST = {'ss:Et', 'ss:Fu', 'ss:Og', 'ss:Tk', 'ss:Mu', 'ss:Dy', 'ss:Vr'}

def add_pack_voiced():
    """unknown_models.json entries for the pack-voiced speakers of PACK_VOICED_RECAST (their client models)"""
    import struct, subprocess, overnight as ov
    def dbc(path):
        b = open(path, 'rb').read(); _, n, fc, rs, ss = struct.unpack('<4s4I', b[:20]); strs = b[20 + n * rs:]
        s = lambda o: strs[o:strs.index(b'\0', o)].decode('utf-8', 'replace')
        return [struct.unpack(f'<{fc}I', b[20 + i * rs:20 + (i + 1) * rs]) for i in range(n)], s
    mrows, ms = dbc('dbc/CreatureModelData.dbc'); model = {r[0]: ms(r[2]) for r in mrows}
    drows, _ = dbc('dbc/CreatureDisplayInfo.dbc'); disp = {r[0]: r[1] for r in drows}
    U = json.load(open(MODELS)); rc = ov.race_cast(); who = {}
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['race'] in PACK_VOICED_RECAST and r['npc_id'].isdigit() and r['npc_id'] not in U and r['npc_id'] not in rc:
            who.setdefault(r['npc_id'], [r['npc_name'], 0])[1] += 1
    for c, (name, n) in who.items():
        out = subprocess.run(['mariadb', f'--defaults-extra-file={LV.DB_CNF}', 'acore_world', '-N', '-B', '-e',
                              f'select CreatureDisplayID from creature_template_model where CreatureID={c}'], capture_output=True, text=True, check=True).stdout
        ms_ = [os.path.basename(model.get(disp.get(int(d)), '')).rsplit('.', 1)[0] for d in out.split()]
        U[c] = {'name': name, 'lines': n, 'models': [m for m in ms_ if m] or ['creature'], 'pack_voiced': True}
    json.dump(U, open(MODELS, 'w'), indent=1); print(len(who), 'pack-voiced speakers added')

def cast():
    import design_voices as dv, direct, overnight as ov
    refs()
    U = json.load(open(MODELS)); RC = json.load(open('race_cast.json')); VC = json.load(open(dv.CAST))
    prof = dv.profiles(); plan = list(csv.DictReader(open('plan_v3.csv')))
    imp = ov.pack_refs().get(IMP_VOICE_NPC)
    import collections; n = collections.Counter()
    for c, u in U.items():
        k = category(c, u); n[k] += 1
        if c in RC: continue
        if k == 'approved':
            ref, opt = APPROVED[u['name']]; RC[c] = dict({'name': u['name'], 'src': 'unknown_approved', 'ref': ref}, **opt)
        elif k.startswith('wc3:') or k in ('ogre', 'golem'):
            ref = {'wc3:banshee': 'clone_refs/wc3_banshee.flac', 'wc3:dryad': 'clone_refs/wc3_dryad.flac',
                   'wc3:keeper': 'clone_refs/keeper_of_the_grove.flac', 'ogre': 'clone_refs/wc3_ogre.flac',
                   'golem': 'clone_refs/patchwerk.flac'}[k]
            RC[c] = {'name': u['name'], 'src': f'unknown_{k}', 'ref': ref}
        elif k == 'imp' and imp:
            RC[c] = {'name': u['name'], 'src': 'unknown_imp', 'clone_ref': imp, 'ref': ''}
        elif k == 'child':
            RC[c] = {'name': u['name'], 'src': 'unknown_child', 'ref': child_voice(c, u['name'])}
        elif k in ('design', 'centaur'):
            if c not in VC:
                lines = [(r['questId'], r['kind']) for r in plan if r['npc_id'] == c]
                p = prof.get(c, {}); sex = next((r['sex'] for r in plan if r['npc_id'] == c), '')
                who = (p.get('who') or '').lower()
                sex = sex if sex in ('male', 'female') else 'female' if re.search(r'\bfemale\b|\bwoman\b|\bgirl\b', who) \
                    else 'male' if re.search(r'\bmale\b|\bman\b|\bboy\b', who) else ''
                sex_txt = sex or 'sex not recorded -- decide from the name, profile and their words'
                user = (f"Character: {u['name']}, {sex_txt}, in the form of a {form(u['models'])} ({p.get('who', '')}).\n"
                        f"Who they are: {direct.PERSONA.get(c, p.get('persona', 'unknown'))}\n"
                        f"Their voice, per the profile: {p.get('voice', '')}\n"
                        f"Their own words: \"{dv.ref_text(lines)}\"\n{CAST_HINT[k]}" + ('' if k == 'centaur' else ' ' + NO_ACCENT))
                desc = dv.llm(user)
                if not sex: sex = 'female' if re.search(r'\bfemale\b|\bwoman\b|\bgirl\b', desc.lower()) else 'male'
                VC[c] = {'name': u['name'], 'race': form(u['models']), 'sex': sex, 'description': desc,
                         'reference_text': dv.ref_text(lines), 'lines': len(lines)}
                json.dump(VC, open(dv.CAST, 'w'), indent=1)
                print(f"{u['name']} ({form(u['models'])}): {VC[c]['description'][:110]}", flush=True)
            RC[c] = {'name': u['name'], 'src': f'unknown_{k}', 'ref': f'designed_voices/{c}.mp3', 'needs_design': True}
        json.dump(RC, open('race_cast.json', 'w'), indent=1)
    print('categories:', dict(n))

def child_voice(c, name):
    """designed_voices/<c>.mp3 for an orphan: a boy from young Anduin placed by race; a girl from an approved girl of
    her race (else a human girl), shifted a little so she is her own child"""
    import child_cast, child_voice as cv
    sex, race = ORPHANS[name]; dst = f'designed_voices/{c}.mp3'
    if os.path.exists(dst): return dst
    if sex == 'male':
        p, f = child_cast.offset(name, race); src = cv.childify(child_cast.anduin_ref(), f'child_refs/boy_{c}.wav', p, f)
    else:
        kids = child_cast.children()
        same = [k for k, v in kids.items() if v['sex'] == 'female' and v['race'].lower() == race and os.path.exists(f'designed_voices/{k}.mp3')]
        any_ = [k for k, v in kids.items() if v['sex'] == 'female' and os.path.exists(f'designed_voices/{k}.mp3')]
        base = f'designed_voices/{(same or any_)[zlib.crc32(c.encode()) % len(same or any_)]}.mp3'
        st = [-0.5, 0.0, 0.5][zlib.crc32(name.encode()) % 3]
        src = f'child_refs/girl_{c}.wav'
        subprocess.run(['rubberband-r3', '-q', '-p', str(st), base, src] if st else ['ffmpeg', '-y', '-v', 'error', '-i', base, src], check=True)
    child_cast.save(src, c, name); return dst

def design():
    """Voice Design for every designed unknown speaker that has no voice yet (card 1's ComfyUI)"""
    import design_voices as dv
    RC = json.load(open('race_cast.json'))
    todo = [c for c, v in RC.items() if v.get('needs_design') and not os.path.exists(v['ref'])]
    print(len(todo), 'voices to design', flush=True)
    if todo: dv.render(todo)
    for c in todo:
        if os.path.exists(RC[c]['ref']): RC[c].pop('needs_design', None)
    json.dump(RC, open('race_cast.json', 'w'), indent=1)

def release():
    """held lines of cast speakers back into the queue: directed -> todo (any old narrator render deleted), else new"""
    import overnight as ov
    RC = json.load(open('race_cast.json')); U = json.load(open(MODELS))
    ready = {c for c in U if c in RC and os.path.exists(RC[c].get('ref') or '') or (c in RC and RC[c].get('clone_ref'))}
    D = ov.load_directions([ov.DIRECTIONS])
    plan = {ov.name_of(r): r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] != 'none'}
    db = sqlite3.connect(ov.DB); n = {'todo': 0, 'new': 0, 'still held': 0}
    for nm, q, k in db.execute("SELECT name, questId, kind FROM lines WHERE status='hold'").fetchall():
        r = plan.get(nm)
        if not r or r['npc_id'] not in ready: n['still held'] += 1; continue
        if os.path.exists(f'render/{nm}.mp3'): os.remove(f'render/{nm}.mp3')
        st = 'todo' if D.get(q, {}).get(k) else 'new'
        db.execute("UPDATE lines SET status=?, err=NULL, seed=1, tries=0, score=NULL WHERE name=?", (st, nm)); n[st] += 1
    db.commit(); print('released:', n)

# (2026-10-13, the producer, after the morph samples) a preset on top of the voice, by the creature the player sees
def morph_for(name, models):
    m = ' '.join(models or []).lower(); n = name.lower()
    if re.search(r'spirit|ghost|wisp|wraith|banshee', m + ' ' + n) and 'banshee' not in m: return 'whisperer'
    if 'satyr' in m: return 'demon'
    if 'murloc' in m: return 'murloc'
    if 'tuskarr' in m: return 'tuskarr'
    if re.search(r'giant', m): return ['giant_stone', 'lyrebird_darth_vader'][zlib.crc32(name.encode()) % 2]
    if re.search(r'robot|gnomebot|mech|oox|bot\b', m + ' ' + n): return 'robot'
    if 'airelemental' in m.replace(' ', ''): return 'elemental_air'
    if 'waterelemental' in m.replace(' ', '') or 'tsunaman' in n: return 'elemental_water'
    if re.search(r'furbolg|wolvar|gnoll|quilboar|kobold|beast|wolf|tiger|frog|bear|cat|chicken|raptor|owl|worg|boar|'
                 r'spider|crab|turtle|serpent|hound|horse|equine|steed|ram|saber|cow|pig|rabbit|bird|crow|hawk|eagle|stag|fox', m + ' ' + n):
        return 'beast_growl'
    return None

def morphs():
    U = json.load(open(MODELS)); RC = json.load(open('race_cast.json')); import collections; n = collections.Counter()
    for c, u in U.items():
        if c not in RC or RC[c]['src'] in ('unknown_approved', 'own_wc3'): continue
        mp = morph_for(u['name'], u['models'])
        if mp: RC[c]['morph'] = mp; n[mp] += 1
        else: RC[c].pop('morph', None)
    json.dump(RC, open('race_cast.json', 'w'), indent=1); print('morphs:', dict(n))

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'cast': cast, 'design': design, 'release': release, 'refs': refs, 'morphs': morphs, 'add_pack_voiced': add_pack_voiced}[sys.argv[1]]()
