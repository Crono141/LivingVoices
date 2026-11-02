"""Regenerate data/ac_quests.json from the AzerothCore base SQL (run from data/).

{questId: {title, desc (QuestDescription = accept), req (quest_request_items.CompletionText = progress),
           off (quest_offer_reward.RewardText = complete)}}, SQL NULL -> "".
Reachable quests only: a creature/gameobject starter or an item that starts it (item_template.startquest
or quest_template.StartItem; --item-starters adds item_template.startquest), and a title that is not UNUSED/DEPRECATED/zz/TEST/NYI/PH.
"""
import json, re, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import lvconfig as LV
from sqlrows import rows

SQL = f'{LV.AC_SQL}/'

def cols(table):
    txt = open(SQL + table + '.sql', encoding='utf-8', errors='replace').read()
    body = txt[txt.index('CREATE TABLE'):]
    body = body[:body.index(') ENGINE')]
    return [m.group(1) for m in re.finditer(r'^\s+`(\w+)`', body, re.M)]

def table(name):
    c = cols(name)
    for r in rows(SQL + name + '.sql', null=''):
        yield dict(zip(c, r))

BAD = re.compile(r'((?i:UNUSED|DEPRECATED)|^\s*zz|\bTEST\b|\bNYI\b|\bPH\b)')
ITEM_STARTERS = '--item-starters' in sys.argv   # also item_template.startquest (18 more quests); off = the old filter

def main(out='ac_quests.json'):
    starters = set()
    for t in ('creature_queststarter', 'gameobject_queststarter'):
        starters |= {r['quest'] for r in table(t)}
    if ITEM_STARTERS:
        starters |= {r['startquest'] for r in table('item_template') if r['startquest'] not in ('', '0')}
    req = {r['ID']: r['CompletionText'] or '' for r in table('quest_request_items')}
    off = {r['ID']: r['RewardText'] or '' for r in table('quest_offer_reward')}
    q = {}
    for r in table('quest_template'):
        qid, title = r['ID'], r['LogTitle'] or ''
        if qid not in starters and r['StartItem'] in ('', '0'):
            continue
        if not title.strip() or BAD.search(title):
            continue
        q[qid] = {'title': title, 'desc': r['QuestDescription'] or '', 'req': req.get(qid, ''), 'off': off.get(qid, '')}
    q = dict(sorted(q.items(), key=lambda kv: int(kv[0])))
    json.dump(q, open(out, 'w'))
    return q

if __name__ == '__main__':
    q = main(next((a for a in sys.argv[1:] if not a.startswith('--')), 'ac_quests.json'))
    print(len(q), 'quests;', sum(v == 'NULL' for x in q.values() for v in x.values()), 'literal NULL texts')
