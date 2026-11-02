"""Ghosts and spirits get a filter (2026-10-16, the producer): a friendly ghost or spirit, one who still remembers who
they were in life (Janice Felstone), gets 'ghost'; a monstrous one -- a banshee, a wraith, a hostile or sinister
spirit -- gets 'whisperer'. The model reads each speaker's profile and lines and decides; no name matching.

  ../.venv/bin/python ../tools/ghost_check.py run      -> ghost_check.jsonl (resumable)
  ../.venv/bin/python ../tools/ghost_check.py apply    -> morphs.json; the speakers' done lines re-queued
"""
import concurrent.futures as cf, csv, datetime, json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import direct, render, bakeoff, overnight as ov

OUT = 'ghost_check.jsonl'
MORPHS = 'morphs.json'
SYSTEM = """You prepare a World of Warcraft quest voice-over. Decide whether this quest giver is a ghost or spirit: \
the spirit of someone dead, a phantom, a wisp, an ancestor's or a god's spirit -- a being without a living body. \
Living people, the undead with bodies (Forsaken, zombies, skeletons, liches), demons and elementals are NOT ghosts. \
If a ghost, say which kind: "friendly" -- a benign or helpful spirit, someone who still remembers who they were in \
life, a wise ancestor, a nature spirit; or "monstrous" -- a banshee, a wraith, a menacing, cruel or sinister spirit. \
Think first, then answer JSON: {"why": "<one short sentence>", "kind": "living" or "friendly" or "monstrous"}"""
SCHEMA = {'type': 'object', 'required': ['why', 'kind'], 'properties': {
    'why': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['living', 'friendly', 'monstrous']}}}
FILTER = {'friendly': 'ghost', 'monstrous': 'whisperer'}

def speakers():
    out = {}
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['npc_id'].startswith(('go:', 'item:')): continue
        out.setdefault(r['npc_id'], []).append(r)
    return out

def run():
    done = {j['npc'] for j in map(json.loads, open(OUT))} if os.path.exists(OUT) else set()
    work = [(c, rs) for c, rs in speakers().items() if c not in done]
    print(len(work), 'speakers to check', flush=True)
    def one(w):
        c, rs = w; r = rs[0]
        lines = []
        for x in rs[:2]:
            t = render.variant_clean(direct.Q[x['questId']][direct.KINDS[x['kind']]] or '', '')
            if t.strip(): lines.append(t[:500])
        user = (f"Quest giver: {direct.who((c, r['npc_name'], r['race'], r['sex']))}\n"
                f"Their lines:\n" + '\n---\n'.join(lines))
        try: a = bakeoff.llm(SYSTEM, user, SCHEMA)
        except Exception as e: a = {'kind': 'error', 'why': str(e)[:80]}
        return dict(npc=c, name=r['npc_name'], **a)
    with open(OUT, 'a') as f, cf.ThreadPoolExecutor(4) as ex:
        for i, j in enumerate(ex.map(one, work), 1):
            f.write(json.dumps(j) + '\n'); f.flush()
            if i % 500 == 0: print(i, flush=True)

# Claude's review of the model's 105 ghosts (2026-10-16): it also took Ancients, elementals, naaru, totems, loa and
# Sylvanas (a body) for ghosts, and missed Pamela Redpath. npc -> the kind that stands; anyone else is living.
REVIEWED = {**dict.fromkeys(['16073', '21797', '27928', '30216', '28030', '14504'], 'monstrous'),
            **dict.fromkeys(['302', '392', '2994', '3650', '7317', '7572', '7729', '10778', '10927', '10684', '11834',
                             '11936', '12238', '14358', '14566', '15042', '15624', '16033', '17087', '17849', '19489',
                             '19698', '19456', '21292', '21318', '21950', '25425', '26501', '28561', '38608', '10926',
                             '34435', '35256', '34478', '34481', '34484', '34479', '34483', '35260', '35261', '34476',
                             '34477', '34480', '34482'], 'friendly'),
            # (2026-10-16, the producer: "the cheerful gnome spirit does not need that echo") a spirit that is no dead
            # person's ghost -- the festival's cheerful spirits, a wisp, a loa, nature spirits -- reads unfiltered; a
            # banshee the model missed (Melisara) is monstrous
            **dict.fromkeys(['34435', '34476', '34477', '34478', '34479', '34480', '34481', '34482', '34483', '34484',
                             '35256', '35260', '35261', '15624', '14566', '15042', '17087'], 'spirit'),
            '2278': 'monstrous'}

def apply():
    J = [dict(j, kind=REVIEWED[j['npc']]) for j in map(json.loads, open(OUT)) if j['npc'] in REVIEWED]
    J += [dict(npc=n, kind=k) for n, k in REVIEWED.items() if n not in {j['npc'] for j in J} and n in speakers()]
    M = json.load(open(MORPHS)) if os.path.exists(MORPHS) else {}
    rc = ov.race_cast(); sp = speakers(); now = datetime.datetime.now().isoformat(timespec='seconds')
    c = sqlite3.connect(ov.DB, isolation_level=None); n = 0
    for j in J:
        old = M.get(j['npc'], rc.get(j['npc'], {}).get('morph'))
        if old and old not in FILTER.values(): continue        # a robot or a beast keeps its own morph
        new = FILTER.get(j['kind'])
        if old == new: continue
        if new: M[j['npc']] = new
        else: M.pop(j['npc'], None)
        for r in sp[j['npc']]:
            n += c.execute("UPDATE lines SET status='todo', seed=seed+1, updated=? WHERE questId=? AND kind=? AND status IN ('done','review')",
                           (now, r['questId'], r['kind'])).rowcount
    json.dump(dict(sorted(M.items(), key=lambda kv: int(kv[0]))), open(MORPHS, 'w'), indent=1)
    print(len(M), 'speakers with a ghost filter;', n, 'done lines re-queued')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'run': run, 'apply': apply}[sys.argv[1]]()
