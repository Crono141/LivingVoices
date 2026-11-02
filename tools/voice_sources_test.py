"""Clone sources for speakers the plan designed or left to the narrator (2026-10-13): their own Warcraft III voice,
or a voiced creature with the same body (model), against the pack's take where one exists. One real line each,
directed and rendered on card 0. -> <listen>/voice_test/sources/<speaker>/{ours,pack,ref}.*
Run from data/ with the venv that has mpyq (WoW sources) and the ComfyUI venv's requests:
  PYTHONPATH=../tools ../.venv/bin/python ../tools/voice_sources_test.py extract     (references; no GPU)
  ~/ComfyUI/venv/bin/python ../tools/voice_sources_test.py render                    (card 0 via the arbiter)
"""
import csv, glob, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
ROOT = f'{LV.COMFY_OUT}/voice_test/sources'
WC3 = LV.SCRATCH
REFS = 'clone_refs'                # data/clone_refs/<key>.wav: the assembled reference, ~12 s of speech
WANT = [  # (speaker name in plan_v3.csv, key, kind, source)
    ('Rexxar', 'rexxar', 'wc3', ['dlg:Rexxar']),
    ('Nazgrel', 'nazgrel', 'wc3', ['dlg:Nazgrel', 'unit:Nazgrel']),
    ('Shandris Feathermoon', 'shandris', 'wc3', ['dlg:Shandris', 'unit:Shandris']),
    ('Rokhan', 'rokhan', 'wc3', ['dlg:Rokhan', 'unit:Rokhan']),
    ('Malfurion Stormrage', 'furion', 'wc3', ['dlg:Furion', 'unit:Furion']),
    ('Keeper Remulos', 'keeper_of_the_grove', 'wc3', ['unit:HeroKeeperOfTheGrove']),
    ("Mog'dorg the Wizened", 'wc3_ogre', 'wc3', ['unit:Ogre']),
    ('Anachronos', 'sartharion', 'wow', 'Sartharion'),
    ('Wind Trader Zhareem', 'xevozz', 'wow', 'Xevozz'),
    ('Parshah', 'ikiss', 'wow', 'Talon King Ikiss'),
    ('Avatar of Freya', 'freya', 'wow', 'Freya'),
    ('The Bone Witch', 'sara', 'wow', 'Sara'),
    ('Duke Hydraxis', 'hydross', 'wow', 'Hydross the Unstable'),
    ("Chu'a'lor", 'blackheart', 'wow', 'Blackheart the Inciter'),
    # flesh golems (2026-10-13): two WoW golems with the same model, and WC3's abomination
    ('Sergeant Gorth', 'patchwerk', 'wow', 'Patchwerk'),
    ('Sergeant Gorth', 'meathook', 'wow', 'Meathook'),
    ('Sergeant Gorth', 'wc3_abomination', 'wc3', ['unit:Abomination']),
    # Aurastrasza (2026-10-28, the producer: the pack's voice is "incredibly generic and without emotion" for a red
    # dragon in blood-elf form): the voiced red dragonflight women in the client
    ('Aurastrasza', 'alexstrasza', 'wow', 'Alexstrasza the Life-Binder'),
    ('Aurastrasza', 'xerestrasza', 'wow', 'Xerestrasza'),
    ('Aurastrasza', 'keristrasza', 'wow', 'Keristrasza'),
]

def dur(p):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p],
                                capture_output=True, text=True).stdout or 0)

def calm(clips, texts, skip_broken=True):
    """clips in the order a reference should take them: the speaker's calmest first. A boss's lines are all yells
    (creature_text type 14) and its death lines are slow and broken -- the producer heard Chu'a'lor and Freya
    shouting all the time, Hydraxis and the Bone Witch dying (2026-10-13). So: an ordinary pace (1.8-4 words a
    second, where the text is known) and, among those, the lowest pitch for that speaker; the rest after."""
    import librosa, numpy as np
    rated = []
    for p in clips:
        d = dur(p)
        if d < 1.2: continue
        y, sr = librosa.load(p, sr=16000, mono=True)
        f0, _, _ = librosa.pyin(y, fmin=50, fmax=500, sr=sr); f0 = f0[~np.isnan(f0)]
        pitch = float(np.median(f0)) if len(f0) else 999.0
        w = len((texts.get(p) or '').split()); wps = w / d if w else 2.5
        broken = skip_broken and ('..' in (texts.get(p) or '') or '\u2026' in (texts.get(p) or ''))   # trailing off (Sara)
        rated.append((0 if 1.8 <= wps <= 4.0 and not broken else 1, pitch, d, p))
    return [p for *_, p in sorted(rated)]

def assemble(clips, dst, want=12.0, ordered=False):
    """clips in the given order (ordered) or longest first, until ~want seconds, each trimmed of silence, joined
    with short gaps; mono 24 kHz"""
    clips = [(dur(p), p) for p in clips] if ordered else sorted(((dur(p), p) for p in clips), reverse=True)
    pick, tot = [], 0.0
    for d, p in clips:
        if d < 1.2: continue
        pick.append(p); tot += d
        if tot >= want: break
    if not pick: raise RuntimeError(f'no usable clips for {dst}')
    inp = sum((['-i', p] for p in pick), [])
    flt = ''.join(f'[{i}:a]aresample=24000,aformat=channel_layouts=mono,silenceremove=start_periods=1:start_threshold=-45dB:'
                  f'stop_periods=1:stop_threshold=-45dB:stop_duration=0.3,apad=pad_dur=0.25[a{i}];' for i in range(len(pick)))
    flt += ''.join(f'[a{i}]' for i in range(len(pick))) + f'concat=n={len(pick)}:v=0:a=1,loudnorm=I=-20:TP=-2[o]'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *inp, '-filter_complex', flt, '-map', '[o]', '-t', '15', dst], check=True)
    return tot, len(pick)

def extract():
    from mpqget import MPQ
    os.makedirs(REFS, exist_ok=True); tmp = f'{WC3}/srcclips'; os.makedirs(tmp, exist_ok=True)
    cat = json.load(open(f'{WC3}/wc3_catalog.json'))
    wow = wow_voiced({w[3] for w in WANT if w[2] == 'wow'})
    only = set(sys.argv[2:])
    for name, key, kind, src in WANT:
        if only and key not in only: continue
        d = f'{tmp}/{key}'; os.makedirs(d, exist_ok=True)
        if kind == 'wc3':
            for ck in src:
                for a, f in cat.get(ck, []):
                    m = MPQ(f'{WC3}/{a}'); open(f"{d}/{f.rsplit(chr(92), 1)[1]}", 'wb').write(m.read(f)); m.close()
        else:
            texts = {}
            for mpq, f, t in wow.get(src, []):
                b = f.rsplit(chr(92), 1)[1]; texts[f'{d}/{b}'] = t
                m = MPQ(mpq); open(f'{d}/{b}', 'wb').write(m.read(f)); m.close()
        clips = glob.glob(f'{d}/*')
        if not clips: print('!!', name, 'no clips from', src); continue
        tot, n = assemble(calm(clips, texts if kind == 'wow' else {}), f'{REFS}/{key}.wav', ordered=True)
        print(f'{name:24} <- {src}: {len(clips)} clips, reference {tot:.1f} s from {n}')

def wow_voiced(names):
    """creature name -> [(mpq path, file)] of its recorded speech (creature_text / broadcast_text sounds)"""
    import struct
    from sqlrows import rows
    import mpyq
    SQL = f'{LV.AC_SQL}/'
    CLIENT = f'{LV.WOW_DATA}/'
    MPQS = ['enUS/speech-enUS.MPQ', 'enUS/expansion-speech-enUS.MPQ', 'enUS/lichking-speech-enUS.MPQ',
            'enUS/patch-enUS.MPQ', 'enUS/patch-enUS-2.MPQ', 'enUS/patch-enUS-3.MPQ']
    def sqltable(name):
        txt = open(SQL + name + '.sql', encoding='utf-8', errors='replace').read()
        body = txt[txt.index('CREATE TABLE'):]; body = body[:body.index(') ENGINE')]
        c = [m.group(1) for m in re.finditer(r'^\s+`(\w+)`', body, re.M)]
        for r in rows(SQL + name + '.sql', null=''): yield dict(zip(c, r))
    where = {}
    for m in MPQS:
        for f in mpyq.MPQArchive(CLIENT + m, listfile=True).files or []:
            f = f.decode('utf-8', 'replace')
            if f.lower().endswith(('.wav', '.mp3', '.ogg')): where[f.lower()] = (CLIENT + m, f)
    b = open('dbc/SoundEntries.dbc', 'rb').read(); _, n, fc, rs, ss = struct.unpack('<4s4I', b[:20]); strs = b[20 + n * rs:]
    s = lambda o: strs[o:strs.index(b'\0', o)].decode('utf-8', 'replace')
    sound = {}
    for i in range(n):
        r = struct.unpack(f'<{fc}I', b[20 + i * rs:20 + (i + 1) * rs]); base = s(r[23]).rstrip('\\')
        sound[r[0]] = [((base + '\\') if base else '') + s(r[3 + j]) for j in range(10) if r[3 + j]]
    ids = {r['entry'] for r in sqltable('creature_template') if r['name'] in names}
    name_of = {r['entry']: r['name'] for r in sqltable('creature_template') if r['entry'] in ids}
    bt = {r['ID']: int(r['SoundEntriesId'] or 0) for r in sqltable('broadcast_text') if r['SoundEntriesId'] not in ('', '0')}
    out = {}
    for r in sqltable('creature_text'):
        if r['CreatureID'] not in ids: continue
        for sid in (int(r['Sound'] or 0), bt.get(r['BroadcastTextId'], 0)):
            for p in sound.get(sid, []) if sid else []:
                w = where.get(p.lower())
                if w and w not in [x[:2] for x in out.setdefault(name_of[r['CreatureID']], [])]:
                    out[name_of[r['CreatureID']]].append((*w, r['Text']))
    return out

def render_all():
    import render, overnight as ov, direct, actor_read
    render.use_server(LV.RENDERERS["0"])
    if ALPHA: render.alpha_for = lambda intensity: float(ALPHA)
    D = {}
    if os.path.exists('directions.jsonl'):
        for l in open('directions.jsonl'):
            x = json.loads(l)
            if 'error' not in x: D[x['questId']] = x
    plan = list(csv.DictReader(open('plan_v3.csv')))
    only = set(sys.argv[2:])
    for name, key, kind, src in WANT:
        if only and key not in only: continue
        ref = f'{REFS}/{key}.wav'
        if not os.path.exists(ref): print('!! no reference', key); continue
        rows = [r for r in plan if r['npc_name'] == name and r['npc_id'] != 'none']
        if not rows: print('!! not in plan', name); continue
        # their longest line the pack recorded (so the pack's own take sits beside ours), else their longest line
        r = max([x for x in rows if x['action'] == 'reuse'] or rows, key=lambda x: int(x['words'] or 0))
        q = r['questId']
        d = D.get(q, {}).get(r['kind'])
        if not d:
            direct.ACTOR_NOTES.update(actor_read.ensure({x['npc_id'] for x in plan if x['questId'] == q}))
            d = direct.direct(q).get(r['kind'])
        if not d: print('!! no direction', name, q); continue
        out = f"{ROOT}/{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')}"; os.makedirs(out, exist_ok=True)
        row = dict(r, clone_ref=f'game:{ref}', action='generate')
        nm = ov.name_of(r)
        render.render_line(row, dict(d, voice='npc'), f'{out}/{nm}_ours{"_" + TAG if TAG else ""}.mp3', emotion=EMOTION)
        subprocess.run(['cp', ref, f'{out}/reference_{key}.wav'])
        if r['action'] == 'reuse' and r['source_pack']:
            ext = r['file_in_pack'].rsplit('.', 1)[1]
            render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", f'{out}/{nm}_pack.{ext}')
        print(f'{name:24} {nm} ({r["words"]} words) <- {key}' + ('  + pack' if r['action'] == 'reuse' else ''), flush=True)

TAG = os.environ.get('TAG', '')
EMOTION = os.environ.get('EMOTION', 'text')          # 'clip': the style's calm reference performance instead
ALPHA = os.environ.get('ALPHA')                      # a fixed emotion strength over the intensity's

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'extract': extract, 'render': render_all}[sys.argv[1]]()
