"""Which quest-giver NPCs have their own voice in the 3.3.5 client (boss/story lines, greetings)?

Run from data/:  PYTHONPATH=../tools ../.venv/bin/python ../tools/npc_voices.py
Reads plan_v3.csv, creature_text + broadcast_text (Sound / SoundEntriesId), CreatureDisplayInfo -> NPCSounds,
SoundEntries.dbc, and the client's MPQ listfiles. Writes npc_voices.json:
  npc_id -> {name, lines: [{file, mpq, text, src}], greet: [{file, mpq}]}
Greeting sets shared by many display ids (the generic race voices) are dropped: only NPC-specific ones count.
"""
import csv, collections, json, re, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
from sqlrows import rows, live_rows
import mpyq

SQL = f'{LV.AC_SQL}/'
CLIENT = f'{LV.WOW_DATA}/'
MPQS = ['enUS/speech-enUS.MPQ', 'enUS/expansion-speech-enUS.MPQ', 'enUS/lichking-speech-enUS.MPQ',
        'enUS/patch-enUS.MPQ', 'enUS/patch-enUS-2.MPQ', 'enUS/patch-enUS-3.MPQ',
        'common.MPQ', 'common-2.MPQ', 'expansion.MPQ', 'lichking.MPQ', 'patch.MPQ', 'patch-2.MPQ', 'patch-3.MPQ']

def sqltable(name):
    txt = open(SQL + name + '.sql', encoding='utf-8', errors='replace').read()
    body = txt[txt.index('CREATE TABLE'):]; body = body[:body.index(') ENGINE')]
    c = [m.group(1) for m in re.finditer(r'^\s+`(\w+)`', body, re.M)]
    for r in rows(SQL + name + '.sql', null=''):
        yield dict(zip(c, r))
    yield from live_rows(name)                  # the realm's own and the holiday quests (extract_live.py)

def dbc(path):
    b = open(path, 'rb').read(); _, n, fc, rs, ss = struct.unpack('<4s4I', b[:20])
    strs = b[20 + n * rs:]
    s = lambda o: strs[o:strs.index(b'\0', o)].decode('utf-8', 'replace')
    return [struct.unpack(f'<{fc}I', b[20 + i * rs:20 + (i + 1) * rs]) for i in range(n)], s

# ---- client file index: lower path -> mpq (later archives patch earlier ones)
where = {}
for m in MPQS:
    a = mpyq.MPQArchive(CLIENT + m, listfile=True)
    for f in a.files or []:
        f = f.decode('utf-8', 'replace')
        # speech + locale patch archives only (patch VO lands in patch-enUS*): the others hold creature noises (roars, attacks) and music
        if ('speech' in m or 'patch-enUS' in m) and f.lower().endswith(('.wav', '.mp3', '.ogg')): where[f.lower()] = (m, f)

# ---- SoundEntries: id -> [paths]
se_rows, s = dbc('dbc/SoundEntries.dbc')
sound = {}
for r in se_rows:
    base = s(r[23]).rstrip('\\')
    files = [s(r[3 + i]) for i in range(10) if r[3 + i]]
    sound[r[0]] = [(base + '\\' + f) if base else f for f in files if s(r[3 + 0]) is not None and f]

def resolve(sid):
    out = []
    for p in sound.get(sid, []):
        w = where.get(p.lower())
        if w: out.append({'file': w[1], 'mpq': w[0]})
    return out

# ---- NPCSounds via display: only sets used by few displays count as NPC-specific
npcs_rows, _ = dbc('dbc/NPCSounds.dbc')
npcsound = {r[0]: r[1:5] for r in npcs_rows}
cdi_rows, _ = dbc('dbc/CreatureDisplayInfo.dbc')
disp_npcsound = {r[0]: r[12] for r in cdi_rows}
models = collections.defaultdict(list)
for r in sqltable('creature_template_model'):
    models[int(r['CreatureID'])].append(int(r['CreatureDisplayID']))
set_users = collections.Counter()
for cid, ds in models.items():
    for v in {disp_npcsound.get(d, 0) for d in ds}:
        if v: set_users[v] += 1

# ---- plan: which NPCs speak, how many generated lines/words each
plan = list(csv.DictReader(open('plan_v3.csv')))
gen = collections.Counter(); genw = collections.Counter(); meta = {}
for r in plan:
    if r['npc_id'].isdigit():
        meta[r['npc_id']] = (r['npc_name'], r['race'], r['sex'], r['family'])
        if r['action'] == 'generate': gen[r['npc_id']] += 1; genw[r['npc_id']] += int(r['words'])

bt = {}
for r in sqltable('broadcast_text'):
    if r['SoundEntriesId'] not in ('', '0'): bt[r['ID']] = (int(r['SoundEntriesId']), r['MaleText'] or r['FemaleText'])

# same character under another entry (boss / event / phase versions): match by name
cnames = {r['entry']: r['name'] for r in sqltable('creature_template')}
norm = lambda n: re.sub(r'[^a-z]', '', n.lower())
by_name = collections.defaultdict(list)
for e, n in cnames.items(): by_name[norm(n)].append(e)
GENERIC = {'', 'image', 'spirit', 'ghost'}
alias = collections.defaultdict(set)          # creature entry -> quest-giver ids it voices
for c, (n, *_rest) in meta.items():
    if norm(n) in GENERIC or len(norm(n)) < 4: continue
    for e in by_name[norm(n)]: alias[e].add(c)

found = collections.defaultdict(lambda: {'lines': [], 'greet': []})
seen = collections.defaultdict(set)

def add_text(cid, r):
    for sid, text, src in ((int(r['Sound'] or 0), r['Text'], 'creature_text' if r['CreatureID'] == cid else 'creature_text:' + r['CreatureID']),
                           (*bt.get(r['BroadcastTextId'], (0, '')), 'broadcast_text')):
        for f in resolve(sid) if sid else []:
            if f['file'] in seen[cid]: continue
            seen[cid].add(f['file']); found[cid]['lines'].append(dict(f, text=text, src=src))
for r in sqltable('creature_text'):
    for cid in alias.get(r['CreatureID'], ()):
        add_text(cid, r)

# folder named for the character: Sound\Creature\<Name>\...
folders = collections.defaultdict(list)
for low, (m, f) in where.items():
    parts = f.split('\\')
    if len(parts) >= 4 and parts[1].lower() == 'creature': folders[norm(parts[2])].append((m, f))
for cid, (n, *_rest) in meta.items():
    k = norm(n)
    for cand in (k, re.sub(r'^(lady|lord|king|prince|princess|highlord|archmage|keeper|commander|warchief|high|chief)', '', k)):
        if len(cand) >= 5 and cand in folders:
            for m, f in folders[cand]:
                if f not in seen[cid]: seen[cid].add(f); found[cid]['lines'].append({'file': f, 'mpq': m, 'text': None, 'src': 'folder'})
            break

for cid in meta:
    for v in {disp_npcsound.get(d, 0) for d in models.get(int(cid), [])}:
        if v and v in npcsound and set_users[v] <= 3:
            for sid in npcsound[v]:
                for f in resolve(sid) if sid else []:
                    if f['file'] not in seen[cid]: seen[cid].add(f['file']); found[cid]['greet'].append(f)

out = {c: dict(name=meta[c][0], race=meta[c][1], sex=meta[c][2], family=meta[c][3], generate=gen[c],
               generate_words=genw[c], **found[c]) for c in found if found[c]['lines'] or found[c]['greet']}
json.dump(out, open('npc_voices.json', 'w'), indent=1)

H = lambda w: round(w / 150 / 60, 1)
has = [c for c in out]
print('client voice files indexed', len(where), '| speaking NPCs', len(meta), '| with own voice', len(has),
      '(lines', sum(1 for c in has if out[c]['lines']), 'greet-only', sum(1 for c in has if not out[c]['lines']), ')')
print('generated lines those NPCs cover', sum(gen[c] for c in has), H(sum(genw[c] for c in has)), 'h of',
      sum(gen.values()), H(sum(genw.values())), 'h')
for grp, sel in (('unknown race', lambda c: meta[c][1] == 'unknown'), ('known race', lambda c: meta[c][1] != 'unknown')):
    cs = [c for c in has if sel(c)]
    allc = [c for c in gen if sel(c)]
    print(f'  {grp}: {len(cs)} NPCs with own voice, {sum(gen[c] for c in cs)} of {sum(gen[c] for c in allc)} generated lines')
print('\ntop by generated lines (own voice clips: dialogue / greeting)')
for c in sorted(has, key=lambda c: -gen[c])[:45]:
    o = out[c]; print(f"  {c:>6} {o['name'][:32]:32} {o['race'][:10]:10} {o['family'][:22]:22} gen {gen[c]:3}  clips {len(o['lines']):3}/{len(o['greet'])}")
unk = sorted((c for c in gen if meta[c][1] == 'unknown' and c not in out), key=lambda c: -gen[c])
print('\nunknown-race NPCs with NO own voice (top 25):', [(meta[c][0], gen[c]) for c in unk[:25]])
