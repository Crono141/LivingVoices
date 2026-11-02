"""Titles and nicknames said as names (2026-10-18, the producer): "May its power aid you, god-slayer!" and "What do you
want, stranger?" came out with the title read as a plain word. Capitals did nothing; an ellipsis before it did
("What do you want... stranger?" -- "This actually worked"). A sentence ending in a comma and a short phrase is shown
to the model, which decides whether that phrase is a title or nickname the speaker gives the listener (godslayer,
stranger, young hero), a casual tag that runs on (mon, lad, friend -- a pause before every one would be
a Kirk pause -- render.scripted sets one apart once in a beat), or no address at all. Titles read with an
ellipsis before them, and no hyphen inside.

  ../.venv/bin/python ../tools/title_check.py run      -> title_check.jsonl (resumable)
  ../.venv/bin/python ../tools/title_check.py apply    -> titles.json (render.scripted reads it); changed done lines re-queued
"""
import concurrent.futures as cf, csv, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT, TITLES = 'title_check.jsonl', 'titles.json'
END = re.compile(r",\s+((?:[\w'’-]+\s+){0,2}[\w'’-]+)(\s*[?!.]+[\"'”]?)$")
SYSTEM = """You direct a World of Warcraft quest voice-over. A quest giver speaks to the hero; the sentence ends with a \
comma and a short phrase. Decide what that phrase is:
- "title": a title, epithet or nickname the speaker gives the listener and says AS A NAME -- godslayer, stranger, \
young hero, champion, slayer of dragons, little sister, soldier. The voice actor would set it apart, as a name.
- "casual": a quick, habitual tag that runs straight on from the sentence -- mon, lad, lass, friend, my friend, sir, \
matey, eh -- said in the same breath.
- "not": not addressing the listener at all (though, of course, too, you know, did he, return to me).
Answer JSON: {"why": "<one short sentence>", "kind": "title" | "casual" | "not"}"""

def schema():
    return {'type': 'object', 'required': ['why', 'kind'],
            'properties': {'why': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['title', 'casual', 'not']}}}

def candidates():
    import render, direct
    seen, out = set(), []
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['npc_id'] == 'none' or r['npc_id'].startswith(('go:', 'item:')): continue      # the narrator addresses nobody
        t = direct.Q.get(r['questId'], {}).get(direct.KINDS[r['kind']]) or ''
        for s in direct.sentences(render.variant_clean(t, r['variant'])):
            s2 = render.drop_address(render.SCRIPTS.get(s, s))
            if s2 not in seen and END.search(s2): seen.add(s2); out.append(s2)
    return out

def run():
    import bakeoff
    done = {j['sentence'] for j in map(json.loads, open(OUT))} if os.path.exists(OUT) else set()
    work = [s for s in candidates() if s not in done]
    print(len(work), 'sentences to check', flush=True)
    def one(s):
        user = f"The sentence:\n{s}\n\nThe closing phrase: \"{END.search(s).group(1)}\""
        try: a = bakeoff.llm(SYSTEM, user, schema())
        except Exception as e: a = {'kind': 'not', 'why': f'(model failed: {str(e)[:80]})'}
        return dict(sentence=s, **a)
    with open(OUT, 'a') as f, cf.ThreadPoolExecutor(4) as ex:
        for i, j in enumerate(ex.map(one, work), 1):
            f.write(json.dumps(j) + '\n'); f.flush()
            if i % 500 == 0: print(i, flush=True)

def read_as(s):
    m = END.search(s)
    return s[:m.start()] + '... ' + m.group(1).replace('-', '') + m.group(2)

def apply():
    import overnight as ov, render, direct
    J = list(map(json.loads, open(OUT)))
    out = {k: {j['sentence']: read_as(j['sentence']) for j in J if j.get('kind') == k} for k in ('title', 'casual')}
    json.dump(out, open(TITLES, 'w'), indent=1, ensure_ascii=False); open(TITLES, 'a').write('\n')
    T = set(out['title']) | set(out['casual'])
    c = ov.db(); now = ov.now(); q = 0
    for r in csv.DictReader(open('plan_v3.csv')):
        t = direct.Q.get(r['questId'], {}).get(direct.KINDS[r['kind']]) or ''
        if any(render.drop_address(render.SCRIPTS.get(s, s)) in T for s in direct.sentences(render.variant_clean(t, r['variant']))):
            q += c.execute("UPDATE lines SET status='todo', seed=seed+1, updated=? WHERE name=? AND status IN ('done','review')",
                           (now, ov.name_of(r))).rowcount
    print(len(out['title']), 'titles,', len(out['casual']), 'casual tags;', q, 'done lines re-queued')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'run': run, 'apply': apply}[sys.argv[1]]()
