"""Ours against the pack (2026-10-29, the producer): the release ships no community pack audio (overnight.KEEP_PACK), so
the voices whose pack recordings we had kept -- orc and troll women above all, "the most difficult to get right" -- now
render in ours. This samples their lines already rendered (one per speaker, up to PER_GROUP a voice), each beside the
pack's own take of the same line, for the review page's Compare tab; its verdict per voice goes to
data/compare/pick.json.

Run from data/:  ~/ComfyUI/venv/bin/python ../tools/voice_compare.py
"""
import csv, json, os, random, shutil, sqlite3, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overnight as o, render
from review_server import meant_text

OUT = 'compare'
GROUPS = [('Orc', 'female'), ('Troll', 'female'), ('Dwarf', 'female'), ('Forest Troll', 'male')]
PER_GROUP = 12

if __name__ == '__main__':
    st = dict(sqlite3.connect('overnight.sqlite').execute('SELECT name, status FROM lines'))
    by = {g: {} for g in GROUPS}
    for r in csv.DictReader(open('plan_v3.csv')):
        g = (r['race'], r['sex']); nm = o.name_of(r)
        if g in by and r['action'] == 'reuse' and st.get(nm) in ('rendered', 'done') and os.path.exists(f'render/{nm}.mp3') \
                and 12 <= int(r['words'] or 0) <= 90:
            by[g].setdefault(r['npc_id'], []).append(r)
    pick = json.load(open(f'{OUT}/pick.json')) if os.path.exists(f'{OUT}/pick.json') else {}
    if os.path.isdir(OUT): shutil.rmtree(OUT)
    os.makedirs(OUT); rnd = random.Random(29); index = []
    for g in GROUPS:
        speakers = list(by[g]); rnd.shuffle(speakers)
        for npc in speakers[:PER_GROUP]:
            r = rnd.choice(by[g][npc]); nm = o.name_of(r)
            shutil.copy(f'render/{nm}.mp3', f'{OUT}/{nm}.ours.mp3')
            raw = render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", f"{OUT}/{nm}.pack.{r['file_in_pack'].rsplit('.', 1)[1]}")
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', raw, '-ac', '1', '-ar', '24000', '-b:a', '128k', f'{OUT}/{nm}.pack.mp3'], check=True)
            os.remove(raw)
            g_row = o.as_generated(r) or {}
            index.append(dict(name=nm, group=f'{g[0]} {g[1]}', who=r['npc_name'], text=meant_text(nm), pack=r['source_pack'],
                              voice=g_row.get('clone_ref', ''), status=st.get(nm)))
    json.dump(dict(groups=[f'{a} {b}' for a, b in GROUPS], lines=index), open(f'{OUT}/index.json', 'w'), indent=1)
    if pick: json.dump(pick, open(f'{OUT}/pick.json', 'w'), indent=1)
    for g in GROUPS: print(f'{g[0]} {g[1]}: {sum(1 for x in index if x["group"] == " ".join(g))} lines ({len(by[g])} speakers rendered)')
