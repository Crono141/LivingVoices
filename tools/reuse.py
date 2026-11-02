"""Decide which existing AI quest VO clips can be reused for our AzerothCore quest text."""
import json, gzip, re, collections, difflib, csv, sys, statistics
sys.path.insert(0, '.')
from luaload import load_table

SP = '.'  # run from data/
ours = json.load(open('ac_quests.json'))
KINDS = {'accept': 'desc', 'progress': 'req', 'complete': 'off'}
GPAT = re.compile(r'\$[Gg]\s*([^:;]+?)\s*:\s*([^:;]+?)\s*;')

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

def ws(t):
    return re.sub(r'\s+', ' ', t.replace('\r', ' ')).strip()

def loose(t):
    t = re.sub(r'\$[Bb]', ' ', t).lower()
    t = re.sub(r"[^a-z0-9$ ]+", ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def ratio(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < 0.97 or sm.quick_ratio() < 0.97: return sm.quick_ratio()
    return sm.ratio()

def compare(src, our):
    """-> tier for full-text comparison."""
    if src is None: return None, None
    if ws(src) == ws(our): return 'exact', 1.0
    a, b = loose(src), loose(our)
    if a == b: return 'near_punct', 1.0
    r = ratio(a, b)
    return ('near_97' if r >= 0.97 else 'differs'), r

# our clip universe
our_clips = {}  # (qid, kind, variant) -> (text, words)
for qid, q in ours.items():
    for kind, col in KINDS.items():
        t = q.get(col) or ''
        if not t.strip() or t.strip() == 'NULL': continue
        vs = ['m', 'f'] if GPAT.search(t) else ['']
        for v in vs:
            our_clips[(int(qid), kind, v)] = (t, spoken_words(variant_text(t, v)))
print('our clips', len(our_clips), 'words', sum(w for _, w in our_clips.values()))
print('raw words desc+req+off', sum(len((q.get(c) or '').split()) for q in ours.values() for c in KINDS.values()),
      'excluding NULL', sum(len((q.get(c) or '').split()) for q in ours.values() for c in KINDS.values() if (q.get(c) or '').strip() != 'NULL'))

# pack clip inventories from zip central directories
NAME = re.compile(r'^(?:([mf])-)?(\d+)-(accept|progress|complete)\.(mp3|ogg)$')
zips = {'Vanilla': 'AI_VoiceOverData_Vanilla.json', 'TBC': 'AI_VoiceOverData_TBC.json',
        'WoTLK': 'AI_VoiceOverData_WoTLK.json', 'Spoken': 'sq.json'}
packmod = {'AI_VoiceOverData_Vanilla': 'mrthinger', 'AI_VoiceOverData_VanillaExtra': 'carevass_VanillaExtra',
           'AI_VoiceOverData_TBC': 'carevass_TBC', 'AI_VoiceOverData_WoTLK': 'carevass_WoTLK'}
clips = collections.defaultdict(dict)   # pack -> key -> (zip path, compressed bytes)
for z, f in zips.items():
    for n, (m, cz, u, o) in json.load(open(f'{SP}/{f}')).items():
        if '/sounds/quests/' not in n: continue
        mm = NAME.match(n.rsplit('/', 1)[1])
        if not mm: continue
        mod = n.split('/')[0]
        pack = packmod.get(mod, 'spoken')
        key = (int(mm.group(2)), mm.group(3), mm.group(1) or '')
        clips[pack].setdefault(key, (n, cz))
for p in clips: print(p, len(clips[p]))

# lookup tables: id -> titles, fingerprints
def lookup_index(path, nfp):
    t = load_table(path)
    idx = collections.defaultdict(lambda: {'titles': set(), 'fps': set()})
    def walk(src, title, node):
        if isinstance(node, int):
            idx[(node, src)]['titles'].add(title); return
        for k, v in node.items():
            if isinstance(v, int) and len(k.split()) > 6:   # a fingerprint key
                idx[(v, src)]['fps'].add(k); idx[(v, src)]['titles'].add(title)
            else:
                walk(src, title, v)
    for src, titles in t.items():
        for title, node in titles.items():
            walk(src, title, node)
    return idx
LK = {'carevass_TBC': lookup_index('lookups/tbc_q.lua', 25), 'carevass_WoTLK': lookup_index('lookups/w_q.lua', 25),
      'carevass_VanillaExtra': lookup_index('lookups/vx_q.lua', 25), 'mrthinger': lookup_index('lookups/v_q.lua', 15)}
NFP = {'carevass_TBC': 25, 'carevass_WoTLK': 25, 'carevass_VanillaExtra': 25, 'mrthinger': 15}

def fingerprint(t, n):
    w = re.findall(r'\S+', t)
    s = ' '.join(w[:n]) + ' ' + ' '.join(w[-n:])
    s = s.replace('"', "'").replace('\r', ' ').replace('\n', ' ')
    return ws(re.sub(r'(\$[Bb])+', ' ', s))

# sound lengths
SL = {}
for p, f in [('carevass_TBC', 'sl_TBC'), ('carevass_WoTLK', 'sl_WoTLK'), ('carevass_VanillaExtra', 'sl_VanillaExtra'), ('mrthinger', 'sl_Vanilla')]:
    SL[p] = load_table(f'lookups/{f}.lua')

# carevass new_entries (full text) and text corrections
import openpyxl
NEW = {}
wb = openpyxl.load_workbook('cv/new_entries.xlsx', read_only=True)
rows = list(wb.worksheets[0].iter_rows(values_only=True)); hdr = rows[0]
for r in rows[1:]:
    d = dict(zip(hdr, r))
    if d['quest'] and d['source'] in KINDS: NEW.setdefault((int(d['quest']), d['source']), []).append(d['original_text'] or d['text'])
CORR = set()
wb = openpyxl.load_workbook('cv/corrections.xlsx', read_only=True)
rows = list(wb['quest'].iter_rows(values_only=True)); hdr = rows[0]
for r in rows[1:]:
    d = dict(zip(hdr, r))
    if d['quest'] and d['cleanedText']:
        for k in ([d['source']] if d['source'] else list(KINDS)): CORR.add((int(d['quest']), k))

# Spoken corpus: exact source text per clip
corpus = json.load(gzip.open(f'{SP}/spoken_corpus.json.gz'))
CT = {}
for l in corpus['lines']:
    if l['source'] in KINDS and l.get('questId'):
        CT.setdefault((l['questId'], l['source']), l['originalText'])

PREF = ['carevass_VanillaExtra', 'carevass_TBC', 'carevass_WoTLK', 'spoken', 'mrthinger']
evals = collections.defaultdict(dict)  # our key -> pack -> (tier, detail)
for key, (text, words) in our_clips.items():
    qid, kind, v = key
    title = ours[str(qid)]['title']
    for pack in PREF:
        if key not in clips[pack]: continue
        fn, cz = clips[pack][key]
        dur = None
        if pack == 'spoken':
            tier, r = compare(CT.get((qid, kind)), text)
            if tier is None: tier = 'no_source_text'
        else:
            li = LK[pack].get((qid, kind))
            dur = SL[pack].get(fn.rsplit('/', 1)[1].rsplit('.', 1)[0])
            tier = None; r = None
            if pack.startswith('carevass') and (qid, kind) in NEW:
                RANK = {'exact': 0, 'near_punct': 1, 'near_97': 2, 'differs': 3}
                tier, r = min((compare(x, text) for x in NEW[(qid, kind)]), key=lambda tr: (RANK[tr[0]], -tr[1]))
                tier = 'newentry_' + tier
            elif li and li['fps']:
                ofp = fingerprint(text, NFP[pack])
                fps = {ws(x) for x in li['fps']}
                if ofp in fps: tier = 'fp_exact'
                else:
                    r = max(ratio(loose(x), loose(ofp)) for x in fps)
                    tier = ('fp_near_punct' if r == 1.0 else 'fp_near_97') if r >= 0.97 else 'fp_differs'
            if tier is None and pack == 'mrthinger':
                t2, r = compare(CT.get((qid, kind)), text)
                tier = 'proxy_' + t2 if t2 else None
            if tier is None:
                if li is None: tier = 'id_only_nolookup'
                elif ws(title.replace('"', "'")) in {ws(x) for x in li['titles']}: tier = 'id_title'
                else: tier = 'id_title_differs'
            if pack.startswith('carevass') and (qid, kind) in CORR: tier += '+corrected'
        evals[key][pack] = (tier, r, fn, cz, dur, words)

# duration calibration: seconds per word on verified clips
spw = collections.defaultdict(list)
for key, d in evals.items():
    for pack, (tier, r, fn, cz, dur, words) in d.items():
        if dur and words >= 15 and 'exact' in tier:
            spw[pack].append(dur / words)
MED = {p: statistics.median(v) for p, v in spw.items()}
print('sec/word medians', {p: round(v, 3) for p, v in MED.items()}, {p: len(v) for p, v in spw.items()})

def dur_ok(pack, dur, words):
    if not dur or pack not in MED: return True
    exp = MED[pack] * words + 1.0
    return 0.5 * exp <= dur <= 2.0 * exp

GOOD = ('exact', 'near', 'id_title')
def acceptable(pack, tier, dur, words):
    base = tier.split('+')[0]
    if 'differs' in base or base == 'no_source_text': return False
    if base == 'id_only_nolookup' and not pack.startswith('carevass'): return False
    return dur_ok(pack, dur, words)

plan, togen = [], []
stats = collections.Counter(); rejected = collections.Counter(); flagged = []
for key in sorted(our_clips):
    d = evals.get(key, {})
    choice = None
    for pack in PREF:
        if pack in d:
            tier, r, fn, cz, dur, words = d[pack]
            if acceptable(pack, tier, dur, words):
                if choice is None: choice = (pack, tier, fn, cz)
            else:
                rejected[(pack, tier if dur_ok(pack, dur, words) else tier + '/bad_duration')] += 1
                flagged.append((key, pack, tier, r, dur, words))
    qid, kind, v = key
    if choice:
        plan.append((qid, kind, v, choice[0], choice[1], choice[2], choice[3]))
        stats[(kind, choice[0], choice[1])] += 1
    else:
        togen.append((qid, kind, v, our_clips[key][1]))

with open('reuse_plan.csv', 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['questId', 'kind', 'variant', 'source_pack', 'match_tier', 'file_name_in_pack'])
    for p in plan: w.writerow(p[:6])
with open('to_generate.csv', 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['questId', 'kind', 'variant', 'words'])
    w.writerows(togen)

json.dump({'flagged': [[list(k), *rest] for k, *rest in flagged]}, open('reuse_flagged.json', 'w'))
print('\n== chosen per kind/pack/tier')
for k in sorted(stats): print(' ', k, stats[k])
print('\n== rejected candidates')
for k in sorted(rejected): print(' ', k, rejected[k])
tot = collections.Counter(); totw = collections.Counter(); rem = collections.Counter(); remw = collections.Counter()
for key, (t, w) in our_clips.items(): tot[key[1]] += 1; totw[key[1]] += w
for q, k, v, w in togen: rem[k] += 1; remw[k] += w
print('\n== per kind: total clips, reused, remaining, remaining words')
for k in KINDS: print(' ', k, tot[k], tot[k] - rem[k], rem[k], remw[k], 'of', totw[k])
W = sum(remw.values())
print('remaining words', W, 'hours@150wpm', round(W / 150 / 60, 1), 'of total', sum(totw.values()), round(sum(totw.values()) / 9000, 1))
need = collections.Counter(); needb = collections.Counter()
for p in plan:
    need[p[3]] += 1; needb[p[3]] += p[6]
print('clips/bytes needed per pack', {k: (need[k], round(needb[k] / 1e6)) for k in need})
# raw availability per pack regardless of selection
avail = collections.Counter()
for key, d in evals.items():
    for pack, (tier, *_r) in d.items():
        avail[(key[1], pack, tier)] += 1
print('\n== all candidate evaluations (kind, pack, tier)')
for k in sorted(avail): print(' ', k, avail[k])

if __name__ == '__main__' and len(sys.argv) > 1:
    import random; random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    want = sys.argv[1]  # pack:tierprefix
    pk, tp = want.split(':')
    xs = [(k, d[pk]) for k, d in evals.items() if pk in d and d[pk][0].startswith(tp)]
    print(len(xs))
    for k, (tier, r, fn, cz, dur, words) in random.sample(xs, min(4, len(xs))):
        qid, kind, v = k
        print('----', k, tier, r, 'dur', dur, 'words', words, 'exp', round(MED.get(pk, 0) * words + 1, 1) if pk in MED else '')
        print('OURS:', ws(our_clips[k][0])[:400])
        src = CT.get((qid, kind)) if pk in ('spoken', 'mrthinger') else (NEW.get((qid, kind)) or [None])[0]
        if src: print('SRC :', ws(src)[:400])
        li = LK.get(pk, {}).get((qid, kind))
        if li: print('LK  :', li['titles'], list(li['fps'])[:1])
        else:
            hits = [(kk, vv['titles']) for kk, vv in LK.get(pk, {}).items() if kk[0] == qid]
            print('LK other kinds:', hits, 'title ours', ours[str(qid)]['title'])
