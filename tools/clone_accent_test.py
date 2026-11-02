"""Does a pack clone keep the speaker's accent? (2026-10-12, the producer: "pack had a clearly british guy, ours was a
generic american dude"). One male pack speaker per accented race, its longest line: the pack original beside ours
with the emotion from the director's phrase (the overnight default) and from the style clip.
Run from data/ with the ComfyUI venv, card 1's ComfyUI up (tools/comfy2.sh start):
  ~/ComfyUI/venv/bin/python ../tools/clone_accent_test.py
-> <listen>/voice_test/clone_accent/<race>_<name>/{pack,ours_text,ours_clip}.*
"""
import csv, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import render, direct, overnight, actor_read
render.use_server(LV.RENDERERS["1"])
OUT = f'{LV.COMFY_OUT}/voice_test/clone_accent'
RACES = sys.argv[1:] or ['Dwarf', 'Blood Elf', 'Undead', 'Draenei', 'Troll', 'Gnome']

rows = [r for r in csv.DictReader(open('plan_v3.csv')) if r['action'] == 'reuse' and r['sex'] == 'male']
refs = overnight.pack_refs()
for race in RACES:
    # the speaker with the most pack material (its clone reference is its longest line); test on that same line
    cand = [r for r in rows if r['race'] == race and refs.get(r['npc_id']) == f"{r['source_pack']}:{r['file_in_pack']}"]
    if not cand: print('no speaker for', race); continue
    r = max(cand, key=lambda x: int(x['words'] or 0))
    who = re.sub(r'[^A-Za-z0-9]+', '_', f"{race}_{r['npc_name']}").strip('_')
    os.makedirs(f'{OUT}/{who}', exist_ok=True)
    ext = r['file_in_pack'].rsplit('.', 1)[1]
    render.pack_clip(refs[r['npc_id']], f'{OUT}/{who}/pack.{ext}')
    direct.ACTOR_NOTES.update(actor_read.ensure({x['npc_id'] for x in csv.DictReader(open('plan_v3.csv')) if x['questId'] == r['questId']}))
    D = direct.direct(r['questId'])
    d = D.get(r['kind'])
    if not d: print('no direction', who, r['questId'], r['kind']); continue
    g = overnight.as_generated(r)
    for emo in ('text', 'clip'):
        dst = f'{OUT}/{who}/ours_{emo}.mp3'
        if not os.path.exists(dst): render.render_line(g, d, dst, emotion=emo)
    print(who, r['questId'], r['kind'], r['words'], 'words', flush=True)
