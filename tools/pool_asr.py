"""Transcribe the style-clip candidates (style_pool/<performer>/*.wav) on the CPU -> style_pool/index.json
(performer -> [{file, dur, text}]). Resumable. Run from data/:  ../.venv/bin/python ../tools/pool_asr.py"""
import glob, json, os, sys, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_check import decode_audio, MODEL
from faster_whisper import WhisperModel
idx = json.load(open('style_pool/index.json')) if os.path.exists('style_pool/index.json') else {}
model = WhisperModel(MODEL, device=os.environ.get('ASR_DEVICE', 'cuda'), compute_type='float16' if os.environ.get('ASR_DEVICE', 'cuda') == 'cuda' else 'int8')
files = sorted(glob.glob('style_pool/*/*.wav')); done = {x['file'] for v in idx.values() for x in v}
for n, f in enumerate(files, 1):
    if f in done: continue
    try:
        with wave.open(f) as w: dur = w.getnframes() / w.getframerate()
    except Exception: dur = None
    if not dur or dur < 0.6: continue
    segs, _ = model.transcribe(decode_audio(open(f, 'rb').read()), language='en', without_timestamps=True, beam_size=1)
    idx.setdefault(f.split('/')[1], []).append({'file': f, 'dur': round(dur, 2), 'text': ' '.join(s.text.strip() for s in segs)})
    if n % 200 == 0:
        json.dump(idx, open('style_pool/index.json', 'w'), indent=0); print(n, '/', len(files), flush=True)
json.dump(idx, open('style_pool/index.json', 'w'), indent=0); print('done', sum(len(v) for v in idx.values()))
