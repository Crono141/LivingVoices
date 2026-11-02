"""Voice-over plan v3: reuse or generate every quest line under the casting rules (data/casting.json).

Run from data/:  PYTHONPATH=../tools ../.venv/bin/python ../tools/plan_v2.py
Writes plan_v3.csv and prints the report numbers.

- accept speaks with the quest STARTER's voice, progress and complete with the quest ENDER's.
- the NPC's race/sex (creature_template_model -> CreatureDisplayInfo -> CreatureDisplayInfoExtra) picks the family.
- carevass and Chatty Little NPC are rejected: never reused, never cloned.
- spoken: corpus text verified (exact / near); mrthinger: verified as in reuse.py; speakstone: no published text ->
  'unverified_id_match' when the clip length fits our text (0.6-1.8x of words / pack median words-per-second);
  these need a speech-recognition check before shipping. SpeakStone reads $G as the male form: its clips serve the
  'm' (or ungendered) variant only.
- v3 (2026-10-11): families 'spoken' and 'spoken|speakstone' are era-split PER NPC: an NPC with any Vanilla quest
  speaks Spoken, any other speaks SpeakStone (Spoken is Vanilla-only). One NPC never mixes packs: it uses its era's
  pack when that pack has any clip of it, else the other, and generates the rest by cloning its own clip.
- v3: a creature with no detectable race (unique models) or an uncast race takes the majority SpeakStone voice code
  over its quests (HuM, BEF, ...); codes outside the playable races (EtM ethereal, TkM tuskarr, ...) cast SpeakStone.
- race unknown (no CreatureDisplayInfoExtra, gameobjects, items) or a race nobody cast (Broken, Taunka, ...):
  today's order minus the rejected packs (spoken > mrthinger).
"""
import json, gzip, re, csv, sys, struct, statistics, collections, difflib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
from sqlrows import rows, live_rows
from luaload import load_table

SQL = f'{LV.AC_SQL}/'
KINDS = {'accept': 'desc', 'progress': 'req', 'complete': 'off'}
SS_KIND = {'description': 'accept', 'progress': 'progress', 'completion': 'complete'}
SS_CODEKEY = {'accept': 'd', 'progress': 'p', 'complete': 'c'}
SS_PACKS = ['classic1', 'classic2', 'forever1', 'forever2', 'tbc', 'wotlk']
SS_RACE = {'Hu': 'Human', 'Dw': 'Dwarf', 'Gn': 'Gnome', 'NE': 'Night Elf', 'Dr': 'Draenei', 'Or': 'Orc', 'Tr': 'Troll',
           'Ta': 'Tauren', 'Ud': 'Undead', 'BE': 'Blood Elf', 'Go': 'Goblin'}
RACE_CODE = {v: k for k, v in SS_RACE.items()}
RACES = {1: 'Human', 2: 'Orc', 3: 'Dwarf', 4: 'Night Elf', 5: 'Undead', 6: 'Tauren', 7: 'Gnome', 8: 'Troll', 9: 'Goblin',
         10: 'Blood Elf', 11: 'Draenei', 12: 'Fel Orc', 13: 'Naga', 14: 'Broken', 15: 'Skeleton', 16: 'Vrykul',
         17: 'Tuskarr', 18: 'Forest Troll', 19: 'Taunka', 20: 'Northrend Skeleton', 21: 'Ice Troll'}
CORPUS_RACE = {'Human': 'human', 'Dwarf': 'dwarf', 'Gnome': 'gnome', 'Night Elf': 'nightelf', 'Orc': 'orc',
               'Troll': 'troll', 'Tauren': 'tauren', 'Undead': 'scourge', 'Goblin': 'goblin', 'Blood Elf': 'bloodelf',
               'Draenei': 'draenei'}
SS_LO, SS_HI = 0.6, 1.8
GPAT = re.compile(r'\$[Gg]\s*([^:;]+?)\s*:\s*([^:;]+?)\s*;')

# ---------------------------------------------------------------- text helpers (as reuse.py)
def variant_text(t, v):
    if v == 'm': return GPAT.sub(r'\1', t)
    if v == 'f': return GPAT.sub(r'\2', t)
    return t

def spoken_words(t):
    t = re.sub(r'\$[Bb]', ' ', t)
    m = re.fullmatch(r'\s*<\s*(.*?)\s*>\s*', t, re.S)
    t = m.group(1) if m else re.sub(r'<[^>]*>', ' ', t)
    t = re.sub(r'\$[NnCcRr]', 'adventurer', t)
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", t))

def ws(t): return re.sub(r'\s+', ' ', t.replace('\r', ' ')).strip()

def loose(t):
    t = re.sub(r'\$[Bb]', ' ', t).lower()
    t = re.sub(r"[^a-z0-9$ ]+", ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def ratio(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < 0.97 or sm.quick_ratio() < 0.97: return sm.quick_ratio()
    return sm.ratio()

def compare(src, our):
    if src is None: return None, None
    if ws(src) == ws(our): return 'exact', 1.0
    a, b = loose(src), loose(our)
    if a == b: return 'near_punct', 1.0
    r = ratio(a, b)
    return ('near_97' if r >= 0.97 else 'differs'), r

def fingerprint(t, n):
    w = re.findall(r'\S+', t)
    s = ' '.join(w[:n]) + ' ' + ' '.join(w[-n:])
    s = s.replace('"', "'").replace('\r', ' ').replace('\n', ' ')
    return ws(re.sub(r'(\$[Bb])+', ' ', s))

def sqltable(name):
    txt = open(SQL + name + '.sql', encoding='utf-8', errors='replace').read()
    body = txt[txt.index('CREATE TABLE'):]; body = body[:body.index(') ENGINE')]
    c = [m.group(1) for m in re.finditer(r'^\s+`(\w+)`', body, re.M)]
    for r in rows(SQL + name + '.sql', null=''):
        yield dict(zip(c, r))
    yield from live_rows(name)                  # the realm's own and the holiday quests (extract_live.py)

def dbc(path):
    b = open(path, 'rb').read(); _, n, fc, rs, _ = struct.unpack('<4s4I', b[:20])
    return [struct.unpack(f'<{fc}I', b[20 + i * rs:20 + (i + 1) * rs]) for i in range(n)]

def race_key(race, sex): return f"{race.lower().replace(' ', '_')}_{sex}"

# ---------------------------------------------------------------- our clips
ours = json.load(open('ac_quests.json'))
our_clips = {}
for qid, q in ours.items():
    for kind, col in KINDS.items():
        t = q.get(col) or ''
        if not t.strip(): continue
        for v in (['m', 'f'] if GPAT.search(t) else ['']):
            our_clips[(int(qid), kind, v)] = (t, spoken_words(variant_text(t, v)))

# ---------------------------------------------------------------- who speaks: starters, enders, race/sex
extra = {r[0]: (r[1], r[2]) for r in dbc('dbc/CreatureDisplayInfoExtra.dbc')}
disp = {r[0]: extra.get(r[3]) for r in dbc('dbc/CreatureDisplayInfo.dbc')}
models = collections.defaultdict(list)
for r in sqltable('creature_template_model'):
    models[int(r['CreatureID'])].append((int(r['Idx']), int(r['CreatureDisplayID'])))
names = {int(r['entry']): r['name'] for r in sqltable('creature_template')}
go_names = {int(r['entry']): r['name'] for r in sqltable('gameobject_template')}

def npc_race(cid):
    for _, d in sorted(models.get(cid, [])):
        rs = disp.get(d)
        if rs and rs[0] in RACES: return RACES[rs[0]], ('male', 'female')[rs[1]] if rs[1] in (0, 1) else 'unknown'
    return None, None

cstart, cend, gstart, gend = (collections.defaultdict(list) for _ in range(4))
for tbl, d in (('creature_queststarter', cstart), ('creature_questender', cend),
               ('gameobject_queststarter', gstart), ('gameobject_questender', gend)):
    for r in sqltable(tbl): d[int(r['quest'])].append(int(r['id']))
item_start = collections.defaultdict(list); item_names = {}
for r in sqltable('item_template'):
    item_names[int(r['entry'])] = r['name']
    if r['startquest'] not in ('', '0'): item_start[int(r['startquest'])].append(int(r['entry']))
startitem = {int(r['ID']): int(r['StartItem']) for r in sqltable('quest_template') if r['StartItem'] not in ('', '0')}
giver_map = json.load(open('quest_giver_race.json'))

def pick(cands, prefer=None):
    """Prefer `prefer`, then creatures with a known race, then the lowest id."""
    if prefer in cands: return prefer
    known = [c for c in sorted(cands) if npc_race(c)[0]]
    return (known or sorted(cands))[0]

def speaker(qid, kind):
    """-> (npc_id label, name, race|None, sex|None, creature id|None)"""
    if kind == 'accept':
        if str(qid) in giver_map: c = giver_map[str(qid)]['npc']
        elif cstart.get(qid): c = pick(cstart[qid])
        elif gstart.get(qid): g = min(gstart[qid]); return f'go:{g}', go_names.get(g, ''), None, None, None
        else:
            it = (item_start.get(qid) or [startitem.get(qid, 0)])[0]
            return f'item:{it}', item_names.get(it, ''), None, None, None
    else:
        if cend.get(qid):
            st = giver_map.get(str(qid), {}).get('npc') or (pick(cstart[qid]) if cstart.get(qid) else None)
            c = pick(cend[qid], st)
        elif gend.get(qid): g = min(gend[qid]); return f'go:{g}', go_names.get(g, ''), None, None, None
        else: return 'none', '', None, None, None
    race, sex = npc_race(c)
    return str(c), names.get(c, ''), race, sex, c

# ---------------------------------------------------------------- pack inventories
NAME = re.compile(r'^(?:([mf])-)?(\d+)-(accept|progress|complete)\.(mp3|ogg)$')
inv = {'spoken': {}, 'mrthinger': {}}
for f, pack in (('sq.json', 'spoken'), ('AI_VoiceOverData_Vanilla.json', 'mrthinger')):
    for n, (m, cz, u, o) in json.load(open(f)).items():
        if '/sounds/quests/' not in n: continue
        if pack == 'mrthinger' and not n.startswith('AI_VoiceOverData_Vanilla/'): continue
        mm = NAME.match(n.rsplit('/', 1)[1])
        if mm: inv[pack].setdefault((int(mm.group(2)), mm.group(3), mm.group(1) or ''), (n, cz))

corpus = json.load(gzip.open('spoken_corpus.json.gz'))
CT, CNPC = {}, {}
npc_voice = collections.defaultdict(collections.Counter); race_voice = collections.defaultdict(collections.Counter)
for l in corpus['lines']:
    if l.get('npcId') and l.get('voice'): npc_voice[str(l['npcId'])][l['voice']] += 1
    if l.get('race') and l.get('voice') and not l['voice'].startswith('model-'):
        race_voice[(l['race'], l.get('gender'))][l['voice']] += 1
    if l['source'] in KINDS and l.get('questId'):
        CT.setdefault((l['questId'], l['source']), l['originalText'])

def lookup_index(path):
    t = load_table(path); idx = collections.defaultdict(lambda: {'titles': set(), 'fps': set()})
    def walk(src, title, node):
        if isinstance(node, int): idx[(node, src)]['titles'].add(title); return
        for k, v in node.items():
            if isinstance(v, int) and len(k.split()) > 6: idx[(v, src)]['fps'].add(k); idx[(v, src)]['titles'].add(title)
            else: walk(src, title, v)
    for src, titles in t.items():
        for title, node in titles.items(): walk(src, title, node)
    return idx
MT_LK = lookup_index('lookups/v_q.lua'); MT_SL = load_table('lookups/sl_Vanilla.lua')
VANILLA = {k[0] for k in MT_LK} | {k[0] for k in CT}

# SpeakStone: inventory, lengths, voice codes
ss_inv = collections.defaultdict(dict)     # (qid, kind) -> pack -> (file, cz, dur)
ss_code = {}                               # (pack, qid) -> {'d','p','c'}
for p in SS_PACKS:
    sl = {m.group(1): float(m.group(2)) for m in
          re.finditer(r'\["([^"]+)"\]\s*=\s*([\d.]+)', open(f'speakstone/{p}_SoundLengths.lua').read())}
    for n, (m, cz, u, o) in json.load(open(f'idx_speakstone_{p}.json')).items():
        mm = re.search(r'/Sounds/(\d+)_(description|progress|completion)\.ogg$', n)
        if mm: ss_inv[(int(mm.group(1)), SS_KIND[mm.group(2)])][p] = (n, cz, sl.get(n.rsplit('/', 1)[1]))
    reg = open(f'speakstone/{p}_Register.lua').read()
    for m in re.finditer(r'\[(\d+)\]\s*=\s*(?:"(\w*)"|\{([^}]*)\})', reg[reg.index('quest = {'):]):
        if m.group(2) is not None: c = {'d': m.group(2), 'p': m.group(2), 'c': m.group(2)}
        else:
            c = dict(re.findall(r'(\w)\s*=\s*"(\w*)"', m.group(3)))
            c.setdefault('c', c.get('p', c.get('d'))); c.setdefault('p', c['c']); c.setdefault('d', c['c'])
        ss_code[(p, int(m.group(1)))] = c

def code_ok(code, race, sex):
    if not code or race is None: return None
    if race.startswith('ss:'): return code[:2] == race[3:] and code[-1] == sex[0].upper()
    return SS_RACE.get(code[:-1]) == race and code[-1] == sex[0].upper()

# pack medians: words per second on clips with >= 15 words
SS_WPS = {}
for p in SS_PACKS:
    xs = [our_clips[(q, k, v)][1] / dur for (q, k), d in ss_inv.items() if p in d and (dur := d[p][2])
          for v in ('', 'm') if (q, k, v) in our_clips and our_clips[(q, k, v)][1] >= 15]
    SS_WPS[p] = statistics.median(xs)

# ---------------------------------------------------------------- per-family candidate evaluation
def eval_spoken(key, text):
    if key not in inv['spoken']: return None
    tier, r = compare(CT.get((key[0], key[1])), text)
    fn, cz = inv['spoken'][key]
    ok = tier in ('exact', 'near_punct', 'near_97')
    return dict(pack='spoken', tier=tier or 'no_source_text', file=fn, cz=cz, ok=ok)

MT_SPW = []
def mt_tier(key, text):
    qid, kind, v = key
    li = MT_LK.get((qid, kind)); r = None
    if li and li['fps']:
        ofp = fingerprint(text, 15); fps = {ws(x) for x in li['fps']}
        if ofp in fps: return 'fp_exact'
        r = max(ratio(loose(x), loose(ofp)) for x in fps)
        return ('fp_near_punct' if r == 1.0 else 'fp_near_97') if r >= 0.97 else 'fp_differs'
    t2, r = compare(CT.get((qid, kind)), text)
    if t2: return 'proxy_' + t2
    if li is None: return 'id_only_nolookup'
    return 'id_title' if ws(ours[str(qid)]['title'].replace('"', "'")) in {ws(x) for x in li['titles']} else 'id_title_differs'

mt_cache = {}
for key, (text, words) in our_clips.items():
    if key in inv['mrthinger']:
        fn, cz = inv['mrthinger'][key]
        dur = MT_SL.get(fn.rsplit('/', 1)[1].rsplit('.', 1)[0]); tier = mt_tier(key, text)
        mt_cache[key] = (fn, cz, dur, tier)
        if dur and words >= 15 and 'exact' in tier: MT_SPW.append(dur / words)
MT_MED = statistics.median(MT_SPW)

def eval_mrthinger(key, words):
    if key not in mt_cache: return None
    fn, cz, dur, tier = mt_cache[key]
    ok = not ('differs' in tier or tier == 'id_only_nolookup')
    if ok and dur:
        exp = MT_MED * words + 1.0; ok = 0.5 * exp <= dur <= 2.0 * exp
        if not ok: tier += '/bad_duration'
    return dict(pack='mrthinger', tier=tier, file=fn, cz=cz, ok=ok, dur=dur)

ss_stats = collections.Counter()
def eval_speakstone(key, words, race, sex):
    qid, kind, v = key
    cands = ss_inv.get((qid, kind))
    if not cands: return None
    if v == 'f':
        ss_stats['female_variant_skipped'] += 1
        return dict(pack='speakstone', tier='male_form_only', ok=False)
    best = None
    for p, (fn, cz, dur) in cands.items():
        if not dur: continue
        x = dur / (words / SS_WPS[p]) if words else 99
        code = ss_code.get((p, qid), {}).get(SS_CODEKEY[kind])
        cand = dict(pack=f'speakstone_{p}', file=fn, cz=cz, dur=dur, x=x, code=code, cok=code_ok(code, race, sex))
        rank = (cand['cok'] is False, not (SS_LO <= x <= SS_HI), abs(1 - x))
        if best is None or rank < best[0]: best = (rank, cand)
    if best is None: return None
    c = best[1]
    if not SS_LO <= c['x'] <= SS_HI:
        ss_stats['bad_duration'] += 1; c.update(tier='unverified_id_match/bad_duration', ok=False)
    elif c['cok'] is False:
        ss_stats['voice_code_mismatch'] += 1; c.update(tier=f"unverified_id_match/voice_{c['code']}", ok=False)
    else:
        ss_stats['ok'] += 1; c.update(tier='unverified_id_match', ok=True)
    return c

# ---------------------------------------------------------------- casting
casting = json.load(open('casting.json'))
def family_order(race, sex, qid):
    rk = race_key(race, sex) if race and sex in ('male', 'female') else None
    ent = casting.get(rk) if rk else None
    if ent is None: return 'spoken>mrthinger', ['spoken', 'mrthinger'], None
    fam = ent.get('family') or 'ours'          # human_male undecided in casting.json -> ours (designed flavors)
    if fam == 'spoken|speakstone':
        return fam, (['spoken', 'speakstone'] if qid in VANILLA else ['speakstone', 'spoken']), ent.get('tempo')
    return fam, [fam], ent.get('tempo')

# ---------------------------------------------------------------- v3: race from SpeakStone codes, per-NPC era
SPEAK = {}
for key in our_clips:
    if (key[0], key[1]) not in SPEAK: SPEAK[(key[0], key[1])] = speaker(key[0], key[1])
code_votes = collections.defaultdict(collections.Counter)
for (qid, kind), (npc, nname, race, sex, cid) in SPEAK.items():
    if cid is None or (race and race_key(race, sex or '') in casting): continue
    for p in SS_PACKS:
        code = ss_code.get((p, qid), {}).get(SS_CODEKEY[kind])
        if code and len(code) == 3 and code[-1] in 'MF': code_votes[npc][code] += 1
inferred = {}
for npc, cv in code_votes.items():
    code = cv.most_common(1)[0][0]; sx = 'male' if code[-1] == 'M' else 'female'
    inferred[npc] = (SS_RACE[code[:2]], sx) if code[:2] in SS_RACE else ('ss:' + code[:2], sx)
for k, (npc, nname, race, sex, cid) in list(SPEAK.items()):
    if npc in inferred: SPEAK[k] = (npc, nname) + inferred[npc] + (cid,)
npc_vanilla = collections.defaultdict(bool)
for (qid, kind), sp in SPEAK.items(): npc_vanilla[sp[0]] |= qid in VANILLA

def family_order(race, sex, qid, npc):
    if race and race.startswith('ss:'): return 'speakstone', ['speakstone'], None
    rk = race_key(race, sex) if race and sex in ('male', 'female') else None
    ent = casting.get(rk) if rk else None
    if ent is None: return 'spoken>mrthinger', ['spoken', 'mrthinger'], None
    fam = ent.get('family') or 'ours'
    if fam in ('spoken', 'spoken|speakstone'):
        return fam, (['spoken', 'speakstone'] if npc_vanilla[npc] else ['speakstone', 'spoken']), ent.get('tempo')
    return fam, [fam], ent.get('tempo')

def evaluate(f, key, text, words, race, sex):
    return (eval_spoken(key, text) if f == 'spoken' else eval_mrthinger(key, words) if f == 'mrthinger'
            else eval_speakstone(key, words, race, sex))

# lock each era-split NPC to one pack: its era's pack if that has any usable clip of it, else the other
lock = {}
for key in our_clips:
    npc, nname, race, sex, cid = SPEAK[(key[0], key[1])]
    fam, order, _ = family_order(race, sex, key[0], npc)
    if fam not in ('spoken', 'spoken|speakstone'): continue
    for i, f in enumerate(order):
        e = evaluate(f, key, *our_clips[key], race, sex)
        if e and e['ok']: lock[npc] = min(lock.get(npc, 9), i)
ss_stats.clear()

out = []
for key in sorted(our_clips):
    qid, kind, v = key
    text, words = our_clips[key]
    npc, nname, race, sex, cid = SPEAK[(qid, kind)]
    fam, order, tempo = family_order(race, sex, qid, npc)
    if fam in ('spoken', 'spoken|speakstone'): order = [order[lock.get(npc, 0)]]
    chosen, tried = None, []
    for f in order:
        if f == 'ours': break
        e = evaluate(f, key, text, words, race, sex)
        if e: tried.append(e)
        if e and e['ok']: chosen = e; break
    rkn = race_key(race, sex) if race else 'unknown'
    known = race is not None and (rkn in casting or race.startswith('ss:'))
    row = dict(questId=qid, kind=kind, variant=v, npc_id=npc, npc_name=nname, race=race or 'unknown',
               sex=sex or 'unknown', family=(fam + '=' + order[0] if '|' in fam or fam == 'spoken' else fam) if known else ('uncast:' if race else '') + fam,
               words=words, order=order, tried=tried)
    if chosen:
        row.update(action='reuse', source_pack=chosen['pack'], match_tier=chosen['tier'], file_in_pack=chosen['file'],
                   cz=chosen['cz'], dur=chosen.get('dur'), code=chosen.get('code'), clone_ref='')
    else:
        row.update(action='generate', source_pack='', file_in_pack='', cz=0,
                   match_tier=';'.join(f"{e['pack']}:{e['tier']}" for e in tried) or ('ours' if order == [] or 'ours' in order else 'no_clip'))
    pf = (chosen or {}).get('pack', '')
    row['tempo'] = tempo if tempo and (pf == 'spoken' or (not chosen and order and order[0] == 'spoken')) else ''
    out.append(row)

# v3: speech-recognition verdicts (tools/asr_check.py + asr_report.py): a SpeakStone clip that does not say our
# text (score < 0.90) is generated instead -- cloned from that same clip, so the NPC keeps the voice.
ASR = {}
if os.path.exists('asr/speakstone_verdicts.csv'):
    ASR = {r['key']: r for r in csv.DictReader(open('asr/speakstone_verdicts.csv'))}
asr_dropped = 0
for r in out:
    a = ASR.get(f"{r['questId']}-{r['kind']}-{r['variant']}")
    if r['action'] == 'reuse' and r['source_pack'].startswith('speakstone') and a and a['verdict'] != 'pass':
        r.update(action='generate', match_tier=f"asr_{a['verdict']}:{a['score']}", asr_ref=f"{r['source_pack']}:{r['file_in_pack']}",
                 source_pack='', file_in_pack='', cz=0)
        asr_dropped += 1

# ---------------------------------------------------------------- clone references for generated lines
def fam_of(pack): return 'speakstone' if pack.startswith('speakstone') else pack
own = collections.defaultdict(list)    # (npc, family) -> reused rows
for r in out:
    if r['action'] == 'reuse': own[(r['npc_id'], fam_of(r['source_pack']))].append(r)
def best_own(npc, f):
    xs = own.get((npc, f))
    if not xs: return None
    clean = lambda r: 'near_97' not in r['match_tier']
    return max(xs, key=lambda r: (r['kind'] == 'accept', clean(r), r['words']))
rep_mt = {}
for r in out:
    if r['action'] == 'reuse' and r['source_pack'] == 'mrthinger' and r['race'] != 'unknown':
        k = (r['race'], r['sex']); cur = rep_mt.get(k)
        if r['kind'] == 'accept' and 'exact' in r['match_tier'] and (cur is None or r['words'] > cur['words']): rep_mt[k] = r

def clone_ref(r):
    if r.get('asr_ref'): return r['asr_ref']
    order = r['order'] if r['order'] and r['order'] != ['ours'] else []
    for f in order:
        b = best_own(r['npc_id'], f)
        if b: return f"{b['source_pack']}:{b['file_in_pack']}"
    if r['family'].startswith('speakstone') and r['race'].startswith('ss:'):
        return f"speakstone:{r['race'][3:]}{r['sex'][0].upper()}"
    if r['family'] == 'ours' or (not order and r['race'] != 'unknown'):
        return f"design:{race_key(r['race'], r['sex'])}"
    for f in order:
        if f == 'speakstone' and r['race'] in RACE_CODE:
            return f"speakstone:{RACE_CODE[r['race']]}{r['sex'][0].upper()}"
        if f == 'spoken':
            # 'model-N' voices are Spoken's per-model voices, which it never recorded ("no-voice") -- skip them
            v = [x for x, _ in (npc_voice.get(r['npc_id']) or collections.Counter()).most_common() if not x.startswith('model-')]
            if v: return 'spoken:' + v[0]
            rv = race_voice.get((CORPUS_RACE.get(r['race']), r['sex']))
            if rv: return 'spoken:' + rv.most_common(1)[0][0]
        if f == 'mrthinger' and (r['race'], r['sex']) in rep_mt:
            return 'mrthinger:' + rep_mt[(r['race'], r['sex'])]['file_in_pack']
    if r['npc_id'].startswith(('go:', 'item:')): return 'design:narrator'
    return f"design:{race_key(r['race'], r['sex'])}" if r['race'] != 'unknown' else 'design:unknown'

for r in out:
    if r['action'] == 'generate': r['clone_ref'] = clone_ref(r)

# v3: characters with their own voice in the client (game_voices/index.json, tools/game_voices.py) speak every
# line in it -- pack clips of them are dropped so Thrall sounds like Thrall in quest text and in the world.
GAME_MIN = 3
game_ref = {}
if os.path.exists('game_voices/index.json'):
    for name, c in json.load(open('game_voices/index.json')).items():
        dl = [x for x in c['clips'] if x['kind'] == 'line' and x['dur']]
        if len(dl) < GAME_MIN: continue
        ref = max(dl, key=lambda x: (bool(x['text']) and 5 <= x['dur'] <= 15, bool(x['text']), -abs(x['dur'] - 10)))
        for n in c['npcs']: game_ref[n] = ref['wav']
# a reference chosen by ear wins over the pick above (game_ref_override.json, by character: Thrall, 2026-10-30)
GAME_OVERRIDE = {k: v for k, v in (json.load(open('game_ref_override.json')).items() if os.path.exists('game_ref_override.json') else []) if k != '_note'}
if os.path.exists('game_voices/index.json'):
    for name, c in json.load(open('game_voices/index.json')).items():
        if name in GAME_OVERRIDE:
            for n in c['npcs']: game_ref[n] = GAME_OVERRIDE[name]
for r in out:
    if r['npc_id'] in game_ref:
        r.update(action='generate', source_pack='', file_in_pack='', cz=0, tempo='',
                 family='game', match_tier='game_voice', clone_ref='game:' + game_ref[r['npc_id']])

# v3 (2026-10-11): age outranks the packs. A child or elder in the chatter profiles (npc_profiles.tsv, exported from
# an NPC profile table) gets a voice designed from that profile instead of a pack's stock adult voice -- Spoken gave
# Billy Maclure its standard adult man and "Auntie" Bernice the same voice as young Maybell. Game voices still win.
AGE = {}
if os.path.exists('npc_profiles.tsv'):
    for p in csv.DictReader(open('npc_profiles.tsv'), delimiter='\t'):
        try: a = json.loads(p['persona'].replace('\\n', ' ')).get('age')
        except ValueError: continue
        if a in ('child', 'elder') and p['spawn_guid'] in ('', 'NULL'): AGE[p['entry']] = a
for e, f in (json.load(open('profile_fixes.json')).items() if os.path.exists('profile_fixes.json') else []):
    if e != '_note' and f.get('age') not in (None, 'child', 'elder'): AGE.pop(e, None)
FIXES = {e: f for e, f in (json.load(open('profile_fixes.json')).items() if os.path.exists('profile_fixes.json') else []) if e != '_note'}
for r in out:                                   # sex the model data does not give (dryads, a whelp)
    if r['npc_id'] in FIXES and FIXES[r['npc_id']].get('sex') and r['sex'] not in ('male', 'female'):
        r['sex'] = FIXES[r['npc_id']]['sex']
aged = 0
for r in out:
    if r['npc_id'] in AGE and r['family'] != 'game':
        r.update(action='generate', source_pack='', file_in_pack='', cz=0, tempo='', family='ours:' + AGE[r['npc_id']],
                 match_tier='age_' + AGE[r['npc_id']], clone_ref=f"design:{race_key(r['race'], r['sex'])}_{AGE[r['npc_id']]}")
        aged += 1
print('age rule: lines moved to designed voices', aged, '| npcs', len({r['npc_id'] for r in out if r['family'].startswith('ours:')}))

COLS = ['questId', 'kind', 'variant', 'npc_id', 'npc_name', 'race', 'sex', 'family', 'action', 'source_pack',
        'match_tier', 'file_in_pack', 'clone_ref', 'tempo', 'words']
with open(os.environ.get('PLAN_OUT', 'plan_v3.csv'), 'w', newline='') as f:   # PLAN_OUT: a scratch run (extract_live)
    w = csv.writer(f); w.writerow(COLS)
    for r in out: w.writerow([r[c] for c in COLS])

# ---------------------------------------------------------------- report
H = lambda wds: round(wds / 150 / 60, 1)
def summary(label, sel):
    c = collections.Counter(); wd = collections.Counter()
    for r in sel: c[r['action']] += 1; wd[r['action']] += r['words']
    return f"{label}: reuse {c['reuse']} ({H(wd['reuse'])} h)  generate {c['generate']} ({wd['generate']} words, {H(wd['generate'])} h)"
print('quests', len(ours), 'clips', len(out), 'words', sum(r['words'] for r in out))
print(summary('TOTAL', out))
for k in KINDS: print(' ', summary(k, [r for r in out if r['kind'] == k]))
print('\n== per family (casting policy)')
for f in sorted({r['family'] for r in out}): print(' ', summary(f, [r for r in out if r['family'] == f]))
print('\n== reused clips per source pack, MB')
pc = collections.Counter(); pb = collections.Counter()
for r in out:
    if r['action'] == 'reuse': pc[r['source_pack']] += 1; pb[r['source_pack']] += r['cz']
for p in sorted(pc): print(f'  {p}: {pc[p]} clips {pb[p] / 1e6:.0f} MB')
print('  download total', round(sum(pb.values()) / 1e6), 'MB')
print('\n== per race/sex')
for k in sorted({(r['race'], r['sex']) for r in out}, key=lambda k: -sum(1 for r in out if (r['race'], r['sex']) == k)):
    print(' ', summary(f'{k[0]} {k[1]}', [r for r in out if (r['race'], r['sex']) == k]))
unv = [r for r in out if r['action'] == 'reuse' and r['match_tier'].startswith('unverified')]
print('\nSpeakStone reused', len(unv), 'words', sum(r['words'] for r in unv), '| ASR verdicts loaded', len(ASR),
      '| reused without a verdict', sum(1 for r in unv if f"{r['questId']}-{r['kind']}-{r['variant']}" not in ASR),
      '| dropped by ASR', asr_dropped)
print('speakstone evaluations', dict(ss_stats), 'pack wps', {p: round(v, 2) for p, v in SS_WPS.items()})
print('mrthinger sec/word', round(MT_MED, 3))
gen = [r for r in out if r['action'] == 'generate']
print('distinct clone refs', len({r['clone_ref'] for r in gen}),
      collections.Counter(r['clone_ref'].split(':')[0] for r in gen))
print('clone ref types (own clip vs family voice vs design)',
      collections.Counter('own' if '/' in r['clone_ref'] else r['clone_ref'].split(':')[0] + '-voice' for r in gen))
print('inferred from SpeakStone codes: npcs', len(inferred), collections.Counter(f'{a} {b}' for a, b in inferred.values()).most_common(30))
print('era-split lock', collections.Counter(r['family'] for r in out if '=' in r['family']))
print('generate reasons (first failure)', collections.Counter((r['family'], r['match_tier'].split(';')[0].split('/')[0].split(':')[-1] if r['match_tier'] else '') for r in gen).most_common(25))
