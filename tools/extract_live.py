"""The quests the realm has that our base-SQL copy does not, from the LIVE realm database (run from data/).

(2026-10-31, the producer: "all realm quests should get voiced too") ac_quests.json was built from AzerothCore's base
SQL (extract_quests.py), which misses the realm's own quests (the realm patch's hunter chains, 6010xx: Ranger Aethon
Emberfall's "Taming the Beast" played a tauren's line in its place) and the holiday quests whose givers only appear
during an event (game_event_creature_quest: the Children's Week orphans, the Lunar Festival...). This adds them:

  ac_quests.json     + {questId: {title, desc, req, off}} for each reachable quest not in it yet. The quests already
                       in it are left alone (471 voiced texts differ from the live ones by later typo fixes; changing
                       them would re-render accepted lines for nothing)
  live_world.json    {table: [rows as the base SQL readers yield them]} -- the rows those quests need from the tables
                       plan_v3.py and direct.py read (quest_template, its addon, the starters and enders -- the event
                       givers as creature starters -- and the givers' creature/gameobject templates and models).
                       sqlrows.live_rows() hands them to every sqltable(); a NULL is '' as in the base reader.

    python3 ../tools/extract_live.py [--dry-run]
"""
import json, os, re, subprocess, sys
import lvconfig as LV

CNF = LV.DB_CNF
BAD = re.compile(r'((?i:UNUSED|DEPRECATED)|^\s*zz|\bTEST\b|\bNYI\b|\bPH\b|<TXT>)')

def query(sql):
    """[{column: value}] -- tabs, newlines and backslashes inside values escaped by the client, undone here"""
    # bytes, decoded here: text=True's universal newlines turn a raw \r inside a value into a line break
    r = subprocess.run(['mariadb', f'--defaults-extra-file={CNF}', '-B', '-e', sql], capture_output=True)
    if r.returncode: sys.exit(f'live database: {r.stderr.decode(errors="replace").strip()[:300]}')
    lines = r.stdout.decode('utf-8', errors='replace').split('\n')
    if not lines or not lines[0]: return []
    cols = lines[0].split('\t')
    un = lambda v: '' if v == 'NULL' else re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t', 'r': '\r', '0': '\0', '\\': '\\'}.get(m.group(1), m.group(1)), v)
    return [dict(zip(cols, map(un, l.split('\t')))) for l in lines[1:] if l]

def ids(xs): return ','.join(str(int(x)) for x in sorted(set(xs), key=int)) or '0'

if __name__ == '__main__':
    ours = json.load(open('ac_quests.json'))
    W = 'acore_world'
    rel = {t: query(f'SELECT id, quest FROM {W}.{t}') for t in
           ('creature_queststarter', 'creature_questender', 'gameobject_queststarter', 'gameobject_questender')}
    # a holiday giver exists only while its event runs: its quests are in game_event_creature_quest, not the starters
    event = query(f'SELECT id, quest FROM {W}.game_event_creature_quest')
    starters = {r['quest'] for r in rel['creature_queststarter'] + rel['gameobject_queststarter'] + event}
    qt = {r['ID']: r for r in query(f'SELECT * FROM {W}.quest_template')}
    req = {r['ID']: r['CompletionText'] for r in query(f'SELECT ID, CompletionText FROM {W}.quest_request_items')}
    off = {r['ID']: r['RewardText'] for r in query(f'SELECT ID, RewardText FROM {W}.quest_offer_reward')}
    new = {}
    for q, r in qt.items():
        if q in ours or BAD.search(r['LogTitle'] or '') or not (r['LogTitle'] or '').strip(): continue
        if q not in starters and r['StartItem'] in ('', '0'): continue
        t = {'title': r['LogTitle'], 'desc': r['QuestDescription'], 'req': req.get(q, ''), 'off': off.get(q, '')}
        if not any((t[k] or '').strip() for k in ('desc', 'req', 'off')): continue
        new[q] = t
    Q = ids(new)
    live = {'quest_template': [qt[q] for q in new],
            'quest_template_addon': query(f'SELECT * FROM {W}.quest_template_addon WHERE ID IN ({Q})')}
    for t, rows in rel.items():
        live[t] = [r for r in rows if r['quest'] in new]
    live['creature_queststarter'] += [r for r in event if r['quest'] in new and r not in live['creature_queststarter']]
    npcs = {r['id'] for t in ('creature_queststarter', 'creature_questender') for r in live[t]}
    gos = {r['id'] for t in ('gameobject_queststarter', 'gameobject_questender') for r in live[t]}
    live['creature_template'] = query(f'SELECT * FROM {W}.creature_template WHERE entry IN ({ids(npcs)})')
    live['creature_template_model'] = query(f'SELECT * FROM {W}.creature_template_model WHERE CreatureID IN ({ids(npcs)})')
    live['gameobject_template'] = query(f'SELECT * FROM {W}.gameobject_template WHERE entry IN ({ids(gos)})')
    realm = sorted((q for q in new if int(q) >= 100000), key=int)
    print(f'{len(new)} quests to add ({len(realm)} the realm\'s own: {", ".join(new[q]["title"] for q in realm[:6])}...), '
          f'{len(npcs)} givers/enders, {len(gos)} objects')
    if '--dry-run' in sys.argv: sys.exit()
    ours.update(new)
    json.dump(dict(sorted(ours.items(), key=lambda kv: int(kv[0]))), open('ac_quests.json', 'w'))
    json.dump(live, open('live_world.json', 'w'))
    print('ac_quests.json and live_world.json written')
