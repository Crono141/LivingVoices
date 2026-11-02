"""overnight.run's same-night retake rounds (2026-10-21), with no card touched: the workers, the speech check, ComfyUI and
the director are stand-ins on a throwaway queue. Each case says when the night should stop starting rounds.
  ~/ComfyUI/venv/bin/python overnight_loop_test.py
"""
import datetime as dt, os, sys, tempfile
os.chdir(tempfile.mkdtemp(prefix='overnight_loop_'))
os.environ['OVERNIGHT_DB'] = os.path.abspath('q.sqlite')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overnight as o

class Clock:                                     # the night's time: each worker round moves it on by `step`
    t = None
    @classmethod
    def now(cls): return cls.t

class Night:
    def __init__(self, lines, fail_every=5, step_min=30, check_fails_on=None, abort_on=None, capacity=None):
        self.fail_every, self.step = fail_every, dt.timedelta(minutes=step_min)
        self.check_fails_on, self.abort_on, self.capacity = check_fails_on, abort_on, capacity
        self.rounds = self.checks = self.starts = self.stops = 0; self.n = 0
        c = o.db(); c.execute('DELETE FROM lines')
        c.executemany("INSERT INTO lines (name, status) VALUES (?, 'todo')", [(f'L{i}',) for i in range(lines)])

    def install(self):
        night = self
        class Popen:                             # one card's worker: renders the queue (or what fits) and exits
            def __init__(self, argv):
                if argv[5] != '0': return        # card 0 does the round's work; card 1 shares it
                night.rounds += 1; c = o.db(); Clock.t += night.step
                lim = night.capacity if night.capacity is not None else -1
                c.execute("UPDATE lines SET status='rendered' WHERE name IN (SELECT name FROM lines WHERE status='todo' LIMIT ?)", (lim,))
                if night.abort_on == night.rounds:
                    os.makedirs(o.REPORTS, exist_ok=True); open(f'{o.REPORTS}/.abort_card0', 'w').write('test abort')
            def wait(self): return 0
        def run(argv, check=False):
            if argv[-1] == 'start': night.starts += 1
            if argv[-1] == 'stop': night.stops += 1
        def check():
            c = o.db(); todo = [r[0] for r in c.execute("SELECT name FROM lines WHERE status='rendered' ORDER BY name")]
            if not todo: return {}
            night.checks += 1
            if night.check_fails_on == night.checks: raise RuntimeError('test: Whisper out of memory')
            res = {}
            for nm in todo:
                night.n += 1; bad = night.n % night.fail_every == 0
                res[nm] = (0.5 if bad else 0.95,)
                if bad: c.execute("UPDATE lines SET status=CASE WHEN seed >= ? THEN 'review' ELSE 'todo' END, seed=seed+1 WHERE name=?", (o.SEEDS, nm))
                else: c.execute("UPDATE lines SET status='done' WHERE name=?", (nm,))
            return res
        o.subprocess.Popen, o.subprocess.run, o.check = Popen, run, check
        o.director = lambda stop_at: None
        o.report = lambda night_, res, rounds=1: setattr(night, 'res', res)
        o.dt = type('dtmod', (), {'datetime': Clock, 'timedelta': dt.timedelta})
        Clock.t = dt.datetime(2026, 10, 24, 1, 0)
        return self

    def status(self):
        return dict(o.db().execute('SELECT status, COUNT(*) FROM lines GROUP BY 1').fetchall())

def go(name, night, until='09:00', **want):
    import shutil; shutil.rmtree(o.REPORTS, ignore_errors=True)
    o.until_dt = lambda hhmm: dt.datetime(2026, 10, 24, *map(int, hhmm.split(':')))
    night.install(); o.run(until, ('0', '1'), force=True)
    got = dict(rounds=night.rounds, checks=night.checks, starts=night.starts, stops=night.stops, status=night.status())
    bad = {k: (v, got[k]) for k, v in want.items() if got[k] != v}
    print(('FAIL ' if bad else 'ok   ') + name, got if bad else '', bad if bad else '')
    return not bad

ok = all([
    # 100 lines, every 5th take scored fails: 100 -> 20 retakes (takes 101-120: 4 fail) -> 4 (takes 121-124 pass), all
    # the same night
    go('queue runs dry: retakes the same night until none are left', Night(100),
       rounds=3, checks=3, starts=3, stops=3, status={'done': 100}),
    # a normal night: the queue never empties, one round and the morning check, as before
    go('queue never empties: one round, one check', Night(100, step_min=480, capacity=60),
       rounds=1, checks=1, status={'done': 48, 'todo': 52}),
    # each round takes 4 h: 01:00 -> 05:00 (check, 20 left, 4 h to go: another round) -> 09:00 (check, 4 left, the
    # window closed: they wait for the next night)
    go('rounds stop at the window', Night(100, step_min=240),
       rounds=2, checks=2, status={'done': 96, 'todo': 4}),
    # 08:45 after the first round: under MIN_ROUND (20 min) left, the retakes wait for the next night
    go('under MIN_ROUND left: retakes wait', Night(100, step_min=465),
       rounds=1, checks=1, status={'done': 80, 'todo': 20}),
    go('a failed check ends the night (lines left rendered for the next)', Night(100, check_fails_on=2),
       rounds=2, checks=2, status={'done': 80, 'rendered': 20}),
    go('a card that aborted ends the night', Night(100, abort_on=1),
       rounds=1, checks=1, status={'done': 80, 'todo': 20}),
    go('a round that rendered nothing ends the night', Night(100, capacity=0),
       rounds=1, checks=0, starts=1, status={'todo': 100}),
    # six seeds then review: a line that always fails stops coming back
    go('every take fails: six rounds, then review', Night(3, fail_every=1),
       rounds=6, checks=6, status={'review': 3}),
])
sys.exit(0 if ok else 1)
