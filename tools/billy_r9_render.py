"""Billy round 9, step 2 (ComfyUI venv, card-1 ComfyUI): A = MossFormer2-cleaned reference, B = A + VoiceFixer
(denoise first, then de-reverb). Each shifted -1/-0.5 like round 6 #3 and cloned with #3's direction."""
import csv, json, os, shutil, subprocess, sys, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, child_voice
R = render.ROOT; OUT = f'{R}/voice_test/child/round9'; P = OUT + '/parts'
moss = f'{P}/boy10_25s_mossformer.wav'
wf = {'1': {'class_type': 'LoadAudio', 'inputs': {'audio': render.upload(moss)}},
      '2': {'class_type': 'VoiceFixerNode', 'inputs': {'audio': ['1', 0], 'restoration_mode': '0 - Original (Default)', 'use_cuda': True}},
      '9': {'class_type': 'SaveAudio', 'inputs': {'audio': ['2', 0], 'filename_prefix': 'voice_test/child/round9/parts/vf'}}}
vf = render.comfy(wf); vfm = f'{P}/boy10_25s_mossformer_voicefixer.wav'
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', vf, '-ac', '1', '-ar', '44100', vfm], check=True)
requests.post(render.URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
d = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}[row['questId']]['accept']
texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
for tag, src in (('A_mossformer', moss), ('B_mossformer_voicefixer', vfm)):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-b:a', '128k', f'{OUT}/{tag}_reference_cleaned.mp3'], check=True)
    ref = child_voice.childify(src, f'{P}/ref_{tag}.wav', -1, -0.5)
    parts = [render.render_beat(render.speakable(render.scripted(t)), ref, render.style_clip(b['style'], 'male', 'human'), f'r9_{tag}_{k}')
             for k, (t, b) in enumerate(zip(texts, d['beats']))]
    render.join(render.even_pace(parts, texts), f'{OUT}/{tag}_billy.mp3'); print(tag, flush=True)
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', f'{P}/boy10_25s_raw.wav', '-b:a', '128k', f'{OUT}/0_reference_raw_25s.mp3'], check=True)
shutil.copy(f'{R}/voice_test/child/round6/3_billy_melband_pitch-1_formant-0.5.mp3', f'{OUT}/0_round6_no3_for_comparison.mp3')
