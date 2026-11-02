"""Billy round 6: boy 10's timbre (the producer's pick), cleaned, shifted slightly, our own direction on top.
Plymouth children's speech (Zenodo 200495, CC BY 4.0). Card-1 ComfyUI. Run from data/."""
import csv, glob, json, os, subprocess, sys, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import render, child_voice
R = render.ROOT; OUT = f'{R}/voice_test/child/round6'; os.makedirs(OUT + '/parts', exist_ok=True)
SRC = f'{LV.CORPORA}/plymouth_children/english_children/english_free_speech/files_cut_by_sentences/10_M_nonNative'
TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
dur = lambda f: float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], capture_output=True, text=True).stdout)
fs = sorted(glob.glob(f'{SRC}/*.wav'), key=lambda f: -dur(f)); pick, tot = [], 0.0
for f in fs:
    if tot >= 14: break
    pick.append(f); tot += dur(f)
n = len(pick); raw = f'{OUT}/parts/boy10_raw.wav'
flt = ''.join(f'[{i}:a]{TRIM},aresample=44100,aformat=channel_layouts=mono[a{i}];' for i in range(n))
flt += ''.join(f'anullsrc=r=44100:cl=mono,atrim=0:0.25[s{i}];' for i in range(n - 1))
flt += ''.join(f'[a{i}]' + (f'[s{i}]' if i < n - 1 else '') for i in range(n)) + f'concat=n={2 * n - 1}:v=0:a=1[o]'
subprocess.run(['ffmpeg', '-y', '-v', 'error', *sum((['-i', f] for f in pick), []), '-filter_complex', flt, '-map', '[o]', '-ar', '44100', raw], check=True)
up = render.upload(raw)
def run(wf, out):
    wf['9'] = {'class_type': 'SaveAudio', 'inputs': {'audio': list(out), 'filename_prefix': 'voice_test/child/round6/parts/clean'}}
    p = render.comfy(wf); dst = p.rsplit('.', 1)[0] + '_mono.wav'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', p, '-ac', '1', '-ar', '44100', dst], check=True); return dst
cleaned = {
  'voicefixer': run({'1': {'class_type': 'LoadAudio', 'inputs': {'audio': up}},
      '2': {'class_type': 'VoiceFixerNode', 'inputs': {'audio': ['1', 0], 'restoration_mode': '0 - Original (Default)', 'use_cuda': True}}}, ('2', 0)),
  # VocalRemovalNode: output 0 is what was REMOVED (round 5's "devil"), output 1 is the cleaned voice
  'melband': run({'1': {'class_type': 'LoadAudio', 'inputs': {'audio': up}},
      '2': {'class_type': 'VocalRemovalNode', 'inputs': {'audio': ['1', 0], 'model': 'MELBAND/denoise_mel_band_roformer_sdr_27.99.ckpt',
            'use_cache': False, 'aggressiveness': 10, 'format': 'wav'}}}, ('2', 1)),
}
requests.post(render.URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
d = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}[row['questId']]['accept']
texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', raw, '-b:a', '128k', f'{OUT}/0_boy10_source_uncleaned.mp3'], check=True)
i = 0
for tag, src in cleaned.items():
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-b:a', '128k', f'{OUT}/0_boy10_cleaned_{tag}.mp3'], check=True)
    for p, f in ((-1, -0.5), (-2, -1)):
        i += 1; ref = child_voice.childify(src, f'{OUT}/parts/ref_{tag}_p{p}_f{f}.wav', p, f)
        parts = [render.render_beat(render.speakable(render.scripted(t)), ref, render.style_clip(b['style'], 'male', 'human'), f'r6_{i}_{k}')
                 for k, (t, b) in enumerate(zip(texts, d['beats']))]
        render.join(render.even_pace(parts, texts), f'{OUT}/{i}_billy_{tag}_pitch{p}_formant{f}.mp3'); print(i, tag, p, f, flush=True)
open(f'{OUT}/CREDITS.txt', 'w').write('Voice reference derived from: children speech recording, Kennedy, Lemaignan, Montassier, Lavalade, '
    'Irfan, Papadopoulos, Senft, Belpaeme (Plymouth University), Zenodo record 200495, CC BY 4.0. Speaker 10.\n')
