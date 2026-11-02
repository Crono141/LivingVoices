"""Bake-off (2026-10-13): for the hard races (trolls, orcs, goblins, undead, dwarves, tauren) -- the current voice
(pack clone or design) beside a Warcraft III unit voice, cloned and shifted per NPC. Three NPCs per race from
outside the Elwynn pilot; the producer decides race by race. Heroes stay with their own characters.

Run from data/ with the ComfyUI venv:
  ~/ComfyUI/venv/bin/python ../tools/bakeoff.py bank      the unit references (data/clone_refs/wc3_<unit>.wav)
  ~/ComfyUI/venv/bin/python ../tools/bakeoff.py pick      three NPCs per race; Gemma casts each from the bank
  ~/ComfyUI/venv/bin/python ../tools/bakeoff.py render    card 0 -> <listen>/voice_test/bakeoff/<race>/<npc>/
"""
import csv, json, os, re, subprocess, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
OUT = f'{LV.COMFY_OUT}/voice_test/bakeoff'
WC3 = LV.SCRATCH
PICKS = 'bakeoff_picks.json'
# race -> {unit folder: what it is in Warcraft III}; male voices unless noted. Named heroes are left out.
BANK = {
    'Orc': {'Orc\\Grunt': 'orc grunt, the foot soldier', 'Orc\\Peon': 'orc peon, the labourer',
            'Orc\\Shaman': 'orc shaman', 'Orc\\Wolfrider': 'orc wolf rider (raider)',
            'Orc\\WyvernRider': 'orc wyvern rider', 'Orc\\HeroBladeMaster': 'orc blademaster, a swordmaster hero',
            'Orc\\HeroFarseer': 'orc far seer, an old shaman hero', 'Orc\\KotoBeast': 'orc kodo beast rider'},
    'Troll': {'Orc\\HeadHunter': 'troll headhunter', 'Orc\\WitchDoctor': 'troll witch doctor',
              'Orc\\BatTroll': 'troll batrider', 'Orc\\HeroShadowHunter': 'troll shadow hunter hero',
              'Creeps\\ForestTroll': 'forest troll', 'Creeps\\IceTroll': 'ice troll'},
    'Tauren': {'Orc\\Tauren': 'tauren warrior', 'Orc\\SpiritWalker': 'tauren spirit walker',
               'Orc\\HeroTaurenChieftain': 'tauren chieftain hero'},
    'Undead': {'Undead\\Acolyte': 'undead acolyte, a hooded cultist', 'Undead\\Necromancer': 'undead necromancer',
               'Undead\\HeroDeathKnight': 'death knight hero', 'Undead\\HeroLich': 'lich hero, hollow and cold',
               'Undead\\Banshee': 'banshee (female), a wailing spirit'},
    'Dwarf': {'Human\\Rifleman': 'dwarf rifleman', 'Human\\MortarTeam': 'dwarf mortar team',
              'Human\\GryphonRider': 'dwarf gryphon rider', 'Human\\GyroCopter': 'dwarf gyrocopter pilot',
              'Human\\HeroMountainKing': 'dwarf mountain king hero'},
    'Goblin': {'Creeps\\GoblinSapper': 'goblin sapper, a demolitions nut', 'Creeps\\GoblinZeppelin': 'goblin zeppelin pilot'},
}
FEMALE = {'Undead\\Banshee'}
OWN_WC3 = {'Nazgrel', 'Rexxar', 'Rokhan', 'Shandris Feathermoon', 'Malfurion Stormrage'}   # their own WC3 voice (chosen)
# the sound's tag ends the file name ("GruntWhat1", "WhiteTaurenPissed2"): combat noises and deaths are not speech
SKIP = re.compile(r'(Death|Warcry|YesAttack|Attack|Cast|Fire|Launch|Impact|Explode|Land|Hit|Swing|Step)\d*[a-z]?\.(wav|mp3)$', re.I)

def ref_name(unit): return 'wc3_' + re.sub(r'[^A-Za-z]', '', unit.split('\\')[1]).lower()

def bank():
    from mpqget import MPQ
    import voice_sources_test as vst
    os.makedirs('clone_refs', exist_ok=True)
    units = {u for r in BANK.values() for u in r}
    files = {u: [] for u in units}
    for a in ('war3.mpq', 'War3x.mpq', 'War3xLocal.mpq'):
        w = MPQ(f'{WC3}/{a}'); L = w.read('(listfile)').decode('latin1').split('\r\n')
        for f in L:
            p = f.split('\\')
            if len(p) >= 4 and p[0].lower() == 'units' and f.lower().endswith(('.wav', '.mp3')):
                u = '\\'.join(p[1:3])
                # the sound's own tag, after the unit's name: "HeroDeathKnightWhat1" is a What, not a Death
                tag = p[-1][len(p[2]):] if p[-1].lower().startswith(p[2].lower()) else p[-1]
                if u in files and not SKIP.search(tag):
                    d = f'{WC3}/bank/{ref_name(u)}'; os.makedirs(d, exist_ok=True)
                    dst = f'{d}/{p[-1]}'; open(dst, 'wb').write(w.read(f)); files[u].append(dst)
        w.close()
    for u, fs in sorted(files.items()):
        if not fs: print('!! nothing for', u); continue
        tot, n = vst.assemble(vst.calm(fs, {}), f'clone_refs/{ref_name(u)}.wav', ordered=True)
        print(f'{u:28} {len(fs):2} clips -> {tot:.1f} s from {n}')

def llm(system, user, schema):
    import urllib.request
    body = {'model': LV.LLM_MODEL, 'temperature': 0.3, 'max_tokens': 300,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'pick', 'schema': schema}},
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    r = urllib.request.Request(f'{LV.LLM_URL}/v1/chat/completions', data=json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json'})
    return json.loads(json.load(urllib.request.urlopen(r, timeout=300))['choices'][0]['message']['content'])

SYSTEM = """You cast voices for an English voice-over of World of Warcraft quest givers. For one character, choose \
the Warcraft III unit voice that best suits them -- their age, temperament, standing and manner -- from the list \
given. The chosen voice will be cloned and slightly pitch-shifted for this character. Answer JSON: \
{"unit": "<exactly one unit from the list>", "why": "<a few words>"}"""

def pick():
    import direct, design_voices
    prof = design_voices.profiles()
    pilot = set(open('pilot_quests.txt').read().split())
    plan = [r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'].isdigit()]
    by = {}
    for r in plan:
        e = by.setdefault(r['npc_id'], {'rows': [], 'pilot': False}); e['rows'].append(r)
        if r['questId'] in pilot: e['pilot'] = True
    picks = {}
    for race, units in BANK.items():
        sexes = ['male', 'female'] if any(u in FEMALE for u in units) else ['male']
        cand = [(c, e) for c, e in by.items() if not e['pilot'] and e['rows'][0]['race'] == race
                and e['rows'][0]['sex'] in sexes and len(e['rows']) >= 4
                and not any(r['clone_ref'].startswith('game:') for r in e['rows'])      # own WoW voice: keeps it
                and e['rows'][0]['npc_name'] not in OWN_WC3]
        # one the packs voiced (cloned from the pack today), one designed, one more of either -- the busiest first
        cand.sort(key=lambda x: -len(x[1]['rows']))
        packed = [x for x in cand if any(r['action'] == 'reuse' for r in x[1]['rows'])]
        designed = [x for x in cand if all(r['clone_ref'].startswith('design:') for r in x[1]['rows'] if r['action'] == 'generate')
                    and not any(r['action'] == 'reuse' for r in x[1]['rows'])]
        chosen = []
        for pool in (packed, designed, cand):
            for x in pool:
                if x[0] not in [c for c, _ in chosen]: chosen.append(x); break
        if race == 'Undead':                         # the one female voice in the bank gets a female speaker
            fem = [x for x in cand if x[1]['rows'][0]['sex'] == 'female' and x[0] not in [c for c, _ in chosen]]
            if fem: chosen[-1] = fem[0]
        for c, e in chosen:
            r0 = e['rows'][0]; p = prof.get(c, {})
            ok = {u: d for u, d in units.items() if (u in FEMALE) == (r0['sex'] == 'female')}
            user = (f"Character: {r0['npc_name']}, {r0['sex']} {race}, {p.get('age', '')}.\n"
                    f"Who they are: {direct.PERSONA.get(c, p.get('persona', ''))}\n"
                    f"Their voice, per the profile: {p.get('voice', '')}\n"
                    "Units:\n" + '\n'.join(f'- {u}: {d}' for u, d in ok.items()))
            ans = llm(SYSTEM, user, {'type': 'object', 'required': ['unit', 'why'],
                                     'properties': {'unit': {'type': 'string', 'enum': list(ok)}, 'why': {'type': 'string'}}})
            shift = ((zlib.crc32(c.encode()) % 7) - 3) * 0.5          # -1.5 .. +1.5 semitones, the same every run
            picks[c] = {'race': race, 'name': r0['npc_name'], 'sex': r0['sex'], 'unit': ans['unit'], 'why': ans['why'],
                        'shift': shift, 'packed': any(r['action'] == 'reuse' for r in e['rows'])}
            print(f"{race:7} {r0['npc_name']:28} {r0['sex']:6} -> {ans['unit']:26} {shift:+.1f} st  ({ans['why']})", flush=True)
    json.dump(picks, open(PICKS, 'w'), indent=1)

def shifted(unit, st):
    src = f'clone_refs/{ref_name(unit)}.wav'
    if not st: return src
    dst = f'clone_refs/{ref_name(unit)}_{st:+.1f}.wav'
    if not os.path.exists(dst):     # ONE pass, pitch and formants together (the child cast: pitch-only corrupts)
        subprocess.run(['rubberband-r3', '-q', '-p', str(st), src, dst], check=True)
    return dst

def render_all():
    import render, overnight as ov, direct, actor_read
    render.use_server(LV.RENDERERS["0"])
    picks = json.load(open(PICKS)); plan = list(csv.DictReader(open('plan_v3.csv')))
    D = {}
    for l in open('directions.jsonl'):
        x = json.loads(l)
        if 'error' not in x: D[x['questId']] = x
    index = []
    for c, pk in picks.items():
        rows = [r for r in plan if r['npc_id'] == c]
        r = max([x for x in rows if x['action'] == 'reuse'] or rows, key=lambda x: int(x['words'] or 0))
        q, nm = r['questId'], ov.name_of(r)
        d = D.get(q, {}).get(r['kind'])
        if not d:
            direct.ACTOR_NOTES.update(actor_read.ensure({x['npc_id'] for x in plan if x['questId'] == q}))
            d = direct.direct(q).get(r['kind'])
        out = f"{OUT}/{pk['race']}/{re.sub(r'[^A-Za-z0-9]+', '_', pk['name']).strip('_')}"; os.makedirs(out, exist_ok=True)
        cur = ov.as_generated(r)
        try:
            if os.path.exists(f'{out}/{nm}_A_current.mp3'): pass
            elif os.path.exists(f'render/{nm}.mp3'): subprocess.run(['cp', f'render/{nm}.mp3', f'{out}/{nm}_A_current.mp3'])
            else: render.render_line(cur, d, f'{out}/{nm}_A_current.mp3')
        except FileNotFoundError as e:
            print('   (no current voice yet:', str(e)[:80], ')')
        unit = pk['unit'].split('\\')[1]
        if not os.path.exists(f'{out}/{nm}_B_wc3_{unit}.mp3'):
            render.render_line(dict(r, action='generate', clone_ref=f"game:{shifted(pk['unit'], pk['shift'])}"), d,
                               f'{out}/{nm}_B_wc3_{unit}.mp3')
        if r['action'] == 'reuse' and r['source_pack']:
            render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", f"{out}/{nm}_pack.{r['file_in_pack'].rsplit('.', 1)[1]}")
        line = f"{pk['race']}/{pk['name']}: A = current ({cur['clone_ref'].split(':')[0]}), B = WC3 {unit} {pk['shift']:+.1f} st  [{pk['why']}]"
        index.append(line); print(line, flush=True)
    open(f'{OUT}/INDEX.txt', 'w').write('\n'.join(index) + '\n')

# ---------------------------------------------------------------- round 2 (2026-10-13, after the producer's verdicts)
# Orcs keep their current voices. Far seer, mortar team and the tauren warrior were rejected; the goblin sapper's
# upward shift corrupted the high end (as the girls' shift once did), so round 2 never shifts up. WoW's own NPC
# voice sets (several actors per race and sex: Grim, Guard, Standard...) carry the race's accent.
BANK2 = {
    'Troll':  {'male':   ['wow:TrollMaleStandardNPC', 'wow:TrollMaleDarkNPC', 'wow:TrollMaleShamanNPC',
                          'wc3:Orc\\HeadHunter', 'wc3:Orc\\WitchDoctor', 'wc3:Orc\\HeroShadowHunter'],
               'female': ['wow:TrollFemaleStandardNPC', 'wow:TrollFemaleLaidBackNPC', 'wow:TrollFemaleOldNPC']},
    'Tauren': {'male':   ['wow:TaurenMaleElderNPC', 'wow:TaurenMaleShamanNPC', 'wow:TaurenMaleWarriorNPC',
                          'wc3:Orc\\SpiritWalker', 'wc3:Orc\\HeroTaurenChieftain'],
               'female': ['wow:TaurenFemaleStandardNPC', 'wow:TaurenFemaleShamanNPC', 'wow:TaurenFemaleOfficialNPC']},
    'Undead': {'male':   ['wow:UndeadMaleStandardNPC', 'wow:UndeadMaleDarkNPC', 'wow:UndeadMaleWarriorNPC'],
               'female': ['wow:UndeadFemaleStandardNPC', 'wow:UndeadFemaleMagicNPC', 'wow:UndeadFemaleWarriorNPC']},
    'Dwarf':  {'male':   ['wow:DwarfMaleStandardNPC', 'wow:DwarfMaleGrimNPC', 'wow:DwarfMaleGuardNPC', 'wc3:Human\\HeroMountainKing'],
               'female': ['wow:DwarfFemaleYoungNPC', 'wow:DwarfFemaleMaternalNPC', 'wow:DwarfFemaleGuardNPC']},
    'Goblin': {'male':   ['wow:GoblinMaleZanyNPC', 'wow:GoblinMaleGruffNPC', 'wow:GoblinMaleGuardNPC', 'wc3:Creeps\\GoblinSapper'],
               'female': ['wow:GoblinFemaleZanyNPC']},
}
PICKS2 = 'bakeoff_picks2.json'

def ref2(src):
    kind, name = src.split(':', 1)
    return f'clone_refs/{ref_name(name)}.wav' if kind == 'wc3' else f'clone_refs/wow_{name.lower()}.wav'

def bank2():
    """WoW NPC voice sets -> clone_refs/wow_<set>.wav (the WC3 ones exist from round 1)"""
    import glob as g
    from mpqget import MPQ
    import voice_sources_test as vst
    C = f'{LV.WOW_DATA}'
    want = {s.split(':', 1)[1].lower() for r in BANK2.values() for xs in r.values() for s in xs if s.startswith('wow:')}
    files = {w: {} for w in want}
    for p in sorted(g.glob(C + '/*.MPQ') + g.glob(C + '/*/*.MPQ')):       # later archives patch earlier ones
        try: m = MPQ(p); L = m.read('(listfile)').decode('latin1').split('\r\n')
        except Exception: continue
        for f in L:
            pp = f.split('\\')
            if len(pp) >= 4 and pp[1].lower() == 'creature' and pp[2].lower() in want and f.lower().endswith('.wav') \
                    and not SKIP.search(pp[-1]):
                d = f'{WC3}/bank/wow_{pp[2].lower()}'; os.makedirs(d, exist_ok=True)
                dst = f'{d}/{pp[-1]}'; open(dst, 'wb').write(m.read(f)); files[pp[2].lower()][pp[-1]] = dst
        m.close()
    for w, fs in sorted(files.items()):
        if not fs: print('!! nothing for', w); continue
        tot, n = vst.assemble(vst.calm(list(fs.values()), {}), f'clone_refs/wow_{w}.flac', ordered=True)
        print(f'{w:28} {len(fs):2} clips -> {tot:.1f} s from {n}')

def pick2():
    import direct, design_voices
    prof = design_voices.profiles(); old = json.load(open(PICKS))
    pilot = set(open('pilot_quests.txt').read().split())
    plan = [r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'].isdigit()]
    by = {}
    for r in plan:
        e = by.setdefault(r['npc_id'], {'rows': [], 'pilot': False}); e['rows'].append(r)
        if r['questId'] in pilot: e['pilot'] = True
    picks = {}
    for race, sexes in BANK2.items():
        chosen = [c for c, pk in old.items() if pk['race'] == race and pk['sex'] == 'male']
        fem = sorted((c for c, e in by.items() if not e['pilot'] and e['rows'][0]['race'] == race and e['rows'][0]['sex'] == 'female'
                      and len(e['rows']) >= 4 and not any(r['clone_ref'].startswith('game:') for r in e['rows'])),
                     key=lambda c: -len(by[c]['rows']))
        chosen += fem[:1] if race != 'Undead' else [c for c, pk in old.items() if pk['race'] == race and pk['sex'] == 'female']
        for c in chosen:
            r0 = by[c]['rows'][0]; p = prof.get(c, {}); opts = sexes[r0['sex']]
            user = (f"Character: {r0['npc_name']}, {r0['sex']} {race}, {p.get('age', '')}.\n"
                    f"Who they are: {direct.PERSONA.get(c, p.get('persona', ''))}\n"
                    f"Their voice, per the profile: {p.get('voice', '')}\n"
                    "Voices (wow: a World of Warcraft NPC voice set, named by its flavour; wc3: a Warcraft III unit):\n"
                    + '\n'.join(f'- {o}' for o in opts))
            ans = llm(SYSTEM, user, {'type': 'object', 'required': ['unit', 'why'],
                                     'properties': {'unit': {'type': 'string', 'enum': opts}, 'why': {'type': 'string'}}})
            shift = -0.5 * (zlib.crc32(c.encode()) % 3)          # 0, -0.5 or -1 st: never up
            picks[c] = {'race': race, 'name': r0['npc_name'], 'sex': r0['sex'], 'src': ans['unit'], 'why': ans['why'], 'shift': shift}
            print(f"{race:7} {r0['npc_name']:28} {r0['sex']:6} -> {ans['unit']:30} {shift:+.1f} st  ({ans['why']})", flush=True)
    json.dump(picks, open(PICKS2, 'w'), indent=1)

def shifted2(src, st):
    ref = ref2(src)
    if not st: return ref
    dst = ref[:-4] + f'_{st:+.1f}.wav'
    if not os.path.exists(dst): subprocess.run(['rubberband-r3', '-q', '-p', str(st), ref, dst], check=True)
    return dst

def render2():
    import render, overnight as ov, direct, actor_read
    render.use_server(LV.RENDERERS["0"])
    picks = json.load(open(PICKS2)); plan = list(csv.DictReader(open('plan_v3.csv')))
    D = {}
    for l in open('directions.jsonl'):
        x = json.loads(l)
        if 'error' not in x: D[x['questId']] = x
    index = []
    for c, pk in picks.items():
        rows = [r for r in plan if r['npc_id'] == c]
        r = max([x for x in rows if x['action'] == 'reuse'] or rows, key=lambda x: int(x['words'] or 0))
        q, nm = r['questId'], ov.name_of(r)
        d = D.get(q, {}).get(r['kind'])
        if not d:
            direct.ACTOR_NOTES.update(actor_read.ensure({x['npc_id'] for x in plan if x['questId'] == q}))
            d = direct.direct(q).get(r['kind'])
        r1 = f"{OUT}/{pk['race']}/{re.sub(r'[^A-Za-z0-9]+', '_', pk['name']).strip('_')}"
        out = f"{OUT}/round2/{pk['race']}/{re.sub(r'[^A-Za-z0-9]+', '_', pk['name']).strip('_')}"; os.makedirs(out, exist_ok=True)
        for f in (glob_one(r1, '_A_current'), glob_one(r1, '_pack')):
            if f: subprocess.run(['cp', f, out])
        if not glob_one(out, '_A_current'):
            cur = ov.as_generated(r)
            try:
                if os.path.exists(f'render/{nm}.mp3'): subprocess.run(['cp', f'render/{nm}.mp3', f'{out}/{nm}_A_current.mp3'])
                else: render.render_line(cur, d, f'{out}/{nm}_A_current.mp3')
            except FileNotFoundError as e: print('   (no current voice:', str(e)[:80], ')')
            if r['action'] == 'reuse' and r['source_pack']:
                render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", f"{out}/{nm}_pack.{r['file_in_pack'].rsplit('.', 1)[1]}")
        tag = re.sub(r'[^A-Za-z0-9]+', '', pk['src'].split(':', 1)[1].split('\\')[-1])
        dst = f'{out}/{nm}_C_{tag}.mp3'
        if not os.path.exists(dst):
            render.render_line(dict(r, action='generate', clone_ref=f"game:{shifted2(pk['src'], pk['shift'])}"), d, dst)
        # when Gemma picked a WC3 unit, a WoW set too: the round is about hearing WoW's own accents (dwarves above all)
        extra = ''
        if pk['src'].startswith('wc3:'):
            wows = [o for o in BANK2[pk['race']][pk['sex']] if o.startswith('wow:')]
            w = wows[zlib.crc32(c.encode()) % len(wows)]
            tag2 = w.split(':', 1)[1]; dst2 = f'{out}/{nm}_D_{tag2}.mp3'
            if not os.path.exists(dst2):
                render.render_line(dict(r, action='generate', clone_ref=f"game:{shifted2(w, pk['shift'])}"), d, dst2)
            extra = f', D = {w}'
        line = f"round2/{pk['race']}/{pk['name']} ({pk['sex']}): C = {pk['src']}{extra} {pk['shift']:+.1f} st  [{pk['why']}]"
        index.append(line); print(line, flush=True)
    open(f'{OUT}/round2/INDEX.txt', 'w').write('\n'.join(index) + '\n')

def glob_one(d, tag):
    import glob as g
    fs = [f for f in g.glob(f'{d}/*') if tag in os.path.basename(f)]
    return fs[0] if fs else None

# ---------------------------------------------------------------- round 3 (2026-10-13, evening)
# Dwarf men sounded like orcs: calm() put the lowest, gruffest clips first, "Pissed" lines got in, and every voice was
# shifted DOWN. The sets carry the accent ("Keep your feet on the ground!" is DwarfMaleGuardNPC, "Off with you" Grim /
# Standard). Round 3: greetings and farewells only, longest first, no shift; plus the player character's voice. And
# the slow ones (troll Dark, tauren Shaman; troll LaidBack's delivery) with the reference sped up, pitch kept.
R3 = 'round3'

def gf_ref(folder_glob, dst, want=12.0, pattern=r'(Greeting|Farewell|Hello|Bye)'):
    import glob as g
    import voice_sources_test as vst
    fs = [f for f in g.glob(folder_glob) if not pattern or re.search(pattern, os.path.basename(f), re.I)]
    tot, n = vst.assemble(fs, dst, want=want)          # longest first: no pitch ordering
    print(f'{os.path.basename(dst):32} {len(fs):2} clips -> {tot:.1f} s from {n}')
    return dst

def tempo(src, f):
    dst = src[:-4] + f'_t{f:.2f}.wav'
    if not os.path.exists(dst): subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-af', f'atempo={f}', dst], check=True)
    return dst

def render3():
    import render, overnight as ov, direct
    render.use_server(LV.RENDERERS["0"])
    T = f'{WC3}/dwarfm'
    refs = {
        'dwarf_guard':    gf_ref(f'{T}/DwarfMaleGuardNPC__*', 'clone_refs/r3_dwarf_guard.flac'),
        'dwarf_standard': gf_ref(f'{T}/DwarfMaleStandardNPC__*', 'clone_refs/r3_dwarf_standard.flac'),
        'dwarf_grim':     gf_ref(f'{T}/DwarfMaleGrimNPC__*', 'clone_refs/r3_dwarf_grim.flac'),
        'dwarf_oldset':   gf_ref(f'{T}/DwarfMale*__*', 'clone_refs/r3_dwarf_oldset.flac', pattern=r'^(DwarfMale|DwarfMaleFinal|DwarfMaleNpc1)__(?!.*Pissed)'),
        'dwarf_player':   gf_ref(f'{T}/DwarfMaleErrorMessages__*', 'clone_refs/r3_dwarf_player.flac', pattern=''),
    }
    # the old-set pattern is on the file name with its folder prefix
    jobs = [('Craftsman Wilhelm', k) for k in refs] + [('Packmaster Stonebruiser', k) for k in refs]
    speed = [("Yeh'kinya", 'troll_dark_fast', tempo('clone_refs/wow_trollmaledarknpc.flac', 1.12)),
             ('Arch Druid Hamuul Runetotem', 'tauren_shaman_fast', tempo('clone_refs/wow_taurenmaleshamannpc.flac', 1.12)),
             ('Maywiki of Zuldazar', 'troll_laidback_livelier', tempo('clone_refs/wow_trollfemalelaidbacknpc.flac', 1.08))]
    plan = list(csv.DictReader(open('plan_v3.csv')))
    D = {}
    for l in open('directions.jsonl'):
        x = json.loads(l)
        if 'error' not in x: D[x['questId']] = x
    for name, key, ref in [(n, k, refs[k]) for n, k in jobs] + speed:
        rows = [r for r in plan if r['npc_name'] == name]
        r = max([x for x in rows if x['action'] == 'reuse'] or rows, key=lambda x: int(x['words'] or 0))
        d = D.get(r['questId'], {}).get(r['kind']) or direct.direct(r['questId']).get(r['kind'])
        out = f"{OUT}/{R3}/{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')}"; os.makedirs(out, exist_ok=True)
        dst = f'{out}/{ov.name_of(r)}_{key}.mp3'
        if not os.path.exists(dst): render.render_line(dict(r, action='generate', clone_ref=f'game:{ref}'), d, dst)
        print(f'{name:28} {key}', flush=True)

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'bank': bank, 'pick': pick, 'render': render_all, 'bank2': bank2, 'pick2': pick2, 'render2': render2, 'render3': render3}[sys.argv[1]]()
