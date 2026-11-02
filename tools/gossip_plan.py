"""The quest givers' own words before any quest (2026-10-29, the producer: "We don't voice any of the chat text" --
Magistrix Erona's "Ever since the destruction of the Sunwell..." before she offers a quest). What a quest giver says
when you talk to them: the gossip window's text (gossip_menu -> npc_text, every text its conditions can show and every
random slot) and the quest-list greeting (quest_greeting). Submenus ("Tell me about...") and NPCs who give no quest
are not voiced (the producer's scope).

Run from data/:  python3 ../tools/gossip_plan.py
-> gossip.json   {"g<npc>t<npc_text id>s<slot>" | "g<npc>q": {title, gossip, npc, zone, src, snippet}} -- direct.py lays
                 these over its quest table as pseudo-quests whose one line is kind 'gossip'
-> plan_v3.csv   its g-rows replaced: one per line, the speaker's own quest row copied so the line is cast exactly
                 as that speaker's quests are (same voice, morph, pace), with no pack file of its own
Re-run it after plan_v3.py rewrites the plan (that drops the g-rows). The live world database is the source: what
the realm actually shows.
"""
import csv, json, os, re, subprocess, sys
import lvconfig as LV
CNF = LV.DB_CNF
GPAT = re.compile(r'\$[Gg]\s*([^:;]+?)\s*:\s*([^:;]+?)\s*;')          # as plan_v3.py (which runs the plan on import)

def spoken_words(t):                                                   # as plan_v3.py
    t = re.sub(r'\$[Bb]', ' ', t)
    m = re.fullmatch(r'\s*<\s*(.*?)\s*>\s*', t, re.S)
    t = m.group(1) if m else re.sub(r'<[^>]*>', ' ', t)
    t = re.sub(r'\$[NnCcRr]', 'adventurer', t)
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", t))

def query(sql):
    """rows of strings; select text columns as HEX(...): batch output leaves some control characters unescaped, and
    Caz Twosprocket's text split his row in three"""
    out = subprocess.run(['mariadb', f'--defaults-extra-file={CNF}', 'acore_world', '-B', '-N', '-e', sql],
                         capture_output=True, text=True, check=True).stdout
    return [l.split('\t') for l in out.split('\n') if l]

def unhex(x): return bytes.fromhex(x).decode('utf-8', 'replace') if x and x != 'NULL' else ''

def speakable(t):
    """words the voice would say: not a lone name ("$N!") or a stage direction ("<Erona eyes you.>")"""
    return spoken_words(re.sub(r'<[^>]*>', ' ', t)) > 0 and re.search(r'[A-Za-z]{2}', re.sub(r'\$\w', '', t))

def snippet(t, others):
    """the longest run of the text the client shows verbatim -- no placeholder ($N, $C, $R, $G..;), no line break --
    that none of the speaker's other texts contains: the add-on finds the line by it in GetGossipText()"""
    runs = sorted((s.strip() for s in re.split(r'\$[Gg][^;]*;|\$[A-Za-z]|\r|\n', t)), key=len, reverse=True)
    for s in runs:
        s = s[:80].strip()
        if len(s) >= 8 and not any(s in o for o in others): return s
    return None

if __name__ == '__main__':
    plan = [r for r in csv.DictReader(open('plan_v3.csv')) if not r['questId'].startswith('g')]
    cols = list(plan[0].keys())
    voice = {}                                  # npc -> the plan row its quests are cast from (an offer, if any)
    for r in plan:
        if r['npc_id'].isdigit() and (r['npc_id'] not in voice or r['kind'] == 'accept' and voice[r['npc_id']]['kind'] != 'accept'):
            voice[r['npc_id']] = r
    ids = ','.join(voice)
    texts = {}                                  # npc -> [(qid, text, src)]
    for npc, menu, tid, *slots in query(
            'SELECT ct.entry, gm.MenuID, nt.ID, ' + ', '.join(f'HEX(nt.text{i}_0), HEX(nt.text{i}_1)' for i in range(8)) +
            f' FROM creature_template ct JOIN gossip_menu gm ON gm.MenuID = ct.gossip_menu_id JOIN npc_text nt ON nt.ID = gm.TextID'
            f' WHERE ct.entry IN ({ids}) ORDER BY ct.entry, nt.ID'):
        fem = voice[npc]['sex'] == 'female'
        for i in range(8):
            m, f = (unhex(x) for x in slots[2 * i:2 * i + 2])
            t = (f or m) if fem else (m or f)      # npc_text: text_0 a male speaker's words, text_1 a female's
            if t: texts.setdefault(npc, []).append((f'g{npc}t{tid}s{i}', t, f'gossip_menu {menu}, npc_text {tid} slot {i}'))
    for npc, t in query(f'SELECT ID, HEX(Greeting) FROM quest_greeting WHERE Type = 0 AND ID IN ({ids})'):
        t = unhex(t)
        if t: texts.setdefault(npc, []).append((f'g{npc}q', t, 'quest_greeting'))

    zone = dict(query(f'SELECT id, MIN(zoneId) FROM creature WHERE id IN ({ids}) GROUP BY id'))    # for the director
    gossip, rows, skipped = {}, [], {'unspeakable': 0, 'repeat': 0, 'no snippet': 0}
    for npc, ts in texts.items():
        seen = set(); ts = [x for x in ts if not (x[1] in seen or seen.add(x[1]))]
        skipped['repeat'] += len(texts[npc]) - len(ts)
        for qid, t, src in ts:
            if not speakable(t): skipped['unspeakable'] += 1; continue
            snip = snippet(t, [o for _, o, _ in ts if o != t])
            if not snip: skipped['no snippet'] += 1; continue
            gossip[qid] = dict(title=voice[npc]['npc_name'], gossip=t.replace('\r', ''), npc=npc, zone=zone.get(npc, '0'), src=src, snippet=snip)
            base = voice[npc]
            for v in (['m', 'f'] if GPAT.search(t) else ['']):
                rows.append(dict(base, questId=qid, kind='gossip', variant=v, source_pack='', match_tier='', file_in_pack='',
                                 words=str(spoken_words(GPAT.sub(r'\2' if v == 'f' else r'\1', t)))))
    # GOSSIP_OUT / PLAN_OUT: a scratch run whose NEW lines are merged by hand (2026-10-31, the realm's own quest givers)
    json.dump(gossip, open(os.environ.get('GOSSIP_OUT', 'gossip.json'), 'w'), indent=1, ensure_ascii=False)
    with open(os.environ.get('PLAN_OUT', 'plan_v3.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(plan + rows)
    print(f'{len(gossip)} texts from {len({g["npc"] for g in gossip.values()})} quest givers -> {len(rows)} lines, '
          f'{sum(int(r["words"]) for r in rows)} words; skipped {skipped}')
