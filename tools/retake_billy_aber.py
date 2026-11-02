"""Retakes 2026-10-12: Billy without the dulling reference de-ess (de-ess the OUTPUT instead, or a lighter one on the
ref); Abercrombie 133 accept with calm() on the intensity-4 beat."""
import csv, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, child_voice, requests
R = render.ROOT; OUT = f'{R}/voice_test/newstyles/retake'; os.makedirs(OUT + '/parts', exist_ok=True)
B = f'{R}/voice_test/child/round9/parts/boy10_25s_mossformer_voicefixer.wav'
light = f'{OUT}/parts/boy10_B_light.wav'
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', B, '-af', 'deesser=i=0.3:m=0.5:f=0.5:s=o', light], check=True)
refs = {'plainref': child_voice.childify(B, f'{OUT}/parts/billy_plain.wav', -1, -0.5),
        'lightref': child_voice.childify(light, f'{OUT}/parts/billy_light.wav', -1, -0.5)}
requests.post(render.URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)
D = json.load(open('newstyle_test_directions.json'))
rows = {(r['questId'], r['kind']): r for r in csv.DictReader(open('plan_v3.csv')) if r['variant'] != 'f'}
def line(q, kind, spk, name):
    r = rows[(q, kind)]; d = D[q][kind]
    texts = [render.scripted(t) for t in render.beat_texts(q, kind, r['variant'], d['beats'])]
    sex = r['sex'] if r['sex'] in ('male', 'female') else 'male'
    parts = [render.render_beat(render.calm(render.speakable(t), b['intensity']), spk, render.style_clip(b['style'], sex, r['race']),
                                f"rt_{name}_{i}", alpha=render.alpha_for(b['intensity'])) for i, (t, b) in enumerate(zip(texts, d['beats']))]
    out = f'{OUT}/{name}.mp3'; render.join(render.even_pace(parts, texts), out); print(name, flush=True); return out
for k, spk in refs.items(): line('86', 'accept', spk, f'Billy_{k}')
# the plain-reference take again, de-essed on the OUTPUT (only where the S's are)
src = f'{OUT}/Billy_plainref.mp3'
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-af', 'deesser=i=0.5:m=0.5:f=0.5:s=o', '-b:a', '128k', f'{OUT}/Billy_plainref_outdeess.mp3'], check=True)
r = rows[('133', 'accept')]
line('133', 'accept', render.speaker_ref(dict(r, clone_ref=f"{r['source_pack']}:{r['file_in_pack']}") if r['action'] == 'reuse' else r), 'Abercrombie_133-accept_calm')
