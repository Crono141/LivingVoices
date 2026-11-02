"""Billy round 5: boy 11's reference de-reverbed before the -2/-1 shift (round 4 #4 had the room's echo).
A: VoiceFixer (speech restoration), B: MelBand-RoFormer denoise, C: aggressive variant. Card-1 ComfyUI."""
import csv, json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, child_voice
R = render.ROOT; OUT = f'{R}/voice_test/child/round5'; os.makedirs(OUT + '/parts', exist_ok=True)
raw0 = f'{R}/voice_test/child/round4/parts/11_M_native_raw.wav'
raw = f'{OUT}/parts/boy11_raw44k.wav'   # the round-4 reference was saved at 192 kHz (loudnorm upsamples)
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', raw0, '-ar', '44100', '-ac', '1', raw], check=True)
up = render.upload(raw)
def node_out(wf, idx_out):
    wf['9'] = {'class_type': 'SaveAudio', 'inputs': {'audio': [idx_out[0], idx_out[1]], 'filename_prefix': 'voice_test/child/round5/parts/clean'}}
    return render.comfy(wf)
cleaned = {}
ONLY = os.environ.get('ONLY')
if not ONLY: cleaned['voicefixer'] = node_out({'1': {'class_type': 'LoadAudio', 'inputs': {'audio': up}},
    '2': {'class_type': 'VoiceFixerNode', 'inputs': {'audio': ['1', 0], 'restoration_mode': '0 - Original (Default)', 'use_cuda': True}}}, ('2', 0))
for tag, m in (('melband', 'MELBAND/denoise_mel_band_roformer_sdr_27.99.ckpt'), ('melband_aggr', 'MELBAND/denoise_mel_band_roformer_aggressive_sdr_27.97.ckpt')):
    if ONLY and tag != ONLY: continue
    cleaned[tag] = node_out({'1': {'class_type': 'LoadAudio', 'inputs': {'audio': up}},
        '2': {'class_type': 'VocalRemovalNode', 'inputs': {'audio': ['1', 0], 'model': m, 'use_cache': False, 'aggressiveness': 10, 'format': 'wav'}}}, ('2', 0))
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
d = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}[row['questId']]['accept']
texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
import requests
requests.post(render.URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)   # separation model out before cloning
for i, (tag, src) in enumerate(cleaned.items(), 1):
    i = {'voicefixer': 1, 'melband': 2, 'melband_aggr': 3}[tag]
    ref = child_voice.childify(src, f'{OUT}/parts/ref_{tag}.wav', -2, -1)
    parts = [render.render_beat(render.speakable(render.scripted(t)), ref, render.style_clip(b['style'], 'male', 'human'), f'r5_{tag}_{k}')
             for k, (t, b) in enumerate(zip(texts, d['beats']))]
    render.join(render.even_pace(parts, texts), f'{OUT}/{i}_billy_{tag}.mp3')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', ref, '-b:a', '128k', f'{OUT}/{i}_reference_{tag}.mp3'], check=True)
    print(i, tag, 'done', flush=True)
shutil.copy(f'{R}/voice_test/child/round4/4_boy11_pitch-2_formant-1.mp3', f'{OUT}/0_round4_no4_as_was.mp3')
