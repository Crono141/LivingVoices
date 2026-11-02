"""Render direction_test.json three ways on the card-1 scratch ComfyUI (42422): flat (no emotion), vec (the emotion
mix), style (the style's game clip as emotion reference). Beats are rendered one by one and joined with a short pause.
Run from data/:  ~/ComfyUI/venv/bin/python ../tools/render_test.py
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
URL = LV.RENDERERS["1"]; ROOT = f'{LV.COMFY_OUT}'
OUT = f'{ROOT}/voice_test/directed'; os.makedirs(OUT, exist_ok=True)
from direct import STYLES, style_clip
ALPHA = float(os.environ.get('ALPHA', 0.65)); MODES = os.environ.get('MODES', 'flat,vec,style').split(','); SUFFIX = os.environ.get('SUFFIX', '')
DFILE = os.environ.get('DFILE', 'direction_test.json')
D = json.load(open(DFILE))
SPEAKER = {'4974': f'{ROOT}/voice_test/clone_bench/refs/thrall_WG_Thrall_HOR31.wav',
           '12036': f'{ROOT}/voice_test/clone_bench/refs/speakstone_12036_description.ogg'}

def upload(path):
    r = requests.post(URL + '/upload/image', files={'image': (os.path.basename(path), open(path, 'rb'))},
                      data={'type': 'input', 'subfolder': 'wowvo', 'overwrite': 'true'}, timeout=60)
    r.raise_for_status(); j = r.json(); return f"{j['subfolder']}/{j['name']}"

def run(wf):
    r = urllib.request.Request(URL + '/prompt', data=json.dumps({'prompt': wf}).encode(), headers={'Content-Type': 'application/json'})
    try: pid = json.load(urllib.request.urlopen(r, timeout=60))['prompt_id']
    except urllib.error.HTTPError as e: sys.exit(e.read()[:1500])
    while True:
        h = json.load(urllib.request.urlopen(f'{URL}/history/{pid}', timeout=30))
        if pid in h: break
        time.sleep(1)
    st = h[pid]['status']
    if st.get('status_str') != 'success': sys.exit(json.dumps(st.get('messages'))[-1500:])
    f = [a for o in h[pid]['outputs'].values() for a in o.get('audio', [])][0]
    return f"{ROOT}/{f['subfolder']}/{f['filename']}"

def beat(text, speaker, mode, b, tag):
    wf = {'1': {'class_type': 'IndexTTSEngineNode', 'inputs': {
              'model_path': 'IndexTTS-2', 'device': 'cuda', 'emotion_alpha': 1.0, 'use_random': False,
              'max_text_tokens_per_segment': 120, 'interval_silence': 200, 'temperature': 0.8, 'top_p': 0.8, 'top_k': 30,
              'do_sample': True, 'length_penalty': 0.0, 'num_beams': 1, 'repetition_penalty': 10.0, 'max_mel_tokens': 1500,
              'use_fp16': True, 'use_deepspeed': False}},
          '2': {'class_type': 'LoadAudio', 'inputs': {'audio': upload(speaker)}},
          '3': {'class_type': 'UnifiedTTSTextNode', 'inputs': {'TTS_engine': ['1', 0], 'text': text, 'narrator_voice': 'none',
              'seed': 1, 'opt_narrator': ['2', 0], 'enable_chunking': True, 'max_chars_per_chunk': 400, 'enable_audio_cache': False}},
          '4': {'class_type': 'SaveAudio', 'inputs': {'audio': ['3', 0], 'filename_prefix': f'voice_test/directed/parts/{tag}'}}}
    if mode == 'vec':
        wf['5'] = {'class_type': 'IndexTTSEmotionOptionsNode', 'inputs': {k.capitalize(): v for k, v in b['emotion'].items()}}
        wf['1']['inputs']['emotion_control'] = ['5', 0]
    elif mode == 'style':
        wf['5'] = {'class_type': 'LoadAudio', 'inputs': {'audio': upload(style_clip(b['style'], 'male'))}}
        wf['1']['inputs']['emotion_control'] = ['5', 0]
        wf['1']['inputs']['emotion_alpha'] = ALPHA
    return run(wf)

def speech_rate(path, words):
    """words per second of speech, leading/trailing silence trimmed"""
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-af',
                          'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse',
                          '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout
    return words / max(len(out) / 4 / 8000, 0.1)

def even_pace(parts, texts):
    """time-stretch beats toward the line's mean speaking rate (pitch kept), at most +-15%"""
    if len(parts) < 2: return parts, []
    w = [len(t.split()) for t in texts]; r = [speech_rate(p, n) for p, n in zip(parts, w)]
    target = sum(w) / sum(n / x for n, x in zip(w, r)); out = []; info = []
    for p, x in zip(parts, r):
        f = max(0.87, min(1.15, target / x)); info.append(f'{x:.2f}w/s x{f:.2f}')
        if abs(f - 1) < 0.03: out.append(p); continue
        q = p.rsplit('.', 1)[0] + '_paced.flac'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', p, '-af', f'atempo={f:.3f}', q], check=True); out.append(q)
    return out, info

def join(parts, dst):
    n = len(parts); inp = sum((['-i', p] for p in parts), [])
    flt = ''.join(f'[{i}:a]aresample=24000,aformat=channel_layouts=mono[a{i}];' for i in range(n))
    flt += ''.join(f'[a{i}]' + (f'[s{i}]' if i < n - 1 else '') for i in range(n))
    sil = ''.join(f'anullsrc=r=24000:cl=mono,atrim=0:0.35[s{i}];' for i in range(n - 1))
    flt = sil + flt + f'concat=n={2 * n - 1}:v=0:a=1[o]'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *inp, '-filter_complex', flt, '-map', '[o]', '-b:a', '160k', dst], check=True)

lines = []
for q, kinds in D.items():
    for kind, d in kinds.items():
        lines.append(f"\n{q} {kind}: {d['note']}")
        for b in d['beats']:
            lines.append(f"   [{b['style']}] {', '.join(f'{k} {v}' for k, v in b['emotion'].items() if v)} | {b['text']}")
        for mode in MODES:
            t0 = time.time()
            if mode == 'flat': parts = [beat(' '.join(b['text'] for b in d['beats']), SPEAKER[q], mode, None, f'{q}_{kind}_flat')]
            else:
                parts = [beat(b['text'], SPEAKER[q], mode, b, f'{q}_{kind}_{mode}{SUFFIX}_{i}') for i, b in enumerate(d['beats'])]
                parts, info = even_pace(parts, [b['text'] for b in d['beats']])
                if info: lines.append(f'   {mode}{SUFFIX} pace: ' + ', '.join(info))
            join(parts, f'{OUT}/{q}_{kind}_{mode}{SUFFIX}.mp3'); print(q, kind, mode + SUFFIX, f'{time.time() - t0:.0f}s', flush=True)
open(f'{OUT}/LISTEN{SUFFIX}.txt', 'w').write('Directed delivery test: <quest>_<line>_{flat|vec|style}.mp3\n'
    '  flat  = no emotion (what the overnight run would do today)\n'
    '  vec   = Gemma\'s emotion mix per beat\n'
    '  style = Gemma\'s chosen style per beat, performed from a real game clip as the emotion reference\n'
    'Speakers: 4974 Thrall (his own game voice), 12036 Senior Sergeant Juktok (SpeakStone orc voice).\n' + '\n'.join(lines) + '\n')
print('done ->', OUT)
