"""Speech-recognition check: does each reused SpeakStone clip say our quest text, and what do the game-voice
reference clips actually say?

Run from data/ on card 1 (card 0 is the image/video card):
  CUDA_VISIBLE_DEVICES=1 LD_LIBRARY_PATH=<venv nvidia libs> ../.venv/bin/python ../tools/asr_check.py [speakstone|game|all]
Resumable: results append to asr/<set>.jsonl, already-done keys are skipped.
- speakstone: every plan_v3.csv row reused from speakstone_*; score = word-sequence similarity between the
  transcript and our text, with name/class/race placeholders and SpeakStone's stand-ins (champion, hero...) removed.
  pass >= 0.90, review 0.75-0.90, fail < 0.75.
- game: every clip in game_voices/index.json; compared with its database transcript when there is one.
"""
import csv, difflib, io, json, os, re, subprocess, sys, time, zipfile
import lvconfig as LV
import numpy as np
from faster_whisper import WhisperModel, BatchedInferencePipeline

def decode_audio(data):
    # ffmpeg, not faster_whisper.decode_audio: its PyAV call breaks on the installed av (metadata_errors)
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '16000', 'pipe:1'],
                         input=data, capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768

MODEL = f'{LV.MODELS}/ASR/faster-whisper-large-v3-turbo'
KINDS = {'accept': 'desc', 'progress': 'req', 'complete': 'off'}
GPAT = re.compile(r'\$[Gg]\s*([^:;]+?)\s*:\s*([^:;]+?)\s*;')
STAND_INS = {'champion', 'hero', 'adventurer', 'traveler', 'traveller', 'friend', 'stranger'}

def words(t, ours=False):
    t = t.lower()
    if ours:
        t = GPAT.sub(r'\1', t)
        t = re.sub(r'\$[nncrr]', ' ', t, flags=re.I)
        t = re.sub(r'\$b', ' ', t)
        t = re.sub(r'<[^>]*>', ' ', t)          # stage directions are not spoken
    t = re.sub(r"[^a-z0-9' ]+", ' ', t.replace('-', ' '))
    w = [x.strip("'") for x in t.split()]
    return [x for x in w if x and x not in STAND_INS]

def score(asr, ref):
    a, b = words(asr), words(ref, ours=True)
    if not b: return None
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)

def done_keys(path):
    if not os.path.exists(path): return set()
    return {json.loads(l)['key'] for l in open(path)}

def run(items, path, model):
    """items: [(key, loader -> bytes, reference text or None, extra dict)]"""
    done = done_keys(path); todo = [i for i in items if i[0] not in done]
    print(f'{path}: {len(items)} items, {len(todo)} to do', flush=True)
    t0 = time.time(); audio_s = 0
    with open(path, 'a') as f:
        for n, (key, load, ref, extra) in enumerate(todo, 1):
            try:
                a = decode_audio(load())
                segs, info = model.transcribe(a, language='en', batch_size=16, without_timestamps=True)
                text = ' '.join(s.text.strip() for s in segs).strip()
                audio_s += info.duration
                rec = dict(key=key, asr=text, dur=round(info.duration, 2), score=score(text, ref) if ref else None, **extra)
            except Exception as e:
                rec = dict(key=key, error=str(e)[:200], **extra)
            f.write(json.dumps(rec) + '\n')
            if n % 200 == 0:
                el = time.time() - t0
                print(f'  {n}/{len(todo)}  {audio_s / el:.0f}x realtime  eta {el / n * (len(todo) - n) / 60:.0f} min', flush=True); f.flush()

def speakstone_items():
    ours = json.load(open('ac_quests.json')); zips = {}
    def z(pack):
        if pack not in zips: zips[pack] = zipfile.ZipFile(f'packs/{pack}.zip')
        return zips[pack]
    items = []
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['action'] != 'reuse' or not r['source_pack'].startswith('speakstone'): continue
        t = ours[r['questId']][KINDS[r['kind']]]
        key = f"{r['questId']}-{r['kind']}-{r['variant']}"
        items.append((key, (lambda p=r['source_pack'], fn=r['file_in_pack']: z(p).read(fn)), t,
                      dict(pack=r['source_pack'], file=r['file_in_pack'], npc=r['npc_id'], words=int(r['words']))))
    return items

def game_items():
    idx = json.load(open('game_voices/index.json')); items = []
    for name, c in idx.items():
        for x in c['clips']:
            items.append((x['wav'], (lambda p=x['wav']: open(p, 'rb').read()), x.get('text'),
                          dict(character=name, db_text=x.get('text'), kind=x['kind'])))
    return items

if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    os.makedirs('asr', exist_ok=True)
    model = BatchedInferencePipeline(WhisperModel(MODEL, device='cuda', compute_type='float16'))
    if which in ('game', 'all'): run(game_items(), 'asr/game_voices.jsonl', model)
    if which in ('speakstone', 'all'): run(speakstone_items(), 'asr/speakstone.jsonl', model)
