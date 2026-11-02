"""Billy round 7: round 6 #3's voice (boy 10, MelBand, -1/-0.5) with the new everyday cheerful clip, two strengths."""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
R = render.ROOT; OUT = f'{R}/voice_test/child/round7'; os.makedirs(OUT, exist_ok=True)
ref = f'{R}/voice_test/child/round6/parts/ref_melband_p-1_f-0.5.wav'
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
D = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}
for kind in ('accept', 'complete'):
    row = next((r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == kind), None)
    if not row or kind not in D.get(row['questId'], {}): continue
    d = D[row['questId']][kind]; texts = render.beat_texts(row['questId'], kind, row['variant'], d['beats'])
    for alpha in (0.55, 0.4):
        render.ALPHA = alpha
        parts = [render.render_beat(render.speakable(render.scripted(t)), ref, render.style_clip(b['style'], 'male', 'human'), f'r7_{kind}_{alpha}_{k}')
                 for k, (t, b) in enumerate(zip(texts, d['beats']))]
        render.join(render.even_pace(parts, texts), f"{OUT}/{row['questId']}-{kind}_strength-{alpha}_{'+'.join(b['style'] for b in d['beats'])}.mp3")
        print(kind, alpha, flush=True)
