"""overnight.keep_take / to_review (2026-10-25): every scored take is kept with its raw score, and a line that fails
all its seeds goes to review with its best take as the line's file. No card touched: a throwaway queue and stand-in files.
  ~/ComfyUI/venv/bin/python overnight_takes_test.py
"""
import os, sys, tempfile
os.chdir(tempfile.mkdtemp(prefix='overnight_takes_'))
os.environ['OVERNIGHT_DB'] = os.path.abspath('q.sqlite')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overnight as o

os.makedirs('render/takes')
c = o.db(); c.execute("INSERT INTO lines (name, status, seed) VALUES ('L1', 'todo', 1)")
# six takes: (raw, fault, faults). Seeds 2 and 5 tie on raw; seed 5 has fewer faults and should win
takes = {1: (0.91, 'odd pause', 2), 2: (0.97, 'odd pause', 2), 3: (0.62, 'low score', 0),
         4: (0.95, 'dropped', 1), 5: (0.97, 'odd pause', 1), 6: (0.90, 'slow', 1)}
for seed, (raw, fault, faults) in takes.items():
    open('render/L1.mp3', 'w').write(f'take {seed}')           # the worker's render of this seed
    o.keep_take(c, 'L1', seed, raw, fault, faults, f'heard {seed}')
o.to_review(c, 'L1')

ok = True
def check(what, got, want):
    global ok; good = got == want; ok &= good
    print(('ok   ' if good else 'FAIL ') + what, '' if good else f'got {got!r}, want {want!r}')
check('six takes kept', c.execute("SELECT COUNT(*) FROM takes WHERE name='L1' AND path IS NOT NULL").fetchone()[0], 6)
check('each take its own file', open('render/takes/L1.s3.mp3').read(), 'take 3')
check('raw score kept, not the capped one', c.execute("SELECT raw FROM takes WHERE name='L1' AND seed=2").fetchone()[0], 0.97)
st, score, heard = c.execute("SELECT status, score, heard FROM lines WHERE name='L1'").fetchone()
check('line goes to review', st, 'review')
check('best take: highest raw, then fewest faults', open('render/L1.mp3').read(), 'take 5')
check('line carries the best take score', score, 0.97)
check('heard says which take', heard.startswith('(best of 6 takes: seed 5, odd pause)'), True)
sys.exit(0 if ok else 1)
