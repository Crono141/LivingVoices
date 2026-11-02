"""Speech-recognition check of rendered lines against what the voice was MEANT to say: the quest text with the
spoken-text rules applied (scripts.json punctuation, the dropped player address) but not the pronunciation
respellings (Whisper writes "Goldshire", not "Gold shire").

Run from data/ on card 1:
  CUDA_VISIBLE_DEVICES=1 LD_LIBRARY_PATH=<venv nvidia libs> ../.venv/bin/python ../tools/check_renders.py render render_compare
Prints the lowest-scoring lines; writes render_check.json.
"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_check import decode_audio, MODEL
from asr_report import rescore
import direct, render
from faster_whisper import WhisperModel, BatchedInferencePipeline

def meant(qid, kind, v):
    t = render.variant_clean(direct.Q[qid][direct.KINDS[kind]] or '', v)
    return render.spoken_text(render.scripted(t))

model = BatchedInferencePipeline(WhisperModel(MODEL, device='cuda', compute_type='float16'))
res = []
for d in sys.argv[1:]:
    for f in sorted(glob.glob(f'{d}/*.mp3')):
        n = os.path.basename(f)[:-4].split('-')
        if len(n) < 2 or n[-1].startswith('v'): continue
        q, kind, v = n[0], n[1], (n[2] if len(n) > 2 else '')
        segs, info = model.transcribe(decode_audio(open(f, 'rb').read()), language='en', batch_size=16, without_timestamps=True)
        t = ' '.join(s.text.strip() for s in segs)
        res.append((rescore(t, meant(q, kind, v)), f, round(info.duration, 1), t))
json.dump(res, open('render_check.json', 'w'), indent=1)
res.sort()
print('lines', len(res), '| >=0.95', sum(r[0] >= 0.95 for r in res), '| 0.90-0.95', sum(0.9 <= r[0] < 0.95 for r in res),
      '| <0.90', sum(r[0] < 0.9 for r in res))
for s, f, d, t in res[:10]: print(f'{s:.3f} {f} {d}s | {t[:150]}')
