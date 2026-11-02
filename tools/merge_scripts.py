"""Merge the review batches (data/script_review/fixes_*.json) into data/scripts.json through the guard
(direct.read_as_ok: same words, no new colons/ellipses, no added pauses). Keeps existing entries (by-ear fixes win).
Run from data/:  ../.venv/bin/python ../tools/merge_scripts.py"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from direct import read_as_ok
have = json.load(open('scripts.json')) if os.path.exists('scripts.json') else {
    '_note': 'original sentence -> the same words punctuated for reading. Reviewed by Claude (2026-10-11) and added to by ear; render.py applies each through direct.read_as_ok.'}
ok = rej = 0
for f in sorted(glob.glob('script_review/fixes_*.json')):
    for x in json.load(open(f)):
        s, fx = x['sentence'], x['fixed']
        if s in have: continue
        if read_as_ok(s, fx): have[s] = fx; ok += 1
        else: rej += 1; print('rejected:', repr(s), '->', repr(fx))
json.dump(have, open('scripts.json', 'w'), indent=1, ensure_ascii=False)
print('added', ok, 'rejected', rej, 'total', len(have) - 1)
