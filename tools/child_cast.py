"""The child cast (2026-10-12): every child in the plan (clone_ref design:*_child) gets its clone reference in
designed_voices/<npc>.mp3, where render.speaker_ref looks for designed voices.

Boys: young Anduin's three client greetings (Joey Cash; Sound\\Creature\\KingAnduinWrynn) -- the producer's pick "BY
FAR" over every dataset boy. Billy Maclure is Anduin unshifted (the approved take); every other boy gets his own
small pitch/formant offset so thirty boys are not one boy. NPCs sharing a name (Matthias Lehner x5, Corki x2) share
an offset.
Girls: Qwen3 Voice Design from the girl's casting description (design_voices.py cast), shifted +6 pitch / +2
formant into a child's range (round 2's girl_p6_f2, which the producer kept).

Run from data/:
  ../.venv/bin/python ../tools/design_voices.py cast <girls' quests>      (Gemma: casting for girls without one)
  ~/ComfyUI/venv/bin/python ../tools/child_cast.py boys                   (CPU)
  ~/ComfyUI/venv/bin/python ../tools/child_cast.py girls [npc ids]        (card-1 ComfyUI 42422)
  ~/ComfyUI/venv/bin/python ../tools/child_cast.py girls-reshift [ids]   (CPU: re-shift the designed girls to 335-390 Hz)
  ~/ComfyUI/venv/bin/python ../tools/child_cast.py list                   (children and their quests)
"""
import csv, glob, hashlib, json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import child_voice

ROOT = f'{LV.COMFY_OUT}'
CLIENT = f'{LV.WOW_DATA}'
ANDUIN = 'child_refs/anduin_ref.wav'; BILLY = '247'
LISTEN = f'{ROOT}/voice_test/child_cast'
BOY_OFFSETS = [(-1.0, -0.5), (-0.5, -0.5), (0.5, 0.0), (1.0, 0.5), (-1.5, -1.0), (1.5, 0.5), (0.5, 0.5), (-0.5, 0.0)]
GIRL_SHIFT = (6, 2)          # first take (2026-10-12): too high for all but the tauren girls -- see girls-reshift
# (2026-10-12, the producer) Mootoo the Younger (~390 Hz median after the shift) is the CEILING; the others sounded
# chipmunk at 474-577 Hz. girls-reshift lands every girl between these, ordered by how high her designed voice was
# (tauren lowest, goblins highest), keeping the +2 formant shift that makes a smaller child, not a pitched-up woman.
GIRL_FLOOR_HZ, GIRL_CEILING_HZ, GIRL_FORMANT = 290.0, 335.0, 2
# (2026-10-12, second listen) the tauren girls must be the DEEPEST and everyone was still a bit high: 290-335 Hz.
# A big downward pitch shift with the formants raised is what sounded like a cheap voice changer (Sprinkle, Liv:
# -4 to -5.5 semitones, worst on long high vowels): a girl whose designed voice would need more than
# GIRL_MAX_DROP semitones down is designed again, lower, from her own casting (girls-redesign), not shifted harder.
GIRL_MAX_DROP = 2.5
# The corruption comes from childify's PITCH-ONLY pass (pitch - formant), not the total: Sprinkle and Liv had
# -2.5 pitch with +2 formant = -4.5 pitch-only. These two are shifted in ONE pass (formant = pitch): fuller, clean.
GIRL_ONE_PASS = {'7583', '8496'}
# (third listen, 2026-10-12) the one-pass goblins "sound human -- more human than the other girls", and Emily, the
# one the producer called about perfect, was nearly one-pass already (+2.4 / +2): moving pitch and formants TOGETHER
# keeps a designed child natural; raising the formants on top of an already-young voice made them chipmunk. Every
# girl is now shifted in one pass to her target. The goblin girls drop only GOBLIN_DROP so they stay brighter and
# smaller than the rest -- goblins, not human girls.
GIRL_ALL_ONE_PASS = True
# the producer's pick (2026-10-12, B over a one-pass -1): the human girls' formant lift, a gentle pitch drop -- the
# pitch-only step stays at 2.5, clean, and they keep a goblin's smaller, brighter sound
GOBLIN_GIRLS = {'7583': (-0.5, 2.0), '8496': (-0.5, 2.0)}
LOWER = (" Her voice sits in a low-to-mid register for a child: soft and warm, never shrill, squeaky or piping.")
DEESS = 'deesser=i=0.5:m=0.5:f=0.5:s=o'          # on the finished child line, never on the reference ("pipe")

def children():
    out = {}
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['clone_ref'].endswith('_child'):
            e = out.setdefault(r['npc_id'], {'name': r['npc_name'], 'race': r['race'], 'sex': r['sex'], 'quests': set()})
            e['quests'].add(r['questId'])
    return out

def anduin_ref():
    """the three greetings, 22 kHz from the client, joined with short gaps -> 24 kHz mono"""
    if os.path.exists(ANDUIN): return ANDUIN
    from mpqget import MPQ
    os.makedirs('child_refs/src', exist_ok=True)
    m = MPQ(glob.glob(CLIENT + '/*/speech-enUS.MPQ')[0]); fs = []
    for n in (1, 2, 3):
        p = f'child_refs/src/KingAnduinWrynnGreeting0{n}.wav'
        open(p, 'wb').write(m.read(f'Sound\\Creature\\KingAnduinWrynn\\KingAnduinWrynnGreeting0{n}.wav')); fs.append(p)
    m.close()
    ins = sum([['-i', f] for f in fs], [])
    flt = ''.join(f'[{i}:a]aresample=24000,aformat=channel_layouts=mono,apad=pad_dur=0.35[a{i}];' for i in range(3))
    flt += '[a0][a1][a2]concat=n=3:v=0:a=1,loudnorm=I=-20:TP=-2'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *ins, '-filter_complex', flt, '-ar', '24000', ANDUIN], check=True)
    return ANDUIN

# (2026-10-12, the producer) "all the boys have IDENTICAL voices": eight table entries for 31 boys, +-1.5 semitones,
# whole groups byte-identical. Now each boy (by name) gets his own continuous pitch and formant offsets over a wider
# range, the heavier races leaning lower; the pitch-only part stays within 2.5 semitones (beyond it the shifter
# corrupts the voice, as the goblin girls showed).
# (second listen) "not enough, especially the non-human races": each race has its own place -- pitch and formant
# (vocal-tract size) -- and each boy varies about +-1 semitone around it; the pitch-only part stays within 2.
RACE_BOY = {'tauren': (-3.0, -2.0), 'orc': (-2.0, -1.5), 'broken': (-2.0, -1.5), 'dwarf': (-1.0, -1.5),
            'troll': (-1.5, -1.0), 'draenei': (-1.5, -1.0), 'gnome': (1.5, 1.2), 'goblin': (1.5, 1.0),
            'blood elf': (0.3, 0.3), 'night elf': (0.0, 0.0), 'human': (0.0, 0.0)}

def offset(name, race=''):
    h = hashlib.md5(name.encode()).digest()
    u1, u2 = h[0] / 255.0, h[1] / 255.0
    bp, bf = RACE_BOY.get(race.lower().replace('ss:', ''), (0.0, 0.0))
    dp = -1.0 + 2.0 * u1
    pitch = bp + dp
    formant = bf + 0.5 * dp + (u2 - 0.5)
    if abs(pitch - formant) > 2.0:
        formant = pitch - 2.0 if pitch > formant else pitch + 2.0
    return round(pitch, 2), round(formant, 2)

def clear_cache(npc):
    """render.speaker_ref caches the first 12 s of designed_voices/<npc>.mp3 -- a stale copy would keep the old voice"""
    for f in glob.glob(f'refs_cache/ref12_designed_voices_{npc}.mp3.wav'): os.remove(f)

def save(src, npc, name):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-ac', '1', '-ar', '24000', '-b:a', '192k',
                    f'designed_voices/{npc}.mp3'], check=True)
    clear_cache(npc); os.makedirs(LISTEN, exist_ok=True)
    shutil.copy(f'designed_voices/{npc}.mp3', f"{LISTEN}/{name.replace(' ', '_')}_{npc}.mp3")

def boys():
    base = anduin_ref(); os.makedirs('child_refs', exist_ok=True)
    for npc, c in children().items():
        if c['sex'] != 'male': continue
        if npc == BILLY: p, f = 0.0, 0.0; src = base
        else:
            p, f = offset(c['name'], c['race']); src = child_voice.childify(base, f'child_refs/boy_{npc}.wav', p, f)
        save(src, npc, c['name']); print(f"{c['name']} ({npc}): pitch {p:+}, formant {f:+}", flush=True)

def girls(only):
    import design_voices
    cast = json.load(open(design_voices.CAST))
    for npc, c in children().items():
        if c['sex'] != 'female' or (only and npc not in only): continue
        if npc not in cast: print(f"!! {c['name']} ({npc}) has no casting -- run design_voices.py cast first", flush=True); continue
        k = cast[npc]
        wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
                  'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
                  'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
              '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0],
                  'voice_description': k['description'], 'reference_text': k['reference_text'], 'language': 'English',
                  'character_name': f'wow_child_{npc}', 'overwrite_character': True}},
              '3': {'class_type': 'SaveAudio', 'inputs': {'audio': ['2', 1], 'filename_prefix': f'voice_test/child_cast/parts/{npc}'}}}
        src = design_voices.run(wf)
        shifted = child_voice.childify(src, f'child_refs/girl_{npc}.wav', *GIRL_SHIFT)
        save(shifted, npc, c['name']); print(f"{c['name']} ({npc})", flush=True)

def median_f0(path):
    import librosa, numpy as np
    y, sr = librosa.load(path, sr=16000, mono=True)
    f, voiced, _ = librosa.pyin(y, fmin=80, fmax=700, sr=sr)
    f = f[voiced]
    return float(np.median(f)) if len(f) else 0.0

# third pass (2026-10-12): written by hand where the casting text kept the designer high ("The pitch is high and
# bright"; Emily's "bright clarity") -- pitch first, the person's accent and manner kept
GIRL_DESC_LOW = {
    '7583': ("A mid-low, slightly raspy voice for a goblin girl of about twelve, warm rather than squeaky. She talks "
             "fast with a nasal New York hustler lilt, bubbly and mischievous, punching her words with sharp, "
             "expressive inflections."),
    '8496': ("A mid-low, textured and slightly scratchy voice for a goblin girl of about twelve, never shrill. Quick, "
             "nasal New York hustler lilt; energetic and bubbly, always on the move, rapid-fire pace."),
    '26588': ("A soft, mid-low and gently breathy voice for a girl of about eleven, with a Southern English accent. "
              "Earnest and polite, a little quickened by wonder, natural for her age, never bright or piping."),
}

TARGETS = 'child_refs/girl_targets.json'   # fixed once, from the FIRST designs' order (tauren lowest): a redesign
                                          # must not reorder the girls

def girl_targets():
    """npc -> (designed Hz, target Hz, source): targets spread floor..ceiling in the order of designed pitch; the
    order (target) comes from TARGETS once it exists"""
    fixed = json.load(open(TARGETS)) if os.path.exists(TARGETS) else None
    parts = f'{LISTEN}/parts'
    girls = []
    for npc, c in children().items():
        src = f'{parts}/{npc}_00001.flac'
        if c['sex'] == 'female' and os.path.exists(src):
            girls.append((median_f0(src), npc, src))
    girls.sort()
    out = {npc: (hz, GIRL_FLOOR_HZ + (GIRL_CEILING_HZ - GIRL_FLOOR_HZ) * (i / max(1, len(girls) - 1)), src)
           for i, (hz, npc, src) in enumerate(girls)}
    if fixed:
        out = {npc: (hz, fixed.get(npc, t), src) for npc, (hz, t, src) in out.items()}
    else:
        json.dump({npc: round(t, 1) for npc, (hz, t, src) in out.items()}, open(TARGETS, 'w'), indent=1)
    return out

def girls_redesign(only, older=False, tries=1):
    """design again, lower, every girl whose voice would need more than GIRL_MAX_DROP semitones down (or those
    named); same casting, 'high-pitched' softened and LOWER appended. Card-1 ComfyUI."""
    import math, re, design_voices
    cast = json.load(open(design_voices.CAST))
    for npc, (hz, target, src) in girl_targets().items():
        drop = 12 * math.log2(target / hz)
        if (only and npc not in only) or (not only and drop >= -GIRL_MAX_DROP):
            continue
        k = cast[npc]
        desc = re.sub(r'\b(very )?high[- ]pitched\b', 'light', k['description'], flags=re.I) + LOWER
        if older:   # second pass: "a young girl of seven" outweighed LOWER -- an older girl, low for her age; the
                    # child shift's formant step makes her younger again
            desc = re.sub(r'\b(a )?(young )?(female child|girl)( of (about |roughly )?\w+ years( old)?)?\b',
                          'a girl of about thirteen', desc, count=1, flags=re.I)
            desc += " Her voice is low and soft for her age, slightly husky, never bright or shrill."
        if npc in GIRL_DESC_LOW:
            desc = GIRL_DESC_LOW[npc]
        best = None
        wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
                  'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
                  'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
              '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0],
                  'voice_description': desc, 'reference_text': k['reference_text'], 'language': 'English',
                  'character_name': f'wow_child_{npc}_low', 'overwrite_character': True}},
              '3': {'class_type': 'SaveAudio', 'inputs': {'audio': ['2', 1], 'filename_prefix': f'voice_test/child_cast/parts/{npc}_low'}}}
        for attempt in range(tries):
            out = design_voices.run(wf)
            got = median_f0(out)
            if best is None or got < best[0]:
                best = (got, out)
            if 12 * math.log2(target / got) >= -GIRL_MAX_DROP:
                break
        shutil.copy(best[1], src)          # the girl's designed voice is now the lowest take
        print(f"{k['name']} ({npc}): {hz:.0f} Hz needed {drop:+.1f} st -> designed again at {best[0]:.0f} Hz "
              f"({attempt + 1} tries; now needs {12 * math.log2(target / best[0]):+.1f} st)", flush=True)
        print(f"   description: {desc}", flush=True)

def girls_reshift(only, listen_dir):
    """re-shift the girls' EXISTING designed voices (no new Voice Design) to a pitch between the floor and the
    ceiling, in the order of their designed pitch"""
    import math
    os.makedirs(listen_dir, exist_ok=True)
    names = {npc: c['name'] for npc, c in children().items()}
    for npc, (hz, target, src) in sorted(girl_targets().items(), key=lambda kv: kv[1][1]):
        name = names[npc]
        # never more than GIRL_MAX_DROP down: past that the shifter corrupts the voice (the goblin girls, whose
        # designs stay high whatever the description says, end a little above the others -- goblins run high)
        pitch = round(max(12 * math.log2(target / hz), -GIRL_MAX_DROP), 2)
        if only and npc not in only:
            continue
        formant = pitch if (GIRL_ALL_ONE_PASS or npc in GIRL_ONE_PASS) else GIRL_FORMANT
        if npc in GOBLIN_GIRLS:
            pitch, formant = GOBLIN_GIRLS[npc]
        out = child_voice.childify(src, f'child_refs/girl_{npc}.wav', pitch, formant)
        save(out, npc, name)
        shutil.copy(f'designed_voices/{npc}.mp3', f"{listen_dir}/{name.replace(' ', '_')}_{npc}.mp3")
        print(f"{name} ({npc}): designed {hz:.0f} Hz -> target {target:.0f} Hz (pitch {pitch:+}, formant {formant:+}), "
              f"measured {median_f0(out):.0f} Hz", flush=True)

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'boys': boys()
    elif cmd == 'girls': girls(set(sys.argv[2:]))
    elif cmd == 'girls-reshift': girls_reshift(set(sys.argv[2:]), f'{LISTEN}/girls_v4')
    elif cmd == 'girls-redesign': girls_redesign(set(sys.argv[2:]))
    elif cmd == 'girls-redesign-older': girls_redesign(set(sys.argv[2:]), older=True, tries=3)
    elif cmd == 'list':
        for npc, c in children().items(): print(npc, c['name'], c['sex'], c['race'], ' '.join(sorted(c['quests'], key=int)))
