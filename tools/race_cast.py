"""Race casting (2026-10-13, the producer's bake-off verdicts): the voices for the races the designs and packs did
worst -- trolls, tauren, undead, dwarves, goblins -- from Blizzard's own recordings (WoW NPC voice sets, a few
Warcraft III units), cloned per NPC. Writes data/race_cast.json: npc_id -> {src, ref, tempo, why}; overnight.py's
as_generated() renders those NPCs from `ref` and speeds the finished line by `tempo` (pitch kept).

Not here: orc men (keep their current voices), troll and orc women and dwarf women's recorded lines (the pack's own; KEEP_PACK), NPCs with
their own WoW recording (game:), and the characters with their own Warcraft III voice (OWN_WC3 below).

Run from data/ with the ComfyUI venv:  ~/ComfyUI/venv/bin/python ../tools/race_cast.py refs | cast
"""
import csv, glob, json, os, re, subprocess, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
CAST = 'race_cast.json'
WC3 = LV.SCRATCH
WOWSETS = f'{WC3}/bank'                 # bakeoff.py bank2 extracted the WoW sets here (wow_<set>/)
# source -> (reference, -, -, what it is). The troll Dark and tauren Shaman references were sped up 12% (approved);
# a slow line is otherwise brought up to its voice's floor after rendering (render.pace_up; overnight.PACE_FLOOR_BY_SRC).
SOURCES = {
    'dwarf_standard': ('clone_refs/rc_dwarf_standard.flac', 1.0, 1.15, 'dwarf, the standard Ironforge voice (approved)'),
    'dwarf_grim':     ('clone_refs/rc_dwarf_grim.flac', 1.0, 1.15, 'dwarf, grim and gravelly'),
    'dwarf_guard':    ('clone_refs/rc_dwarf_guard.flac', 1.0, 1.15, 'dwarf, a guard: "Keep your feet on the ground!"'),
    'dwarf_player':   ('clone_refs/r3_dwarf_player.flac', 1.0, 1.15, 'dwarf, lighter accent, plain-spoken'),
    # Plan C (2026-10-16, the producer): Vol'jin's own WoW speech (Zul'Farrak, "We were driven away, Great Spirit...")
    'troll_dark':     ('clone_refs/voljin_wow_greatspirit.flac', 1.0, 1.0, 'troll, the deepest and darkest (approved)'),
    'troll_standard': ('clone_refs/rc_troll_standard_t1.12.flac', 1.0, 1.0, 'troll, an ordinary troll'),
    'troll_shaman':   ('clone_refs/rc_troll_shaman_t1.12.flac', 1.0, 1.0, 'troll, a shaman or witch doctor'),
    'tauren_warrior': ('clone_refs/wow_taurenmalewarriornpc.flac', 1.0, 1.0, 'tauren, a warrior or hunter (approved)'),
    'tauren_shaman':  ('clone_refs/wow_taurenmaleshamannpc_t1.12.flac', 1.0, 1.0, 'tauren, a shaman, druid or elder (approved)'),
    'tauren_female':  ('clone_refs/wow_taurenfemaleofficialnpc.flac', 1.0, 1.0, 'tauren woman (approved)'),
    'undead_male':    ('clone_refs/wow_undeadmaledarknpc_t1.15.flac', 1.0, 1.0, 'Forsaken man, dark and sinister, a rasping whisper (approved)'),
    'undead_warrior': ('clone_refs/wow_undeadmalewarriornpc.flac', 1.0, 1.0, 'Forsaken man, a warrior: gravelly (unhurried; x1.15 lost the gravel)'),
    'undead_female':  ('clone_refs/wow_undeadfemalewarriornpc.flac', 1.0, 1.0, 'Forsaken woman (approved)'),
    'goblin_male':    ('clone_refs/wc3_goblinsapper.flac', 1.0, 1.0, 'goblin man, WC3 sapper (approved)'),
    'goblin_gruff':   ('clone_refs/gob_gruff.flac', 1.0, 1.0, 'goblin man, gruff and businesslike: a worker, trader or boss'),
    # Plan C (2026-10-16, the producer, blind): one continuous WC3 Gazlowe speech beat his stitched barks 3 of 3
    'goblin_gazlowe': ('clone_refs/wc3_gazlowe_planc.flac', 1.0, 1.0, 'goblin man, sly and fast-talking: a schemer, salesman or tinker'),
    'goblin_female':  ('clone_refs/wow_goblinfemalezanynpc.flac', 1.0, 1.0, 'goblin woman (approved)'),
    # dwarf women's lines no pack recorded (2026-10-17): Donova Snowden's pack voice from her short completion clip, the
    # reference that kept the accent (the producer, 2026-10-13: "new female dwarf is good"); recorded lines stay KEEP_PACK
    'dwarf_female_donova': ('clone_refs/dwarf_female_donova_short.flac', 1.0, 1.0, 'dwarf woman (approved)'),
    # orc women's lines no pack recorded (2026-10-17): Vlagga Freyfeather's 10120 completion clip, the one clone of
    # ours near the pack; their recorded lines stay KEEP_PACK
    'orc_female_vlagga': ('clone_refs/orc_female_vlagga.flac', 1.0, 1.0, 'orc woman'),
    # gnome women (2026-10-17, the producer): SpeakStone's two echo-free clips (the rest carry reverb). Betina's is the
    # everyday voice and the wider one; Chromie's is already so high and small it barely moves
    'gnome_female_betina':  ('clone_refs/gnome_female_betina.flac', 1.0, 1.0, 'gnome woman, the usual gnome voice: bright, quick and capable -- an engineer, officer, trader or townswoman'),
    'gnome_female_chromie': ('clone_refs/gnome_female_chromie.flac', 1.0, 1.0, 'gnome woman, very high, small and girlish: only for one notably young, tiny, whimsical or otherworldly'),
    # blood elf women (2026-10-30, the producer): the SpeakStone clones were flat (Magistrix Erona, the first voice a
    # blood elf hears) and Blizzard's noblewoman NPC set "sounds like an old woman" -- the race is the Horde's young,
    # glamorous one. The player character's own voice (speech-enUS BloodElfFemale: two flirts, a hello, five error
    # lines -- flirts alone would make every quest giver flirt) was "way better than both"
    'bloodelf_female_player': ('clone_refs/bloodelf_female_player.flac', 1.0, 1.0, 'blood elf woman, the player voice'),
    # blood elf men (2026-10-30): the player voice beat the Standard and Noble NPC sets and the pack clones on Arcanist
    # Helion and Well Watcher Solanian ("isn't as much an improvement as before"); two short flirts, a hello, six errors
    'bloodelf_male_player': ('clone_refs/bloodelf_male_player.flac', 1.0, 1.0, 'blood elf man, the player voice'),
}
GROUPS = {   # (race, sex) -> (sources to choose from, allowed shifts in semitones: down only, never up)
    ('Dwarf', 'male'):    (['dwarf_standard', 'dwarf_player'], [0.0]),   # grim and guard retired (2026-10-15); see VARY
    ('Troll', 'male'):    (['troll_dark', 'troll_shaman'], [0.0]),          # standard retired (2026-10-15); see VARY
    ('Tauren', 'male'):   (['tauren_warrior', 'tauren_shaman'], [0.0, -0.5, -1.0]),
    ('Tauren', 'female'): (['tauren_female'], [0.0, -0.5, -1.0]),
    ('Undead', 'male'):   (['undead_male', 'undead_warrior'], [0.0]),                        # see VARY
    ('Undead', 'female'): (['undead_female'], [0.0, -0.5, -1.0]),
    ('Goblin', 'male'):   (['goblin_gruff', 'goblin_gazlowe'], [0.0]),   # the sapper retired (2026-10-15): grating when slightly off
    ('Goblin', 'female'): (['goblin_female'], [0.0, -0.5]),
    ('Dwarf', 'female'):  (['dwarf_female_donova'], ('range', -1.0, 0.5)),   # -1 to +0.5 heard on 10-13
    ('Orc', 'female'):    (['orc_female_vlagga'], [0.0]),     # see VARY
    ('Gnome', 'female'):  (['gnome_female_betina', 'gnome_female_chromie'], [0.0]),     # see VARY
    ('Blood Elf', 'female'): (['bloodelf_female_player'], [0.0]),                        # see VARY
    ('Blood Elf', 'male'):   (['bloodelf_male_player'], [0.0]),                          # see VARY
}
# kept on their own voices inside a cast group: Aurastrasza, a red dragon in elf form (the producer's pick, 2026-10-28);
# Soridormi, a bronze dragon in elf form (heard against the player voice, 2026-10-30: the pack clone stays)
KEEP_OWN = {'Aurastrasza', 'Soridormi',
            # the eleven dragons in blood elf form, as Soridormi, until the producer hears one
            'Andormu', 'Erozion', "Sa'at", 'Mordenai', 'Barthamus', 'Tariolstrasz', 'Ceristrasz', 'Krasus', 'Vargastrasz',
            'Lord Itharius', 'Penumbrius'}
# Per-voice limits for varied() -- (pitch semitones lo, hi), (formant lo, hi), (pitch range lo, hi)[, 'diamond'] --
# set by the producer's ear on a 5x5 pitch x formant grid per voice (voice_test/race_grids/, 2026-10-14/15). A voice
# listed here gives every NPC his own draw inside its box; a voice not listed keeps its group's fixed shifts.
# 'diamond': the far corners of the box are out (|pitch|/half-width + |formant-1|/half-width <= 1.5).
# Pitch range 0.7-1.6 was heard on the Forsaken men only (0.5 too flat, 1.8 a hair too wide).
VARY = {
    'undead_male':    ((-4.0, 4.0), (0.84, 1.08), (0.7, 1.6)),   # over 1.08 turned them female
    'undead_female':  ((-4.0, 2.0), (0.92, 1.08), (0.7, 1.6)),
    'undead_warrior': ((-4.0, 4.0), (0.92, 1.16), (0.7, 1.6)),   # at 1x: x1.15 lost his gravel
    'tauren_female':  ((-4.0, 4.0), (0.92, 1.00), (0.7, 1.6)),   # over 1.00 no good; under 0.92 mannish
    'tauren_shaman':  ((-4.0, 4.0), (0.84, 1.16), (0.7, 1.6), 'diamond'),
    'tauren_warrior': ((-2.0, 4.0), (0.84, 1.00), (0.7, 1.6)),   # formant over 1.00 fails at every pitch
    'troll_dark':     ((-4.0, 4.0), (0.92, 1.08), (0.7, 1.6)),   # Vol'jin's grid, 2026-10-16
    'goblin_female':  ((-4.0, 2.0), (0.84, 1.08), (0.7, 1.6)),
    'troll_shaman':   ((-4.0, 4.0), (0.84, 1.00), (0.7, 1.6)),
    'goblin_gruff':   ((-4.0, 4.0), (0.92, 1.00), (0.7, 1.6)),
    'goblin_gazlowe': ((-2.0, 4.0), (0.94, 1.08), (0.7, 1.6)),   # the Plan C reference's grid, 2026-10-16
    'dwarf_standard': ((-4.0, 4.0), (1.00, 1.08), (0.7, 1.6)),   # formant under 1.00 loses the accent
    'dwarf_player':   ((-4.0, 2.0), (1.00, 1.08), (0.7, 1.6)),   # likewise
    'orc_female_vlagga':    ((-4.0, 4.0), (1.00, 1.00), (0.7, 1.6)),   # her grid, 2026-10-17: pitch only
    'gnome_female_betina':  ((-4.0, 4.0), (0.92, 1.00), (0.7, 1.6)),   # her grid, 2026-10-17
    'gnome_female_chromie': ((-4.0, 0.0), (1.00, 1.16), (0.7, 1.6)),   # her grid: p0/f1.16 to p-4/f1.00, no higher
    # her grid, 2026-10-30: -2/0.92 to +4/1.08. Pitch range never under 1.0: flatness is what she was recast for
    'bloodelf_female_player': ((-2.0, 4.0), (0.92, 1.08), (1.0, 1.6)),
    'bloodelf_male_player':   ((-4.0, 4.0), (0.92, 1.08), (1.0, 1.6)),   # his grid, 2026-10-30: the full range
}

# the women whose own clip a source is: their voice unshifted (2026-10-17)
OWN_CLIP = {'Chromie': 'gnome_female_chromie', 'Betina Bigglezink': 'gnome_female_betina', 'Vlagga Freyfeather': 'orc_female_vlagga'}
OWN_WC3 = {'Rexxar': 'clone_refs/rexxar.flac', 'Nazgrel': 'clone_refs/nazgrel.flac', 'Rokhan': 'clone_refs/rokhan.flac',
           'Shandris Feathermoon': 'clone_refs/shandris.flac', 'Malfurion Stormrage': 'clone_refs/furion.flac'}

def full_ref(folder, dst, want=15.0):
    """every clip of a WoW NPC voice set, longest first with the irritated ones last -- round 3 built dwarf references
    from greetings over 1.2 s only (5.5 s of speech) and the accent thinned; the full set (S1) was best"""
    fs = glob.glob(f'{folder}/*.wav')
    dur = lambda p: float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p],
                                         capture_output=True, text=True).stdout or 0)
    fs = sorted(fs, key=lambda p: ('pissed' in p.lower(), -dur(p)))
    n = len(fs); inp = sum((['-i', p] for p in fs), [])
    flt = ''.join(f'[{i}:a]aresample=24000,aformat=channel_layouts=mono,silenceremove=start_periods=1:start_threshold=-45dB:'
                  f'stop_periods=1:stop_threshold=-45dB:stop_duration=0.2,apad=pad_dur=0.25[a{i}];' for i in range(n))
    flt += ''.join(f'[a{i}]' for i in range(n)) + f'concat=n={n}:v=0:a=1,loudnorm=I=-20:TP=-2[o]'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *inp, '-filter_complex', flt, '-map', '[o]', '-t', str(want), dst], check=True)
    return dst

def tempo(src, f, dst):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-af', f'atempo={f}', dst], check=True); return dst

def refs():
    os.makedirs('clone_refs', exist_ok=True)
    subprocess.run(['cp', 'clone_refs/r3c_dwarf_standard_full.flac', 'clone_refs/rc_dwarf_standard.flac'], check=True)
    full_ref(f'{WOWSETS}/wow_dwarfmalegrimnpc', 'clone_refs/rc_dwarf_grim.flac')
    full_ref(f'{WOWSETS}/wow_dwarfmaleguardnpc', 'clone_refs/rc_dwarf_guard.flac')
    tempo(full_ref(f'{WOWSETS}/wow_trollmalestandardnpc', 'clone_refs/rc_troll_standard.flac'), 1.12, 'clone_refs/rc_troll_standard_t1.12.flac')
    tempo(full_ref(f'{WOWSETS}/wow_trollmaleshamannpc', 'clone_refs/rc_troll_shaman.flac'), 1.12, 'clone_refs/rc_troll_shaman_t1.12.flac')
    if not os.path.exists('clone_refs/wow_taurenmaleshamannpc_t1.12.flac'):
        tempo('clone_refs/wow_taurenmaleshamannpc.flac', 1.12, 'clone_refs/wow_taurenmaleshamannpc_t1.12.flac')
    missing = [s for s, v in SOURCES.items() if not os.path.exists(v[0])] + [n for n, p in OWN_WC3.items() if not os.path.exists(p)]
    print('references ready' if not missing else f'!! missing: {missing}')

def pitch_for(npc_id, shifts):
    """the NPC's pitch shift in semitones, fixed by his id: one of a list, or -- ('range', lo, hi) -- anywhere in the range
    in 0.1 steps (the producer, 2026-10-14: three fixed pitches made a town of three men; the reference is the floor
    for the Forsaken and a shift moves pitch AND formant together, so a raised man is a different, slighter man)"""
    h = zlib.crc32(npc_id.encode())
    if isinstance(shifts, tuple) and shifts[0] == 'range':
        lo, hi = shifts[1], shifts[2]; return round(lo + (h % (round((hi - lo) * 10) + 1)) / 10, 1)
    return shifts[h % len(shifts)]

VARY_DIR = 'vary_refs'          # made from the reference, not tracked (rebuilt on demand: same id, same voice)

def varied(ref, npc_id, spec):
    """the 2026-10-14 grid (the producer's ear): one reference made into many men by shifting the REFERENCE's pitch and
    formant independently (voice_vary.py, Praat Change Gender) -- pitch -4..+4 semitones all passed for men; formant
    over 1.08 turned them female (f1.16 at either end of pitch); pitch range 0.5 was too flat, 1.8 a hair too wide. Changing the finished line instead was rejected
    (audible autotune at the pitch extremes, worse overall). Each man's two draws are fixed by his id."""
    (p0, p1), (f0, f1), (r0, r1) = spec[:3]
    vo = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    os.makedirs(VARY_DIR, exist_ok=True)
    # a draw outside a 'diamond', or one Praat cannot finish (2026-10-15: gob_gruff p+2.6 f0.99 r1.60 spun for two
    # hours), is drawn again with the next salt -- the same id still always gives the same voice
    fails = 0
    for k in range(100):
        salt = f':{k}' if k else ''
        hp, hf = zlib.crc32(f'pitch:{npc_id}{salt}'.encode()), zlib.crc32(f'formant:{npc_id}{salt}'.encode())
        st = round(p0 + hp % (round((p1 - p0) * 10) + 1) / 10, 1)
        fm = round(f0 + hf % (round((f1 - f0) * 100) + 1) / 100, 2)
        if 'diamond' in spec[3:] and abs(st - (p0 + p1) / 2) / ((p1 - p0) / 2) + abs(fm - (f0 + f1) / 2) / ((f1 - f0) / 2) > 1.5: continue
        rg = round(r0 + zlib.crc32(f'range:{npc_id}{salt if fails else ""}'.encode()) % (round((r1 - r0) * 20) + 1) / 20, 2)
        dst = f"{VARY_DIR}/{os.path.basename(ref).rsplit('.', 1)[0]}_p{st:+.1f}_f{fm:.2f}_r{rg:.2f}.wav"
        if os.path.exists(dst): break
        try:
            subprocess.run([f'{vo}/.venv/bin/python', '-W', 'ignore', f'{vo}/tools/voice_vary.py', ref, dst, str(st), str(fm), str(rg)],
                           check=True, capture_output=True, timeout=120)
            break
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            fails += 1
            if os.path.exists(dst): os.remove(dst)
    return st, fm, rg, dst

def shifted(ref, st):
    if not st: return ref
    dst = ref.rsplit('.', 1)[0] + f'_{st:+.1f}.wav'
    if not os.path.exists(dst): subprocess.run(['rubberband-r3', '-q', '-p', str(st), ref, dst], check=True)  # one pass
    return dst

SYSTEM = """You cast voices for an English voice-over of World of Warcraft quest givers. For one character, choose \
the voice that best suits them -- their age, temperament, calling and manner -- from the list. Answer JSON: \
{"voice": "<exactly one name from the list>", "why": "<a few words>"}"""

def cast():
    import direct, design_voices, bakeoff
    prof = design_voices.profiles()
    have = json.load(open(CAST)) if os.path.exists(CAST) else {}
    speakers = {}
    for r in csv.DictReader(open('plan_v3.csv')):
        if not r['npc_id'].isdigit() or r['clone_ref'].startswith('game:'): continue
        if r['npc_name'] in OWN_WC3:
            speakers[r['npc_id']] = ('own', r); continue
        if r['npc_name'] in KEEP_OWN: continue
        if r['npc_name'] in OWN_CLIP:
            speakers[r['npc_id']] = ('own_clip', r); continue
        if (r['race'], r['sex']) in GROUPS: speakers.setdefault(r['npc_id'], ('group', r))
    n = 0
    for c, (kind, r) in speakers.items():
        if c in have: continue
        if kind == 'own_clip':
            src = OWN_CLIP[r['npc_name']]
            have[c] = {'name': r['npc_name'], 'race': r['race'], 'sex': r['sex'], 'src': src, 'shift': 0.0,
                       'ref': SOURCES[src][0], 'tempo': 1.0, 'why': 'her own clip, unshifted'}
        elif kind == 'own':
            have[c] = {'name': r['npc_name'], 'src': 'own_wc3', 'ref': OWN_WC3[r['npc_name']], 'tempo': 1.0, 'why': 'their own Warcraft III voice'}
        else:
            opts, shifts = GROUPS[(r['race'], r['sex'])]
            if len(opts) == 1: src, why = opts[0], 'the one approved voice'
            else:
                p = prof.get(c, {})
                user = (f"Character: {r['npc_name']}, {r['sex']} {r['race']}, {p.get('age', '')}.\n"
                        f"Who they are: {direct.PERSONA.get(c, p.get('persona', ''))}\n"
                        f"Their voice, per the profile: {p.get('voice', '')}\nVoices:\n"
                        + '\n'.join(f'- {o}: {SOURCES[o][3]}' for o in opts))
                try:
                    a = bakeoff.llm(SYSTEM, user, {'type': 'object', 'required': ['voice', 'why'], 'properties': {
                        'voice': {'type': 'string', 'enum': opts}, 'why': {'type': 'string'}}})
                    src, why = a['voice'], a['why']
                except Exception as e:
                    src, why = opts[zlib.crc32(c.encode()) % len(opts)], f'(model failed: {str(e)[:60]})'
            ref, _, line_tempo, _ = SOURCES[src]
            if src in VARY:
                st, fm, rg, vref = varied(ref, c, VARY[src])
                have[c] = {'name': r['npc_name'], 'race': r['race'], 'sex': r['sex'], 'src': src, 'shift': st, 'formant': fm, 'range': rg,
                           'ref': vref, 'tempo': line_tempo, 'why': why}
            else:
                st = pitch_for(c, shifts)
                have[c] = {'name': r['npc_name'], 'race': r['race'], 'sex': r['sex'], 'src': src, 'shift': st,
                           'ref': shifted(ref, st), 'tempo': line_tempo, 'why': why}
        n += 1
        if n % 25 == 0: json.dump(have, open(CAST, 'w'), indent=1); print(n, 'cast', flush=True)
    json.dump(have, open(CAST, 'w'), indent=1)
    import collections
    print(len(have), 'cast:', dict(collections.Counter(v['src'] for v in have.values())))

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'refs': refs, 'cast': cast}[sys.argv[1]]()
