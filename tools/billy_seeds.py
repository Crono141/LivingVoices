"""Billy: is round 7's rustle the luck of the draw? Same voice (round 6 #3: boy 10, MelBand, -1/-0.5), same joined
cheerful NPC clip, four seeds."""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
R = render.ROOT; OUT = f'{R}/voice_test/child/seeds'; os.makedirs(OUT, exist_ok=True)
ref = f'{R}/voice_test/child/round6/parts/ref_melband_p-1_f-0.5.wav'
emo = f'{R}/voice_test/cheerful_check/0_joined_cheerful_clip.wav'
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
d = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}[row['questId']]['accept']
texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
for seed in (2, 3, 4, 5):
    parts = [render.render_beat(render.speakable(render.scripted(t)), ref, emo, f'seed{seed}_{k}', seed=seed) for k, t in enumerate(texts)]
    render.join(render.even_pace(parts, texts), f'{OUT}/billy_cheerful_npc_clip_seed{seed}.mp3'); print('seed', seed, flush=True)
