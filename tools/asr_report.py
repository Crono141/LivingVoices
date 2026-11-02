"""Summarise asr/*.jsonl. Run from data/:  ../.venv/bin/python ../tools/asr_report.py
Writes asr/speakstone_verdicts.csv (key, verdict, score, pack, file, asr) for plan_v4 to consume."""
import csv, difflib, json, collections, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_check import words
PASS, REVIEW = 0.90, 0.80
KINDS = {'accept': 'desc', 'progress': 'req', 'complete': 'off'}
ONES = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
TENS = 'x x twenty thirty forty fifty sixty seventy eighty ninety'.split()
def spell(n):
    if n < 20: return ONES[n]
    if n < 100: return TENS[n // 10] + ('' if n % 10 == 0 else ONES[n % 10])
    if n < 1000: return ONES[n // 100] + 'hundred' + ('' if n % 100 == 0 else spell(n % 100))
    return str(n)
def squash(ws):
    """words -> one string, numbers spelled, spacing ignored (stone splinter == stonesplinter)"""
    return ''.join(spell(int(w)) if w.isdigit() and int(w) < 1000 else w.replace("'", '') for w in ws)
def rescore(asr, ours):
    a, b = squash(words(asr)), squash(words(ours, ours=True))
    if not b: return None
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)
QUESTS = json.load(open('ac_quests.json'))

if __name__ == '__main__':
    def load(p):
        try: return [json.loads(l) for l in open(p)]
        except FileNotFoundError: return []
    ss = load('asr/speakstone.jsonl'); gv = load('asr/game_voices.jsonl')
    if ss:
        v = collections.Counter(); w = collections.Counter(); per = collections.defaultdict(collections.Counter)
        rows = []
        for r in ss:
            if 'asr' in r:
                qid, kind, _ = r['key'].split('-'); r['score'] = rescore(r['asr'], QUESTS[qid][KINDS[kind]])
            s = r.get('score'); verdict = 'error' if 'error' in r else 'pass' if s is not None and s >= PASS else 'review' if s is not None and s >= REVIEW else 'fail'
            v[verdict] += 1; w[verdict] += r.get('words', 0); per[r['pack']][verdict] += 1
            rows.append(dict(key=r['key'], verdict=verdict, score=s, pack=r['pack'], file=r['file'], asr=r.get('asr', r.get('error'))))
        with open('asr/speakstone_verdicts.csv', 'w', newline='') as f:
            c = csv.DictWriter(f, fieldnames=list(rows[0])); c.writeheader(); c.writerows(rows)
        print('speakstone', len(ss), dict(v), {k: round(x / 9000, 1) for k, x in w.items()}, 'h')
        for p, c in sorted(per.items()): print(' ', p, dict(c))
        sc = sorted(r['score'] for r in ss if r.get('score') is not None)
        print('  score deciles', [sc[int(len(sc) * q / 10)] for q in range(10)])
    if gv:
        t = [r for r in gv if r.get('db_text')]
        print('game voices', len(gv), 'errors', sum('error' in r for r in gv), '| with db transcript', len(t),
              'agree >=0.9', sum(1 for r in t if (r['score'] or 0) >= 0.9), '<0.75', sum(1 for r in t if (r['score'] or 0) < 0.75))
