"""Pick and fetch A/B samples: for each race x gender, quests voiced by as many packs as possible."""
import json, re, os, sys, subprocess, collections
from concurrent.futures import ThreadPoolExecutor
OUT = sys.argv[1]
ONLY = set(sys.argv[2].split(',')) if len(sys.argv) > 2 else None   # e.g. human_female,orc_female
SKIP = set(sys.argv[3].split(',')) if len(sys.argv) > 3 else set()  # quest ids already sampled
REQUIRE = os.environ.get('REQUIRE_PACK')                            # e.g. spoken
packs = json.load(open('packs.json'))
q = json.load(open('ac_quests.json')); giver = json.load(open('quest_giver_race.json'))
idx = {'mrthinger': 'AI_VoiceOverData_Vanilla.json', 'spoken': 'sq.json', 'carevass_tbc': 'AI_VoiceOverData_TBC.json',
       'carevass_wotlk': 'AI_VoiceOverData_WoTLK.json', 'chatty_vanilla': 'idx_chatty_vanilla.json',
       'chatty_tbc': 'idx_chatty_tbc.json', 'chatty_wotlk': 'idx_chatty_wotlk.json',
       'speakstone_tbc': 'idx_speakstone_tbc.json', 'speakstone_wotlk': 'idx_speakstone_wotlk.json'}
pat = {'mrthinger': r'AI_VoiceOverData_Vanilla/generated/sounds/quests/(?:[mf]-)?(\d+)-accept\.mp3$',
       'spoken': r'SpokenQuestsAudio\w+/generated/sounds/quests/(?:[mf]-)?(\d+)-accept\.ogg$',
       'carevass_tbc': r'AI_VoiceOverData_TBC/generated/sounds/quests/(?:[mf]-)?(\d+)-accept\.mp3$',
       'carevass_wotlk': r'AI_VoiceOverData_WoTLK/generated/sounds/quests/(?:[mf]-)?(\d+)-accept\.mp3$',
       'chatty_vanilla': r'/voiceovers/(\d+)_Desc\.ogg$', 'chatty_tbc': r'/voiceovers/(\d+)_Desc\.ogg$',
       'chatty_wotlk': r'/voiceovers/(\d+)_Desc\.ogg$',
       'speakstone_tbc': r'/Sounds/(\d+)_description\.ogg$', 'speakstone_wotlk': r'/Sounds/(\d+)_description\.ogg$'}
have = collections.defaultdict(dict)        # qid -> pack -> filename
for p, f in idx.items():
    for name in json.load(open(f)):
        m = re.search(pat[p], name)
        if m and m.group(1) not in have or (m and p not in have[m.group(1)]):
            have[m.group(1)][p] = name
fam = lambda p: p.split('_')[0]
sys.path.insert(0, '../tools'); from sqlrows import rows
import lvconfig as LV
starters = collections.defaultdict(list)    # single-giver quests only: a pack voices ONE of several givers
for r in rows(f'{LV.AC_SQL}/creature_queststarter.sql'):
    starters[r[1]].append(r[0])
RACES = ['Human', 'Dwarf', 'Gnome', 'Night Elf', 'Draenei', 'Orc', 'Troll', 'Tauren', 'Undead', 'Blood Elf', 'Goblin']
jobs, index = [], []
for race in RACES:
    for sex in ('male', 'female'):
        folder = f"{race.lower().replace(' ', '_')}_{sex}"
        if ONLY and folder not in ONLY:
            continue
        cands = []
        for qid, g in giver.items():
            if qid in SKIP or len(starters.get(qid, ())) != 1:
                continue
            if REQUIRE and REQUIRE not in have.get(qid, {}):
                continue
            if g['race'] != race or g['sex'] != sex or qid not in have or qid not in q:
                continue
            words = len(q[qid]['desc'].split())
            fams = {fam(p) for p in have[qid]}
            cands.append((-len(fams), abs(words - 70), qid))
        cands.sort()
        chosen, seen_npc = [], set()
        for _, _, qid in cands:
            if giver[qid]['npc'] in seen_npc:
                continue
            chosen.append(qid); seen_npc.add(giver[qid]['npc'])
            if len(chosen) == 2:
                break
        for qid in chosen:
            slug = re.sub(r'[^a-z0-9]+', '_', q[qid]['title'].lower()).strip('_')[:40]
            folder = f"{race.lower().replace(' ', '_')}_{sex}"
            index.append(f"{folder}/{qid}_{slug}: {giver[qid]['name']} -- packs: {', '.join(sorted(have[qid]))}")
            for p, name in have[qid].items():
                ext = name.rsplit('.', 1)[1]
                jobs.append((packs[p], idx[p], name, f"{OUT}/{folder}/{qid}_{slug}__{p}.{ext}"))
def get(j):
    os.makedirs(os.path.dirname(j[3]), exist_ok=True)
    subprocess.run([sys.executable, '../tools/zget.py', *j], check=False)
with ThreadPoolExecutor(6) as ex:
    list(ex.map(get, jobs))
open(f"{OUT}/INDEX.txt", 'a').write("\n".join(index) + "\n")
print(len(jobs), 'clips;', len(index), 'quests'); print("\n".join(index))
