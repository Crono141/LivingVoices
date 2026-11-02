"""Narrator or quest giver? A second, single-question look at every line the director gave to the quest giver
(2026-10-15, the producer: Tiev Mordune's "Light explodes as you finish the incantation..." was voiced by Tiev). The
director answers this inside a long prompt with many other jobs; here the model judges only this, one line at a time.

  ../.venv/bin/python ../tools/narration_check.py run      -> narration_check.jsonl (resumable)
  ../.venv/bin/python ../tools/narration_check.py apply    -> directions.jsonl gets voice: narrator; lines re-queued
"""
import concurrent.futures as cf, csv, datetime, json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import direct, render, bakeoff, overnight as ov

OUT = 'narration_check.jsonl'
SYSTEM = """You prepare World of Warcraft quest text for a voice-over. Nearly every line is the quest giver \
talking to the hero, and is spoken in their voice. A very few lines are not speech at all: a storyteller reads them. \
Speech is often full of "you" -- a question to the hero ("You have the letter? Good."), an order ("You must hurry \
to the mill"), a remark ("You look half-starved, friend"). All of that is speech. Narration is a scene described as \
it happens, like a book, that no character could say aloud: "You lift the lid. Inside, something stirs and \
hisses." / "The old woman says nothing. She stares into the fire, her hands trembling." Decide by asking: could the \
quest giver say these exact words aloud to the hero? If any part of it plainly could, it is speech. A sentence in \
angle brackets is a stage direction and is read separately: judge the rest. Think first, then answer JSON: \
{"why": "<one short sentence>", "voice": "npc" or "narrator"}"""
SCHEMA = {'type': 'object', 'required': ['why', 'voice'], 'properties': {
    'why': {'type': 'string'}, 'voice': {'type': 'string', 'enum': ['npc', 'narrator']}}}

def todo():
    D = ov.load_directions([ov.DIRECTIONS])
    sp = {}
    for r in csv.DictReader(open('plan_v3.csv')): sp.setdefault((r['questId'], r['kind']), r)
    out = []
    for q, x in D.items():
        for kind in ('accept', 'progress', 'complete'):
            d = x.get(kind)
            if not isinstance(d, dict) or d.get('voice') != 'npc' or (q, kind) not in sp: continue
            r = sp[(q, kind)]
            if r['npc_id'].startswith(('go:', 'item:')): continue
            text = render.variant_clean(direct.Q[q][direct.KINDS[kind]] or '', '')
            if text.strip(): out.append((q, kind, r, text))
    return out

def run():
    done = {(j['questId'], j['kind']) for j in map(json.loads, open(OUT))} if os.path.exists(OUT) else set()
    work = [w for w in todo() if (w[0], w[1]) not in done]
    print(len(work), 'lines to check', flush=True)
    def one(w):
        q, kind, r, text = w
        who = direct.who((r['npc_id'], r['npc_name'], r['race'], r['sex'])).split('\n')[0]
        user = f'Quest giver: {who}\nQuest: {direct.Q[q]["title"]}\nThe line:\n{text}'
        try: a = bakeoff.llm(SYSTEM, user, SCHEMA)
        except Exception as e: a = {'voice': 'error', 'why': str(e)[:80]}
        return dict(questId=q, kind=kind, npc=r['npc_name'], **a)
    with open(OUT, 'a') as f, cf.ThreadPoolExecutor(4) as ex:
        for i, j in enumerate(ex.map(one, work), 1):
            f.write(json.dumps(j) + '\n'); f.flush()
            if i % 500 == 0: print(i, flush=True)

def apply():
    J = [j for j in map(json.loads, open(OUT)) if j['voice'] == 'narrator']
    D = ov.load_directions([ov.DIRECTIONS]); now = datetime.datetime.now().isoformat(timespec='seconds')
    c = sqlite3.connect(ov.DB, isolation_level=None); quests = {}
    for j in J:
        x = quests.setdefault(j['questId'], D[j['questId']])
        x[j['kind']]['voice'] = 'narrator'
        x[j['kind']]['note'] = f"Narration (narration check 2026-10-15: {j['why']})"
        c.execute("UPDATE lines SET status='todo', seed=seed+1, updated=? WHERE questId=? AND kind=? AND status IN ('done','review')",
                  (now, j['questId'], j['kind']))
    with open(ov.DIRECTIONS, 'a') as f:
        for x in quests.values(): f.write(json.dumps(x) + '\n')
    print(len(J), 'lines now narrated, in', len(quests), 'quests')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'run': run, 'apply': apply}[sys.argv[1]]()
