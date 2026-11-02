"""Build the release: the LivingVoices add-on with every quest line, the DLL, the Wow.exe patcher (exe, and the
Python one), the player's README and the licence notes, zipped for the portal.
Run from data/:   python3 ../client/build_release.py [--partial]
-> client/release/LivingVoices-<version>.zip, staged in release/LivingVoices-<version>/

(1.1.0) The lines ship at 64 kbps (render64/, re-encoded from render/; the producer's blind test heard no difference
down to 48) in one MPQ in the add-on folder, LivingVoices.MPQ ("vo\\<line>.mp3" and "test.mp3" inside), written by
build/mkpack and read back in full by build/test_pack through the DLL's own reader before anything is zipped.
Run client/build.sh first.

Every line is our own render (render/<line>.mp3, the take the speech check or the producer accepted). No community
pack audio ships: the packs give no permission to redistribute (2026-10-29; overnight.KEEP_PACK). A planned line with
no render stops the build unless --partial (then it is listed and left silent in game).
"""
import csv, os, re, shutil, sqlite3, subprocess, sys, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import lvconfig as LV
import direct, overnight, json, hashlib
CLIENT = os.path.dirname(os.path.abspath(__file__))
VERSION = re.search(r'ADDON_VERSION = "([^"]+)"', open(f'{CLIENT}/addon/LivingVoices/LivingVoices.lua').read()).group(1)
OUT = os.path.join(CLIENT, 'release', f'LivingVoices-{VERSION}')
AD = os.path.join(OUT, 'Interface', 'AddOns', 'LivingVoices')

st = dict(sqlite3.connect('overnight.sqlite').execute('SELECT name, status FROM lines'))
vo, titles, gossip, missing, stale, speaker, in_review = set(), {}, {}, [], [], {}, []
for r in csv.DictReader(open('plan_v3.csv')):
    if r['npc_id'] == 'none': continue                  # no speaker: nothing to voice
    nm = overnight.name_of(r)
    if st.get(nm) == 'silent': continue                 # a line with nothing to say aloud
    # (2026-10-31) a line on the review page ships its best take (render/<line>.mp3, the one the page plays first) until
    # the producer decides: a reported line being retaken must not go silent for a week
    if st.get(nm) not in ('done', 'review') or not os.path.exists(f'render/{nm}.mp3'): missing.append((nm, st.get(nm))); continue
    if st.get(nm) == 'review': in_review.append(nm)
    if not os.path.exists(f'render64/{nm}.mp3') or os.path.getmtime(f'render64/{nm}.mp3') < os.path.getmtime(f'render/{nm}.mp3'):
        stale.append(nm)
    vo.add(nm)
    if r['kind'] == 'gossip':          # a quest giver's chat text: found in game by the NPC and a stretch of the text
        g = direct.Q[r['questId']]; gossip.setdefault(int(g['npc']), {})[f"{r['questId']}-gossip"] = g['snippet']
    else:
        # trimmed: four live titles end in a space ("Attack by Air! "); the add-on trims what the client shows too
        titles.setdefault(direct.Q[r['questId']]['title'].strip(), set()).add(int(r['questId']))
        if r['npc_id'].isdigit(): speaker[(r['questId'], r['kind'])] = int(r['npc_id'])
# (2026-10-31) race and class in the voice: a sentence clip (variants.py; rendered and checked like any line, then
# trimmed, paced and padded by splices.py into render64/) ships when its line ships and its take's cuts are known.
# Index.rc[line] = { {sentence, "R"|"C"|"RC", from_ms, to_ms}, ... }: the add-on hands the take and the hearer's clips
# to engine 0.4's PlaySpliced.
VAR = json.load(open('variants.json')) if os.path.exists('variants.json') else {}
SPL = json.load(open('splices.json')) if os.path.exists('splices.json') else {}
rc = {}
for vn, x in VAR.items():
    cut = SPL.get(x['base'], {}).get('cuts', {}).get(str(x['i']))
    if x['base'] not in vo or st.get(vn) not in ('done', 'review') or not cut or not os.path.exists(f'render64/{vn}.mp3'): continue
    if os.path.getmtime(f'render64/{vn}.mp3') < max(os.path.getmtime(f'render/{vn}.mp3'), SPL[x['base']]['mtime']): continue
    vo.add(vn)
    rc.setdefault(x['base'], {})[x['i']] = (x['i'], x['tok'], cut[0], cut[1])
print(f'race/class: {sum(1 for n in vo if "_s" in n)} sentence clips for {len(rc)} lines')

if missing and '--partial' not in sys.argv:
    sys.exit(f'{len(missing)} planned lines are not done yet (e.g. {missing[:5]}); --partial builds without them')

if stale:                                                         # a line re-rendered since the re-encode
    sys.exit(f'{len(stale)} lines have no 64 kbps copy newer than their render (e.g. {stale[:5]}); re-encode them into render64/')

shutil.rmtree(OUT, ignore_errors=True); os.makedirs(AD)
for f in ('LivingVoices.lua', 'LivingVoices.toc'): shutil.copy(f'{CLIENT}/addon/LivingVoices/{f}', AD)
lst = os.path.join(OUT, '..', f'.LivingVoices-{VERSION}.list')
with open(lst, 'w') as f:
    f.write('render64/783-accept.mp3\ttest.mp3\n')                  # /lv test: "Your first task..." (Marshal McBride)
    for nm in sorted(vo): f.write(f'render64/{nm}.mp3\tvo\\{nm}.mp3\n')
# (1.1.1, GitHub releases) the lines in TWO archives, each zip under GitHub's 2 GiB per file: LivingVoices.MPQ and
# LivingVoices.part2.MPQ, split by size in name order. The engine mounts every *.MPQ in the folder; no line is in both,
# and both names sort before LivingVoices.patch.MPQ ('.M' and '.pa'r before '.pa't), so a patch still wins.
PARTS = (('LivingVoices.MPQ', f'{lst}.1'), ('LivingVoices.part2.MPQ', f'{lst}.2'))
rows = [l for l in open(lst)]
sizes = [os.path.getsize(l.split('\t')[0]) for l in rows]
half, run, cut = sum(sizes) / 2, 0, len(rows)
for i, n in enumerate(sizes):
    run += n
    if run >= half: cut = i + 1; break
for (name, part), chunk in zip(PARTS, (rows[:cut], rows[cut:])):
    open(part, 'w').writelines(chunk)
    m = f'{AD}/{name}'
    if subprocess.run([f'{CLIENT}/build/mkpack', m, part]).returncode: sys.exit(f'mkpack failed on {name}; the release was not zipped')
    if subprocess.run([f'{CLIENT}/build/test_pack', part, m]).returncode: sys.exit(f'{name} does not read back; the release was not zipped')
# (1.1.0) the patch archive. release/.LivingVoices-<version>.base.json records every file of the archive as this version
# first shipped (written by the first build of the version); a line re-rendered since goes into LivingVoices.patch.MPQ,
# which the engine mounts after LivingVoices.MPQ (by name: '.p' sorts after '.M') so its lines win. The update zip
# carries it; the full zip carries an EMPTY one under the same name, so a stale patch left in the folder by an earlier
# update can never override a newer full install.
entries = [l.rstrip('\n').split('\t') for l in open(lst)]
sha = {name: hashlib.sha1(open(src, 'rb').read()).hexdigest() for src, name in entries}
basef = os.path.join(CLIENT, 'release', f'.LivingVoices-{VERSION}.base.json')
if not os.path.exists(basef): json.dump(sha, open(basef, 'w'))
base = json.load(open(basef))
changed = [(src, name) for src, name in entries if base.get(name) != sha[name]]
plst, elst = f'{lst}.patch', f'{lst}.empty'
with open(plst, 'w') as f: f.writelines(f'{src}\t{name}\n' for src, name in changed)
open(elst, 'w').close()
patch_full, patch_upd = os.path.join(OUT, '..', '.patch-empty.MPQ'), f'{AD}/LivingVoices.patch.MPQ'
for l_, m_ in ((plst, patch_upd), (elst, patch_full)):
    if subprocess.run([f'{CLIENT}/build/mkpack', m_, l_]).returncode or subprocess.run([f'{CLIENT}/build/test_pack', l_, m_]).returncode:
        sys.exit('the patch MPQ did not build or read back; the release was not zipped')
print(f'patch: {len(changed)} line(s) changed since {VERSION} first shipped: {", ".join(n for _, n in changed[:8])}')
# (1.1.0, the producer: Jesthenis Sunstriker spoke in a draenei's voice, then a woman's; Ranger Aethon Emberfall's
# "Taming the Beast" -- a realm quest with no voice -- in a tauren's) the 3.3.5 client gives add-ons a quest's title,
# not its id, and titles are shared: "Paladin Training" is Aurelon's (draenei, 9287) and Jesthenis's (9676), "Taming
# the Beast" is eighteen hunter quests and the realm's own. Every quest line now carries who speaks it and a stretch of
# its text as the quest window shows it -- from the LIVE realm database (471 voiced texts differ from our copy: later
# typo fixes, trailing spaces), ours only if the database cannot be read. The add-on plays a line only if that stretch
# is on screen, preferring the one the NPC in front of you speaks; a quest none of whose lines match stays silent.
LIVE_SQL = ("SELECT q.ID, REPLACE(REPLACE(q.QuestDescription,'\\r','\\\\r'),'\\n','\\\\n'), "
            "REPLACE(REPLACE(COALESCE(r.CompletionText,''),'\\r','\\\\r'),'\\n','\\\\n'), "
            "REPLACE(REPLACE(COALESCE(o.RewardText,''),'\\r','\\\\r'),'\\n','\\\\n') FROM acore_world.quest_template q "
            "LEFT JOIN acore_world.quest_request_items r ON r.ID=q.ID LEFT JOIN acore_world.quest_offer_reward o ON o.ID=q.ID")
def live_texts():
    r = subprocess.run(['mariadb', f'--defaults-extra-file={LV.DB_CNF}', '-N', '-B', '-e', LIVE_SQL],
                       capture_output=True, text=True, errors='replace')
    if r.returncode: print('  WARNING: the live quest texts could not be read; using our copy:', r.stderr.strip()[:200]); return {}
    un = lambda t: t.replace('\\r', '\r').replace('\\n', '\n')
    return {p[0]: {'accept': un(p[1]), 'progress': un(p[2]), 'complete': un(p[3])}
            for p in (l.split('\t') for l in r.stdout.splitlines()) if len(p) == 4}
LIVE = live_texts()
was = {k: x['was'] for k, x in json.load(open('rewrites.json')).items() if not k.startswith('_')}
def shown(q, kind):
    q = str(q)
    if q in LIVE: return LIVE[q][kind]
    return was.get(f'{q}-{kind}', direct.Q[q][direct.KINDS[kind]] or '')
def verbatim(t, others, width=40):
    """(stretch, unique): the longest run of the text the client shows as written (no $N/$C/$G..;, no line break), cut
    to `width`; one that none of `others` contains if there is one (unique=1: it tells same-titled quests apart), else
    the longest anyway (unique=0: it still proves the window holds this quest's text, but a sibling's may hold it too).
    '' when the text has no run of 8 characters"""
    runs = [x.strip()[:width].strip() for x in sorted(re.split(r'\$[Gg][^;]*;|\$[A-Za-z]|\r|\n', t), key=lambda x: len(x.strip()), reverse=True)]
    runs = [x for x in runs if len(x) >= 8]
    # unique: the first `width`-character window of any run, sliding along it, that no sibling contains -- siblings
    # often share a run's start and part later ("one of the most" / "one of most", 5093 / 5094)
    full = [x.strip() for x in re.split(r'\$[Gg][^;]*;|\$[A-Za-z]|\r|\n', t) if len(x.strip()) >= 8]
    for x in sorted(full, key=len, reverse=True):
        for i in range(0, max(1, len(x) - width + 1), 2):
            w = x[i:i + width].strip()
            if len(w) >= 8 and not any(w in o for o in others): return w, 1
    return (runs[0] if runs else '', 0)
pick = {}
for t, ids in titles.items():
    for kind in ('accept', 'progress', 'complete'):
        have = [q for q in sorted(ids) if f'{q}-{kind}' in vo or f'{q}-{kind}-m' in vo]
        for q in have:
            # unique against the siblings whose text DIFFERS: two quests with the same words are the same line
            pick[f'{q}-{kind}'] = (speaker.get((str(q), kind), 0),
                                   *verbatim(shown(q, kind), [shown(o, kind) for o in have if o != q and shown(o, kind) != shown(q, kind)]))
lua = lambda s: '{' + ', '.join(f'["{x}"] = true' for x in sorted(s)) + '}'
esc = lambda t: t.replace('\\', '\\\\').replace('"', '\\"')
with open(f'{AD}/Index.lua', 'w') as f:
    f.write(f'-- generated by client/build_release.py ({len(vo)} lines)\nLivingVoicesIndex = {{\n')
    f.write(f'  vo = {lua(vo)},\n  title = {{\n')
    for t, ids in sorted(titles.items()): f.write(f'    ["{esc(t)}"] = {{{", ".join(map(str, sorted(ids)))}}},\n')
    f.write('  },\n  pick = {\n')
    for k, (npc, sn, uniq) in sorted(pick.items()): f.write(f'    ["{k}"] = {{{npc}, "{esc(sn)}", {uniq}}},\n')
    f.write('  },\n  rc = {\n')
    for b, ss in sorted(rc.items()):
        f.write(f'    ["{b}"] = {{' + ', '.join(f'{{{i}, "{t}", {a}, {z}}}' for i, t, a, z in sorted(ss.values())) + '},\n')
    f.write('  },\n  gossip = {\n')
    for npc, xs in sorted(gossip.items()):
        f.write(f'    [{npc}] = {{' + ', '.join(f'{{"{esc(sn)}", "{b}"}}' for b, sn in sorted(xs.items())) + '},\n')
    f.write('  },\n}\n')
if subprocess.run(['luac5.1', '-p', f'{AD}/Index.lua', f'{AD}/LivingVoices.lua']).returncode:
    sys.exit('Lua does not parse; the release was not zipped')
# (2026-11-02, public) the source is the GitHub repository (LICENSES.txt says where), not a src/ folder in the zip
for f in ('build/LivingVoices.dll', 'build/LivingVoicesPatcher.exe', 'patch_wowexe.py', 'README.txt', 'LICENSES.txt'):
    shutil.copy(f'{CLIENT}/{f}', OUT)

z = f'{OUT}.zip'
if os.path.exists(z): os.remove(z)
with zipfile.ZipFile(z, 'w', zipfile.ZIP_STORED, allowZip64=True) as zf:   # the MPQ does not compress; stored unzips fast
    for root, _, files in os.walk(OUT):
        for fn in sorted(files):
            p = os.path.join(root, fn); arc = os.path.relpath(p, os.path.dirname(OUT))
            zf.write(patch_full if fn == 'LivingVoices.patch.MPQ' else p, arc)      # the empty patch in the full zip
# (1.1.1) the same, as two downloads under GitHub's 2 GiB limit: part 1 is everything but the second archive, part 2
# only that archive, at the same path (unzipped over part 1 it lands beside LivingVoices.MPQ)
GIB2 = 2 * 1024 ** 3
for zp, keep in ((f'{OUT}-part1.zip', lambda fn: fn != 'LivingVoices.part2.MPQ'), (f'{OUT}-part2.zip', lambda fn: fn == 'LivingVoices.part2.MPQ')):
    if os.path.exists(zp): os.remove(zp)
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_STORED, allowZip64=True) as zf:
        for root, _, files in os.walk(OUT):
            for fn in sorted(files):
                if not keep(fn): continue
                p = os.path.join(root, fn); zf.write(patch_full if fn == 'LivingVoices.patch.MPQ' else p, os.path.relpath(p, os.path.dirname(OUT)))
    if os.path.getsize(zp) >= GIB2: sys.exit(f'{zp} is {os.path.getsize(zp) / 1e9:.2f} GB, over GitHub\'s 2 GiB per file')
    print(f'release part -> {zp} ({os.path.getsize(zp) / 1e9:.2f} GB)')
# (1.1.0, the producer) the small files alone -- engine, patcher, add-on and its index, docs; no LivingVoices.MPQ -- for
# an install that already has this version's archive: a DLL or add-on fix without re-copying 2.8 GB
zu = f'{OUT}-update.zip'
if os.path.exists(zu): os.remove(zu)
with zipfile.ZipFile(zu, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, _, files in os.walk(OUT):
        for fn in sorted(files):
            if fn in ('LivingVoices.MPQ', 'LivingVoices.part2.MPQ'): continue       # the base archives stay out
            p = os.path.join(root, fn); zf.write(p, os.path.relpath(p, os.path.dirname(OUT)))
print(f'update (no base MPQ; patch MPQ with {len(changed)} line(s)) -> {zu} ({os.path.getsize(zu) / 1e6:.1f} MB)')
print(f'{len(vo)} lines ({sum(1 for n in vo if n.startswith("g"))} chat), {len(titles)} quest titles, {len(gossip)} chatting NPCs, {len(missing)} missing -> {z} ({os.path.getsize(z) / 1e9:.2f} GB)')
for nm, s in missing: print('  missing', nm, s)
if in_review: print(f'{len(in_review)} line(s) on the review page shipped with their best take: {", ".join(in_review[:10])}')
