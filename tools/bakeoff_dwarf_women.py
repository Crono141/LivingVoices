"""Dwarf women (2026-10-13): Donova Snowden's pack voice (SpeakStone Forever 1) as the reference for every dwarf
woman, shifted per NPC (one pass). Three women at -1, 0, +0.5 st beside their own pack takes. Run from data/."""
import sys, csv, json, os, re, subprocess
sys.path.insert(0, '../tools')
import lvconfig as LV
import render, overnight as ov, direct, actor_read, voice_sources_test as vst
render.use_server(LV.RENDERERS["0"])
OUT = f'{LV.COMFY_OUT}/voice_test/bakeoff/round3/dwarf_women'; os.makedirs(OUT, exist_ok=True)
plan = list(csv.DictReader(open('plan_v3.csv')))
src = sorted([r for r in plan if r['npc_name'] == 'Donova Snowden' and r['source_pack'] == 'speakstone_forever1'],
             key=lambda r: -int(r['words']))[:4]
clips = []
for r in src:
    p = f"refs_cache/donova_{r['questId']}_{r['kind']}.ogg"; render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", p); clips.append(p)
base = 'clone_refs/dwarf_female_donova.flac'; tot, n = vst.assemble(clips, base, want=14.0); print('reference', round(tot, 1), 's from', n)
subprocess.run(['cp', base, f'{OUT}/reference_donova.wav'])
D = {}
for l in open('directions.jsonl'):
    x = json.loads(l)
    if 'error' not in x: D[x['questId']] = x
for name, st in [('Quartermaster Miranda Breechlock', -1.0), ('Geologist Larksbane', 0.0), ('Lana Stouthammer', 0.5)]:
    ref = base if not st else base[:-4] + f'_{st:+.1f}.wav'
    if st and not os.path.exists(ref): subprocess.run(['rubberband-r3', '-q', '-p', str(st), base, ref], check=True)
    rows = [r for r in plan if r['npc_name'] == name]
    r = max([x for x in rows if x['action'] == 'reuse'] or rows, key=lambda x: int(x['words'] or 0))
    d = D.get(r['questId'], {}).get(r['kind'])
    if not d:
        direct.ACTOR_NOTES.update(actor_read.ensure({x['npc_id'] for x in plan if x['questId'] == r['questId']}))
        d = direct.direct(r['questId']).get(r['kind'])
    tag = re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')
    render.render_line(dict(r, action='generate', clone_ref=f'game:{ref}'), d, f'{OUT}/{tag}_{ov.name_of(r)}_donova{st:+.1f}st.mp3')
    if r['action'] == 'reuse' and r['source_pack']:
        render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", f"{OUT}/{tag}_{ov.name_of(r)}_pack.{r['file_in_pack'].rsplit('.', 1)[1]}")
    print(name, st, flush=True)
