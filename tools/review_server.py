"""The review page (2026-10-26): every line that failed all its seeds, its best take and the others, for the producer
to accept, retry, or look at closer (the prompt or the text massaged for a better take). The audio stays where the runner left it (data/render/, data/render/takes/); decisions go
into the queue's own database (review_decisions), for the next step to act on.

Run from data/ with the ComfyUI venv:
  ~/ComfyUI/venv/bin/python ../tools/review_server.py [--port 8470] [--host 0.0.0.0]
"""
import csv, http.server, json, os, re, sqlite3, struct, subprocess, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import overnight as o

SNORTS, SNORT_PICK = 'sfx/snort_cands', 'sfx/snort_pick.json'   # the Snort tab (2026-10-26)
COMPARE = 'compare'           # the Compare tab (2026-10-29): ours against the pack, voice_compare.py
FAULT_ORDER = {'reported in game': -1, 'low score': 0, 'dropped': 1, 'slow': 2, 'odd pause': 3, 'odd delivery': 4, 'missed stop': 5, 'mispronounced': 6}

def db():
    c = o.db()
    c.execute("""CREATE TABLE IF NOT EXISTS review_decisions (name TEXT PRIMARY KEY, decision TEXT, seed INTEGER,
                 note TEXT, updated TEXT)""")
    return c

_VAR = None
def variant(nm):
    """a race/class sentence (variants.py: '<line>_s<i>_<word>') -> its record, else None"""
    global _VAR
    if _VAR is None: _VAR = json.load(open('variants.json')) if os.path.exists('variants.json') else {}
    return _VAR.get(nm)
def base_of(nm): return variant(nm)['base'] if variant(nm) else nm

def meant_text(nm):
    """the words the line is meant to say, as the speech check reads them"""
    import direct, render
    if variant(nm): return render.spoken_text(variant(nm)['text'])
    p = nm.split('-'); q, kind, v = p[0], p[1], (p[2] if len(p) > 2 else '')
    try: return render.spoken_text(render.scripted(render.variant_clean(direct.Q[q][direct.KINDS[kind]] or '', v)))
    except Exception: return ''

CREATURE_TYPE = {1: 'Beast', 2: 'Dragonkin', 3: 'Demon', 4: 'Elemental', 5: 'Giant', 6: 'Undead', 7: 'Humanoid',
                 8: 'Critter', 9: 'Mechanical', 10: 'Not specified', 11: 'Totem', 12: 'Non-combat pet', 13: 'Gas cloud'}
READER = LV.DB_CNF

def zones():
    """zone id -> name, from the client's AreaTable.dbc (the server's areatable_dbc table is empty)"""
    b = open('dbc/AreaTable.dbc', 'rb').read(); _, n, nf, rs, _ = struct.unpack('<4s4I', b[:20]); st = b[20 + n * rs:]
    out = {}
    for i in range(n):
        rec = struct.unpack(f'<{nf}I', b[20 + i * rs: 20 + (i + 1) * rs])
        out[rec[0]] = st[rec[11]:st.index(b'\0', rec[11])].decode('utf-8', 'replace')
    return out

def game_rows(sql):
    """rows from the world database, read-only (db_reader_cnf); none if it is not reachable"""
    try:
        out = subprocess.run(['mysql', f'--defaults-extra-file={READER}', '-B', '-N', '-e', sql], capture_output=True, text=True, timeout=30).stdout
        return [l.split('\t') for l in out.splitlines()]
    except Exception: return []

_CTX = None
def context(names):
    """what the reviewer needs around a line: who speaks it, where, and what the quest is about"""
    global _CTX
    if _CTX is None:
        plan = {o.name_of(r): r for r in csv.DictReader(open('plan_v3.csv'))}
        qs = sorted({base_of(n).split('-')[0] for n in names})
        npcs = sorted({plan[base_of(n)]['npc_id'] for n in names if base_of(n) in plan and plan[base_of(n)]['npc_id'].isdigit()})
        zone = zones()
        quest = {q: (int(sort), lvl) for q, sort, lvl in game_rows(f"SELECT ID, QuestSortID, QuestLevel FROM acore_world.quest_template WHERE ID IN ({','.join(qs) or 0})")}
        npc = {e: (CREATURE_TYPE.get(int(t), t), sub if sub != 'NULL' else '') for e, t, sub in
               game_rows(f"SELECT entry, type, subname FROM acore_world.creature_template WHERE entry IN ({','.join(npcs) or 0})")}
        Q = json.load(open('ac_quests.json')); D = o.load_directions([o.DIRECTIONS])
        notes = json.load(open('actor_notes.json')) if os.path.exists('actor_notes.json') else {}
        vcast = o.load_cast()
        _CTX = {}
        for nm in names:
            b = base_of(nm); r = plan.get(b, {}); q, kind = b.split('-')[0], b.split('-')[1]
            sort, lvl = quest.get(q, (0, ''))
            g = o.as_generated(r) if r else None
            ref = (g or {}).get('clone_ref', '')
            rc = o.race_cast().get(r.get('npc_id', ''))
            if ref.startswith('design:'):
                voice = 'designed: ' + vcast.get(o.voice_key(g), {}).get('description', '(no casting description)')
            elif rc:
                voice = f"cloned from {rc.get('ref') or rc.get('clone_ref')} ({rc.get('src')})" + (f" -- {rc['why']}" if rc.get('why') else '')
            else:
                voice = f'cloned from {ref}' if ref else ''
            d = D.get(q, {}).get(kind) or {}
            qt = Q.get(q, {})
            _CTX[nm] = dict(race=r.get('race', ''), sex=r.get('sex', ''), ctype=npc.get(r.get('npc_id'), ('', ''))[0],
                            subname=npc.get(r.get('npc_id'), ('', ''))[1], zone=zone.get(sort, '') if sort > 0 else '',
                            level=lvl, title=qt.get('title', ''), kind=kind,
                            texts={k: qt.get(o_k, '') for k, o_k in (('accept', 'desc'), ('progress', 'req'), ('complete', 'off'))},
                            note=d.get('note', ''), subtext=d.get('subtext', ''),
                            emotion='; '.join(b.get('emotion', '') for b in d.get('beats', []) if b.get('emotion')),
                            actor=notes.get(r.get('npc_id', ''), ''), voice=voice)
    return _CTX

def load_lines():
    c = db(); out = []
    dec = {n: (d, s, note, u) for n, d, s, note, u in c.execute("SELECT name, decision, seed, note, updated FROM review_decisions")}
    for nm, who, score, heard in c.execute("SELECT name, npc_name, score, heard FROM lines WHERE status='review'"):
        heard = heard or ''
        m = re.match(r'\(best of (\d+) takes: seed (\d+), ([^)]*)\) ', heard)
        best_seed, fault = (int(m.group(2)), m.group(3)) if m else (None, 'unknown')
        rest = heard[m.end():] if m else heard
        flag, said = (rest[:rest.index(') ') + 1], rest[rest.index(') ') + 2:]) if rest.startswith('(') and ') ' in rest else ('', rest)
        gaps = [float(g) for g in re.findall(r' (\d+(?:\.\d+)?)s\b', flag)] if fault == 'odd pause' else []
        takes = [dict(seed=s, raw=r, fault=f, heard=h, file=os.path.basename(p))
                 for s, r, f, h, p in c.execute("SELECT seed, raw, fault, heard, path FROM takes WHERE name=?1 AND path IS NOT NULL "
                                                "AND night=(SELECT MAX(night) FROM takes WHERE name=?1) ORDER BY seed", (nm,))
                 if os.path.exists(p)]
        # (2026-10-31) a mark from an earlier review, made before the line's latest takes, is not a mark on these
        latest = c.execute("SELECT MAX(created) FROM takes WHERE name=?", (nm,)).fetchone()[0] or ''
        d = dec.get(nm) if dec.get(nm) and (dec[nm][3] or '') >= latest else None
        out.append(dict(name=nm, who=who, score=score, fault=fault, best_seed=best_seed, gaps=gaps,
                        max_gap=max(gaps) if gaps else 0, heard=said, flag=flag, meant=meant_text(nm),
                        takes=takes, decision=d[0] if d else None, decision_seed=d[1] if d else None, note=d[2] if d else ''))
    ctx = context([r['name'] for r in out])
    for r in out: r['ctx'] = ctx.get(r['name'], {})
    out.sort(key=lambda r: (FAULT_ORDER.get(r['fault'], 9), r['score'] if r['fault'] == 'low score' else -r['max_gap'], r['name']))
    return out

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/': return self.send(200, open(os.path.join(os.path.dirname(__file__), 'review_page.html'), 'rb').read(), 'text/html; charset=utf-8')
        if path == '/api/lines': return self.send(200, json.dumps(load_lines()))
        if path == '/api/snorts':        # Mangletooth's snort candidates (snort_candidates.py) and the pick so far
            if not os.path.exists(SNORTS + '/index.json'): return self.send(200, '{"cands": []}')
            d = json.load(open(SNORTS + '/index.json'))
            d['pick'] = json.load(open(SNORT_PICK)) if os.path.exists(SNORT_PICK) else {}
            return self.send(200, json.dumps(d))
        if path == '/api/compare':
            if not os.path.exists(COMPARE + '/index.json'): return self.send(200, '{"lines": [], "groups": []}')
            d = json.load(open(COMPARE + '/index.json'))
            d['pick'] = json.load(open(COMPARE + '/pick.json')) if os.path.exists(COMPARE + '/pick.json') else {}
            return self.send(200, json.dumps(d))
        m = re.fullmatch(r'/compare/([\w-]+\.([a-z0-9_]+)\.mp3)', path)   # names only: no slashes, no '..'
        if m and os.path.isfile(os.path.join(COMPARE, m.group(1))):
            return self.send(200, open(os.path.join(COMPARE, m.group(1)), 'rb').read(), 'audio/mpeg')
        m = re.fullmatch(r'/snort/(ctx/)?([\w-]+\.(wav|mp3))', path)
        if m:
            f = os.path.join(SNORTS, 'ctx' if m.group(1) else '', m.group(2))
            if os.path.isfile(f): return self.send(200, open(f, 'rb').read(), 'audio/wav' if m.group(3) == 'wav' else 'audio/mpeg')
        m = re.fullmatch(r'/audio/(takes/)?([\w.+-]+\.mp3)', path)       # names only: no slashes, no '..'
        if m and '..' not in m.group(2):
            f = os.path.join('render', 'takes' if m.group(1) else '', m.group(2))
            if os.path.isfile(f): return self.send(200, open(f, 'rb').read(), 'audio/mpeg')
        self.send(404, '{"error": "not found"}')

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path == '/api/compare':
            # {group, verdict: 'ours'|'pack'|null, note}: per voice; {line, note}: per line
            try:
                d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                idx = json.load(open(COMPARE + '/index.json'))
                pick = json.load(open(COMPARE + '/pick.json')) if os.path.exists(COMPARE + '/pick.json') else {}
                if 'group' in d:
                    if d['group'] not in idx['groups']: raise ValueError('not a voice')
                    if d.get('verdict') not in ('ours', 'pack', None): raise ValueError('bad verdict')
                    v = pick.setdefault('voices', {}).setdefault(d['group'], {})
                    for k in ('verdict', 'note'):
                        if k in d: v[k] = d[k] if k != 'note' else (d[k] or '')[:1000]
                elif 'line' in d:
                    if d['line'] not in {x['name'] for x in idx['lines']}: raise ValueError('not a line')
                    if 'verdict' in d:   # the missed-stop test (2026-10-30): per line, what the splice does
                        if d['verdict'] not in ('splice', 'retake', 'fine', 'good', 'bad', None): raise ValueError('bad verdict')
                        pick.setdefault('stops', {})[d['line']] = d['verdict']
                    else: pick.setdefault('lines', {})[d['line']] = (d.get('note') or '')[:1000]
                else: raise ValueError('nothing to save')
                pick['updated'] = o.now(); json.dump(pick, open(COMPARE + '/pick.json', 'w'), indent=1)
                return self.send(200, json.dumps(pick))
            except Exception as e:
                return self.send(400, json.dumps({'error': str(e)[:200]}))
        if urllib.parse.urlparse(self.path).path == '/api/snort':
            try:
                d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                ids = {c['id'] for c in json.load(open(SNORTS + '/index.json'))['cands']}
                if d.get('snort') is not None and d['snort'] not in ids: raise ValueError('not a candidate')
                if d.get('depth') is not None and d['depth'] not in ('current', 'deeper', 'deepest'): raise ValueError('bad depth')
                pick = json.load(open(SNORT_PICK)) if os.path.exists(SNORT_PICK) else {}
                for k in ('snort', 'depth', 'note'):
                    if k in d: pick[k] = d[k] if k != 'note' else (d[k] or '')[:1000]
                pick['updated'] = o.now(); json.dump(pick, open(SNORT_PICK, 'w'), indent=1)
                return self.send(200, json.dumps(pick))
            except Exception as e:
                return self.send(400, json.dumps({'error': str(e)[:200]}))
        if urllib.parse.urlparse(self.path).path != '/api/decide': return self.send(404, '{"error": "not found"}')
        try:
            d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            nm, decision = d['name'], d.get('decision')
            if decision not in ('accept', 'retry', 'look closer', None): raise ValueError('bad decision')
            c = db()
            if not c.execute("SELECT 1 FROM lines WHERE name=? AND status='review'", (nm,)).fetchone(): raise ValueError('not a review line')
            if decision is None and not d.get('note'): c.execute("DELETE FROM review_decisions WHERE name=?", (nm,))
            else:
                c.execute("INSERT OR REPLACE INTO review_decisions VALUES (?,?,?,?,?)",
                          (nm, decision, d.get('seed'), (d.get('note') or '')[:1000], o.now()))
            self.send(200, '{"ok": true}')
        except Exception as e:
            self.send(400, json.dumps({'error': str(e)[:200]}))

if __name__ == '__main__':
    os.chdir(os.environ.get('OVERNIGHT_DATA', os.path.join(o.VO, 'data')))
    a = sys.argv[1:]; opt = lambda k, dflt: a[a.index(k) + 1] if k in a else dflt
    host, port = opt('--host', '0.0.0.0'), int(opt('--port', '8470'))
    print(f'review page on http://{host}:{port}/ ({len(load_lines())} lines)', flush=True)
    http.server.ThreadingHTTPServer((host, port), H).serve_forever()
