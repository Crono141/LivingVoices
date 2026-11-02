"""Beats that are not turns (2026-10-17, the producer's lever tests): the director split 63% of the lines into two beats
though its brief says one unless the feeling clearly turns, and the second beat is where long takes ran away (Sage
Edan's "These carvings" shouted, Velania's last line lower and slower, Dillinger and Darthalia speeding up exactly
where an "urgent orders" beat began). A second look: the model reads the line and its beats and decides whether the
text really turns there; if not, the line becomes one beat performed as its first beat was (the producer on Velania:
the last line "should be same energy as first line").

  ../.venv/bin/python ../tools/steady_check.py run [name ...]   -> steady_check.jsonl (resumable; names: only those)
  ../.venv/bin/python ../tools/steady_check.py apply            -> directions.jsonl (backup kept); changed done lines re-queued
"""
import concurrent.futures as cf, datetime, json, os, shutil, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, bakeoff, overnight as ov

OUT = 'steady_check.jsonl'
SYSTEM = """You direct a World of Warcraft quest voice-over. A quest giver's line has been split in two (marked ||), each part \
to be performed differently. A split is only right when the speaker's FEELING clearly turns at that point -- calm \
explanation breaking into a battle cry, a joke turning to grief, a report interrupted by alarm. Moving from \
describing a situation to telling the hero what to do is NOT a turn: that is how almost every quest is given, \
in one frame of mind. Neither is more explanation, the next instruction, a request, a hope or a warning in the same \
voice. One person saying one thing reads it in one breath, at one energy. Most splits are not turns. Answer JSON: \
{"why": "<one short sentence>", "turn": true or false}"""

def schema():
    return {'type': 'object', 'required': ['why', 'turn'], 'properties': {'why': {'type': 'string'}, 'turn': {'type': 'boolean'}}}

def multi():
    D = ov.load_directions([ov.DIRECTIONS])
    for q, x in D.items():
        for k, d in x.items():
            if isinstance(d, dict) and len(d.get('beats') or []) > 1 and d.get('voice') != 'narrator':
                yield f'{q}-{k}', q, k, d

def run(only=()):
    done = {j['name'] for j in map(json.loads, open(OUT))} if os.path.exists(OUT) else set()
    work = [w for w in multi() if w[0] not in done and (not only or w[0] in only)]
    print(len(work), 'split lines to check', flush=True)
    def one(w):
        nm, q, k, d = w
        # only the text and where it was split: the director's own labels ("analytical", then "mystical") talked the
        # model into seeing a turn in them (pilot, 2026-10-17)
        ts = render.beat_texts(q, k, '', d['beats'])
        user = f"{d.get('note', '')}\n\nThe line, with the split marked ||:\n{ts[0]}  ||  {' '.join(ts[1:])}"
        try: a = bakeoff.llm(SYSTEM, user, schema())
        except Exception as e: a = {'turn': True, 'why': f'(model failed: {str(e)[:80]})'}
        return dict(name=nm, **a)
    with open(OUT, 'a') as f, cf.ThreadPoolExecutor(4) as ex:
        for i, j in enumerate(ex.map(one, work), 1):
            f.write(json.dumps(j) + '\n'); f.flush()
            if only: print(j['name'], 'TURN' if j['turn'] else 'one beat', '|', j['why'], flush=True)
            elif i % 500 == 0: print(i, flush=True)

def apply():
    J = {j['name']: j for j in map(json.loads, open(OUT)) if not j.get('turn')}
    shutil.copy(ov.DIRECTIONS, ov.DIRECTIONS + '.before_steady')
    out = []; n = 0; changed = set()
    for l in open(ov.DIRECTIONS):
        x = json.loads(l)
        for k, d in x.items():
            j = J.get(f"{x['questId']}-{k}")
            if j and isinstance(d, dict) and len(d.get('beats') or []) > 1:
                b0 = d['beats'][0]
                d['beats'] = [dict(b0, sentences=[1, d['beats'][-1]['sentences'][1]], steadied=j['why'],
                                   text=' '.join(b['text'] for b in d['beats'] if b.get('text')))]
                n += 1; changed.add(f"{x['questId']}-{k}")
        out.append(json.dumps(x))
    open(ov.DIRECTIONS, 'w').write('\n'.join(out) + '\n')
    c = sqlite3.connect(ov.DB, isolation_level=None); now = datetime.datetime.now().isoformat(timespec='seconds'); q = 0
    for nm in changed:
        q += c.execute("UPDATE lines SET status='todo', seed=seed+1, updated=? WHERE (name=? OR name LIKE ?) AND status IN ('done','review')",
                       (now, nm, nm + '-%')).rowcount
    print(n, 'lines made one beat;', q, 'done lines re-queued')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'run': lambda: run(set(sys.argv[2:])), 'apply': apply}[sys.argv[1]]()
