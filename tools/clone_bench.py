"""Card-1 benchmark: IndexTTS-2 cloning beside the pinned Gemma. Measures speed (seconds of audio per second),
peak VRAM on card 1, and Gemma's tokens/s before and during generation.

Needs the scratch ComfyUI on 42422 (CUDA_VISIBLE_DEVICES=1). Run from data/:
  ~/ComfyUI/venv/bin/python ../tools/clone_bench.py
"""
import json, urllib.error, re, subprocess, sys, threading, time, urllib.request, zipfile, os, wave
import lvconfig as LV
URL = LV.RENDERERS["1"]; GEMMA = f'{LV.JUDGE_URL}/v1/chat/completions'
OUT = f'{LV.COMFY_OUT}/voice_test/clone_bench'
REFS = f'{LV.COMFY_OUT}/voice_test/clone_bench/refs'
os.makedirs(REFS, exist_ok=True)

def clean(t):
    t = re.sub(r'\$[bB]', '\n', t); t = re.sub(r'\$[nNcC]', 'adventurer', t); t = re.sub(r'\$[rR]', 'traveler', t)
    t = re.sub(r'\$[gG]([^:;]*):([^;]*);', r'\1', t); t = re.sub(r'<[^>]*>', '', t)
    return re.sub(r'\n\s*\n+', '\n', t).strip()

def post(path, body, url=URL, timeout=60):
    r = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    try: return json.load(urllib.request.urlopen(r, timeout=timeout))
    except urllib.error.HTTPError as e: sys.exit(f'{path}: {e.code} {e.read()[:1500]}')

def upload(path):
    """POST /upload/image takes any file; returns the name LoadAudio sees (works for the container on card 0 too)"""
    import requests
    r = requests.post(URL + '/upload/image', files={'image': (os.path.basename(path), open(path, 'rb'))},
                      data={'type': 'input', 'subfolder': 'wowvo', 'overwrite': 'true'}, timeout=60)
    r.raise_for_status(); j = r.json()
    return f"{j['subfolder']}/{j['name']}" if j.get('subfolder') else j['name']

def vram():
    out = subprocess.run(['nvidia-smi', '--query-gpu=index,memory.used', '--format=csv,noheader,nounits'],
                         capture_output=True, text=True).stdout
    return {int(a): int(b) for a, b in (l.split(',') for l in out.strip().splitlines())}

def gemma_tps():
    t0 = time.time()
    r = post('', {'model': LV.LLM_MODEL, 'max_tokens': 150, 'temperature': 0.7,
                  'messages': [{'role': 'user', 'content': 'Describe a quiet harbour town at dawn in about 120 words.'}]},
             url=GEMMA, timeout=120)
    n = r['usage']['completion_tokens']; return n / (time.time() - t0), n

q = json.load(open('ac_quests.json'))
gv = json.load(open('game_voices/index.json'))
thrall = max((x for x in gv['Thrall']['clips'] if x['text'] and x['dur'] and 8 <= x['dur'] <= 15), key=lambda x: x['dur'])
z = zipfile.ZipFile('packs/speakstone_wotlk.zip')
ss_file = next(n for n in z.namelist() if n.endswith('/12036_description.ogg')) if any(n.endswith('/12036_description.ogg') for n in z.namelist()) \
    else next(n for n in z.namelist() if n.endswith('_description.ogg'))
ss_ref = os.path.join(REFS, 'speakstone_' + os.path.basename(ss_file)); open(ss_ref, 'wb').write(z.read(ss_file))
th_ref = os.path.join(REFS, 'thrall_' + os.path.basename(thrall['wav'])); subprocess.run(['cp', thrall['wav'], th_ref])

BEAMS = int(os.environ.get('BEAMS', 3)); COMPILE = os.environ.get('COMPILE') == '1'; TAG = f'b{BEAMS}' + ('c' if COMPILE else '')
jobs = [('thrall_warmup', th_ref, clean(q['4974']['off'])),
        ('thrall_long', th_ref, clean(q['4974']['desc'] if '4974' in q else q['10985']['desc'])),
        ('speakstone_short', ss_ref, clean(q['12036']['req'] or q['12036']['off'])),
        ('speakstone_long', ss_ref, clean(q['12036']['desc']))]

base = vram(); print('vram before', base)
print(TAG, 'gemma baseline tok/s', [round(gemma_tps()[0], 1) for _ in range(2)])

peak = {'v': 0}; stop = threading.Event()
def sampler():
    while not stop.is_set(): peak['v'] = max(peak['v'], vram()[1]); time.sleep(0.5)
threading.Thread(target=sampler, daemon=True).start()
during = []
def gemma_loop():
    while not stop.is_set():
        try: during.append(gemma_tps()[0])
        except Exception as e: during.append(f'err {e}')
gl = threading.Thread(target=gemma_loop, daemon=True)

total_audio = total_wall = 0
for i, (name, ref, text) in enumerate(jobs):
    wf = {'1': {'class_type': 'IndexTTSEngineNode', 'inputs': {
              'model_path': 'IndexTTS-2', 'device': 'cuda', 'emotion_alpha': 1.0, 'use_random': False,
              'max_text_tokens_per_segment': 120, 'interval_silence': 200, 'temperature': 0.8, 'top_p': 0.8, 'top_k': 30,
              'do_sample': True, 'length_penalty': 0.0, 'num_beams': BEAMS, 'repetition_penalty': 10.0, 'max_mel_tokens': 1500,
              'use_fp16': True, 'use_deepspeed': False, 'use_torch_compile': COMPILE}},
          '2': {'class_type': 'LoadAudio', 'inputs': {'audio': upload(ref)}},
          '3': {'class_type': 'UnifiedTTSTextNode', 'inputs': {'TTS_engine': ['1', 0], 'text': text, 'narrator_voice': 'none',
              'seed': 1, 'opt_narrator': ['2', 0], 'enable_chunking': True, 'max_chars_per_chunk': 400, 'enable_audio_cache': False}},
          '4': {'class_type': 'SaveAudio', 'inputs': {'audio': ['3', 0], 'filename_prefix': f'voice_test/clone_bench/{TAG}_{name}'}}}
    if i == 1: gl.start()       # first job warms the model up without Gemma load
    t0 = time.time(); pid = post('/prompt', {'prompt': wf})['prompt_id']
    while True:
        h = json.load(urllib.request.urlopen(f'{URL}/history/{pid}', timeout=30))
        if pid in h: break
        time.sleep(1)
    wall = time.time() - t0; st = h[pid]['status']
    files = [f for o in h[pid]['outputs'].values() for f in o.get('audio', [])]
    dur = 0
    for f in files:
        p = f"{LV.COMFY_OUT}/{f['subfolder']}/{f['filename']}"
        dur += float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p],
                                    capture_output=True, text=True).stdout or 0)
    print(f"{name}: {st.get('status_str')} words {len(text.split())} audio {dur:.1f}s wall {wall:.1f}s -> {dur / wall if wall else 0:.2f}x realtime")
    if st.get('status_str') != 'success': print('  ', json.dumps(st.get('messages'))[-800:])
    if i > 0: total_audio += dur; total_wall += wall
stop.set(); time.sleep(1)
print('warm speed', round(total_audio / total_wall, 2), 'x realtime | peak vram card1', peak['v'], 'MiB of 24576 (gemma+asr before:', base[1], ')')
print('gemma tok/s during', [round(x, 1) if isinstance(x, float) else x for x in during])
