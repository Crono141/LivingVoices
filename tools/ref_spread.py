"""How much a pack recording's pitch moves (2026-10-18). A clone copies its reference's range: the women cloned from a
level recording came out flat however strongly they were directed (Karja, Modera, Sutton), and the most expressive
recording of their own -- not the longest, as before -- won every blind test (Modera "a completely different voice",
to excellent; Sutton "no longer sounding like a robot"). The spread is the standard deviation of the voiced pitch in
semitones (pYIN); overnight.pack_refs picks a woman's reference by it.

  ../.venv/bin/python ../tools/ref_spread.py [female|all]     -> ref_spread.json (resumable)
"""
import concurrent.futures as cf, csv, json, os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT, MIN_WORDS = 'ref_spread.json', 25

def candidates(sex='female'):
    out = {}
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['action'] == 'reuse' and r['npc_id'] != 'none' and r['source_pack'] and r['file_in_pack'] \
                and int(r['words'] or 0) >= MIN_WORDS and (sex == 'all' or r['sex'] == sex):
            out[f"{r['source_pack']}:{r['file_in_pack']}"] = f"refs_cache/spread_{r['questId']}{r['kind']}{r['variant']}.ogg"
    return out

def one(job):
    warnings.filterwarnings('ignore')
    import numpy as np, librosa, render
    ref, local = job
    try:
        p = local if os.path.exists(local) else render.pack_clip(ref, local)
        y, sr = librosa.load(p, sr=16000, mono=True)
        f0, v, _ = librosa.pyin(y, fmin=70, fmax=600, sr=sr, frame_length=1024)
        st = 12 * np.log2(f0[v & ~np.isnan(f0)] / 100.0)
        return ref, round(float(np.std(st)), 2) if len(st) > 50 else None
    except Exception as e:
        print('!!', ref, str(e)[:120], flush=True); return ref, None

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    have = json.load(open(OUT)) if os.path.exists(OUT) else {}
    jobs = [(k, v) for k, v in candidates(sys.argv[1] if len(sys.argv) > 1 else 'female').items() if k not in have]
    print(len(jobs), 'recordings to measure', flush=True)
    with cf.ProcessPoolExecutor(16) as ex:
        for i, (ref, s) in enumerate(ex.map(one, jobs, chunksize=8), 1):
            have[ref] = s
            if i % 200 == 0: json.dump(have, open(OUT, 'w')); print(i, flush=True)
    json.dump(have, open(OUT, 'w'), indent=0); print('SPREAD DONE', len(have))
