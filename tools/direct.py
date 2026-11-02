"""Voice direction: the model reads a whole quest in context and directs each spoken line's delivery.

Run from data/:  ../.venv/bin/python ../tools/direct.py <questId> [...]     (prints; tests)
                          ../.venv/bin/python ../tools/direct.py --all [--workers 8]  (directions.jsonl, resumable)
For each quest the model sees: title, level, zone, quest type, the chain around it, the speaker(s) (name, title,
race, sex), the objectives, and all three spoken texts. It returns per spoken line an actor's note and 1-3 beats,
each a run of numbered sentences with an IndexTTS-2 emotion vector. Text is never rewritten: beats only group
sentences we numbered.
"""
import csv, difflib, json, re, struct, sys, os, urllib.request, concurrent.futures as cf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
from sqlrows import rows, live_rows

SQL = f'{LV.AC_SQL}/'
LLM = f'{LV.LLM_URL}/v1/chat/completions'; MODEL = LV.LLM_MODEL
EMOS = ['happy', 'angry', 'sad', 'afraid', 'disgusted', 'melancholic', 'surprised', 'calm']
KINDS = {'accept': 'desc', 'progress': 'req', 'complete': 'off', 'gossip': 'gossip'}

def sqltable(name):
    txt = open(SQL + name + '.sql', encoding='utf-8', errors='replace').read()
    body = txt[txt.index('CREATE TABLE'):]; body = body[:body.index(') ENGINE')]
    c = [m.group(1) for m in re.finditer(r'^\s+`(\w+)`', body, re.M)]
    for r in rows(SQL + name + '.sql', null=''):
        yield dict(zip(c, r))
    yield from live_rows(name)                  # the realm's own and the holiday quests (extract_live.py)

def dbc_names(path, col):
    b = open(path, 'rb').read(); _, n, fc, rs, _ = struct.unpack('<4s4I', b[:20]); strs = b[20 + n * rs:]
    out = {}
    for i in range(n):
        r = struct.unpack(f'<{fc}I', b[20 + i * rs:20 + (i + 1) * rs]); o = r[col]
        out[r[0]] = strs[o:strs.index(b'\0', o)].decode('utf-8', 'replace')
    return out

# database typos the producer found (2026-10-13; pronunciation sheet 2): corrected before anything reads the text -- the
# director, the voice and the speech check all see the right word. The same fixes go to the world database
# (sql/quest_text_typos.sql) so the quest window shows them too.
_FIXES = json.load(open('text_fixes.json')) if os.path.exists('text_fixes.json') else {}
_FIX_RE = re.compile(r'\b(' + '|'.join(re.escape(w) for w in sorted(_FIXES, key=len, reverse=True)) + r')\b') if _FIXES else None

def fix_typos(t):
    return _FIX_RE.sub(lambda m: _FIXES[m.group(1)], t) if _FIX_RE and t else t

def clean(t):
    # $N (name) -> adventurer, $C (class) -> hero, $R (race) -> traveler; "a hero", "an adventurer"; a sentence that
    # began with a placeholder gets its capital back ("adventurer, you are a adventurer" -- pilot, 2026-10-11)
    t = re.sub(r'\$[bB]', '\n', t); t = fix_typos(t)        # after the line breaks: "$B$BUnderwold" had no word boundary
    # a name pun ("$ner", "$Nama", "$nath", "Purple Leafed $Nrium" -- Daryl the Bold, 2026-10-13): the voice cannot say the
    # hero's name, so the whole pun is "adventurer"
    t = re.sub(r'\$[nN][a-z]+\b', 'adventurer', t)
    # a race and class together ("his favorite $r $c") is one stand-in, not two: "traveler hero" read as a name
    # (Great-father Winter, the producer 2026-10-18)
    t = re.sub(r'\$[rRcC]\s+\$[rRcC]', 'hero', t)
    # (2026-10-26, the producer's review) placeholders the voice was handed as written: "%N" (12310: "Is it done, %N?",
    # read as a name), a world-state counter "$2063w" ("we've collected $2063w pieces of medium leather": 'many'), and
    # "$T rank : rank;" (9589: the rank it names, once)
    t = re.sub(r'%[nN]\b', '$N', t); t = re.sub(r'\$\d+[wW]\b', 'many', t)
    t = re.sub(r'\$[tT]\s*([^:;]*?)\s*:[^;]*;(\s*\$[nN]\b)?', r'\1', t)
    t = re.sub(r'\$[nN]', 'adventurer', t); t = re.sub(r'\$[cC]', 'hero', t)
    t = re.sub(r'\$[rR]', 'traveler', t)
    # <grin>, <cough>, <snort>... are the speaker's sounds, not words: kept as *grin* etc. for render.py's sound map
    # (data/sfx.json), as the *Whir* kind already are (2026-10-12; they used to be deleted). <name> is the hero's name.
    t = re.sub(r'\$[gG]([^:;]*):([^;]*);', r'\1', t); t = re.sub(r'<name>', 'adventurer', t, flags=re.I)
    # ...except a short one in several different words that is no sound in the map ("<Nazgrel salutes you crisply>",
    # "<Kalecgos sighs>"): that is a stage direction too (2026-10-13). "<cough cough>" stays a sound.
    def short(m):
        w = m.group(1).strip(); words = {x.lower() for x in w.split()}
        return f'\n{STAGE[0]}{w}.{STAGE[1]}\n' if len(words) > 1 and w.lower() not in SFX_KEYS else f'*{w}*'
    t = re.sub(r'<([A-Za-z][A-Za-z \-]{0,30})>', short, t)
    # anything longer is a stage direction ("<Bouldercrag begins to look over the documents, his eyes wide.>"): kept
    # as its own paragraph in STAGE brackets, read by the narrator where it stands -- the producer wanted these
    # narrated rather than dropped (2026-10-13; 1,216 lines had one inside the speech, 95 were nothing else)
    t = re.sub(r'<([^>]*[A-Za-z][^>]*)>', lambda m: f'\n{STAGE[0]}{m.group(1).strip()}{STAGE[1]}\n', t)
    t = re.sub(r'<[^>]*>', '', t)
    t = re.sub(r'\b([Aa]) (adventurer)\b', lambda m: ('An' if m.group(1) == 'A' else 'an') + ' ' + m.group(2), t)
    t = re.sub(r'\b([Aa])n (hero|traveler)\b', lambda m: m.group(1) + ' ' + m.group(2), t)
    t = re.sub(r'(^|[.!?]\s+|\n\s*)(adventurer|hero|traveler)\b', lambda m: m.group(1) + m.group(2).capitalize(), t)
    return re.sub(r'\n\s*\n+', '\n', t).strip()

STAGE = '\u27e8\u27e9'      # ⟨stage direction⟩: the narrator reads it (clean())
SFX_KEYS = set(json.load(open('sfx.json'))) if os.path.exists('sfx.json') else set()   # render.py's sound map

def sentences(t):
    """split the cleaned text into sentences; joining them back with ' ' / newlines restores the text. A stage
    direction is one sentence, however many it holds"""
    parts = []
    for para in t.split('\n'):
        if para.strip().startswith(STAGE[0]): parts.append(para.strip()); continue
        parts += [s for s in re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', para.strip()) if s]
    return parts

# ---------------------------------------------------------------- context tables (loaded once)
Q = json.load(open('ac_quests.json'))
# (2026-10-29, the producer) what a quest giver says when you talk to them, before any quest (tools/gossip_plan.py):
# pseudo-quests "g<npc>...", each one line of kind 'gossip', so the voice and the speech check read them like the rest
if os.path.exists('gossip.json'): Q.update(json.load(open('gossip.json')))
# (2026-10-16, the producer) lines whose words are ours: Blizzard's placeholders ("temp text 02 - description",
# "[PH] ...") filled in by Claude from the quest, the speaker and the chain; a chicken's clucks as its own sounds.
# Laid over the quest text here, so the director, the voice and the speech check all read the same words.
if os.path.exists('rewrites.json'):
    for nm, x in json.load(open('rewrites.json')).items():
        if nm.startswith('_'): continue
        q, kind = nm.split('-')[:2]
        Q[q][KINDS[kind]] = x['text']
area = dbc_names('dbc/AreaTable.dbc', 11); qsort = dbc_names('dbc/QuestSort.dbc', 1); qinfo = dbc_names('dbc/QuestInfo.dbc', 1)
QT = {r['ID']: r for r in sqltable('quest_template')}
PREV = {r['ID']: r['PrevQuestID'] for r in sqltable('quest_template_addon')}
NEXT = {}
for qid, r in QT.items():
    if r['RewardNextQuest'] not in ('', '0'): NEXT[qid] = r['RewardNextQuest']
for qid, p in PREV.items():
    if p not in ('', '0') and str(abs(int(p))) in QT: NEXT.setdefault(str(abs(int(p))), qid)
CT = {r['entry']: r for r in sqltable('creature_template')}
PLAN = collections = None
import collections
SPEAKERS = collections.defaultdict(dict)        # qid -> kind -> (npc_id, name, race, sex)
for r in csv.DictReader(open('plan_v3.csv')):
    SPEAKERS[r['questId']][r['kind']] = (r['npc_id'], r['npc_name'], r['race'], r['sex'])

PERSONA = {}            # entry -> persona line from an NPC profile table (the realm's chat bots keep one), when exported
if os.path.exists('npc_profiles.tsv'):
    for r in csv.DictReader(open('npc_profiles.tsv'), delimiter='\t'):
        if r.get('persona') and r['persona'] != 'NULL' and (r['entry'] not in PERSONA or r.get('spawn_guid') in ('', 'NULL')):
            raw = r['persona'].replace('\\n', ' ')
            try:
                j = json.loads(raw)
                v = j.get('voice') if j.get('voice') not in (None, '', 'none') else None
                PERSONA[r['entry']] = (j.get('persona') or '') + (f' Their voice: {v}' if v else '')
            except ValueError:
                PERSONA[r['entry']] = raw

# (2026-10-12) the producer's notes on particular characters -- how far to take them -- by npc id
# (data/actor_notes.json, {"<npc>": "<note>"}). They outrank the usual restraint on intensity for that character.
ACTOR_NOTES = {k: v for k, v in (json.load(open('actor_notes.json')).items() if os.path.exists('actor_notes.json') else [])
               if not k.startswith('_')}

def who(sp):
    npc, name, race, sex = sp
    if npc.startswith('go:'): return f'an object: "{name}" (read aloud by a narrator)'
    if npc.startswith('item:'): return f'an item: "{name}" (read aloud by a narrator)'
    sub = CT.get(npc, {}).get('subname') or ''
    r = '' if race == 'unknown' else f', {sex} {race.replace("ss:", "")}'
    p = PERSONA.get(npc)
    note = ACTOR_NOTES.get(npc)
    return (f'{name}' + (f' <{sub}>' if sub else '') + r + (f'\n   Who they are: {p}' if p else '')
            + (f'\n   The producer on this character: {note}' if note else ''))

def chain_after(qid, n=3, chars=260):
    """the next n quests of the chain: (title, the start of their offer text)"""
    out, q, seen = [], NEXT.get(qid), {qid}
    while q and q not in seen and q in Q and len(out) < n:
        seen.add(q); out.append((Q[q]['title'], clean(Q[q].get('desc') or '')[:chars])); q = NEXT.get(q)
    return out

def gossip_context(qid):
    """a quest giver's chat text: who they are, where they stand, and the quests they hand out (for the colour)"""
    g = Q[qid]; npc = g['npc']
    sp = SPEAKERS.get(qid, {}).get('gossip') or (npc, g['title'], 'unknown', 'unknown')
    head, _, persona = who(sp).partition('\n')
    gives = [q for q, k in SPEAKERS.items() if not q.startswith('g') and k.get('accept', ('',))[0] == npc and q in Q][:4]
    lines = [f"Zone: {area.get(int(g.get('zone') or 0)) or 'unknown'}"]
    if gives:
        lines.append('Quests this character gives (for colour; none is being offered in this line):')
        lines += [f"  - {Q[q]['title']}: {' '.join(clean(Q[q].get('desc') or '').split())[:200]}" for q in gives]
    ss = sentences(clean(g['gossip']))
    lines.append(f'\n[gossip] spoken by {head} when the hero walks up and talks to them, before choosing any quest '
                 f'-- their everyday greeting:' + (f'\n{persona}' if persona else ''))
    lines += [f'  {i}. {s}' for i, s in enumerate(ss, 1)]
    return '\n'.join(lines), {'gossip': ss}

def context(qid):
    if qid.startswith('g'): return gossip_context(qid)
    q = Q[qid]; t = QT.get(qid, {})
    sort = int(t.get('QuestSortID') or 0)
    where = area.get(sort) if sort > 0 else (qsort.get(-sort) and f'{qsort[-sort]} (a class/profession/holiday quest)')
    info = qinfo.get(int(t.get('QuestInfoID') or 0))
    prev = PREV.get(qid, '0'); prev = Q.get(str(abs(int(prev))), {}).get('title') if prev not in ('', '0') else None
    nxt = Q.get(NEXT.get(qid, ''), {}).get('title')
    lines = [f"Quest: {q['title']} (level {t.get('QuestLevel', '?')}){' - ' + info if info else ''}",
             f"Zone: {where or 'unknown'}"]
    if prev: lines.append(f'Follows the quest: {prev}')
    if nxt: lines.append(f'Leads to the quest: {nxt}')
    later = chain_after(qid)
    if later:                       # the story the hero has not reached yet: for subtext (a deceiver's later turn)
        lines.append('Later in this chain (the hero does not know this yet -- use it only for subtext):')
        lines += [f'  - {t}: {d}' for t, d in later]
    obj = clean(t.get('LogDescription') or '')
    if obj: lines.append(f'Objective (quest log, not spoken): {obj}')
    spoken = {}
    for kind, col in KINDS.items():
        txt = clean(q.get(col) or '')
        if not txt: continue
        sp = SPEAKERS.get(qid, {}).get(kind)
        ss = sentences(txt); spoken[kind] = ss
        head, _, persona = (who(sp) if sp else 'the quest giver').partition('\n')
        lines.append(f"\n[{kind}] spoken by {head}"
                     + {'accept': ' when offering the quest:', 'progress': ' when the hero returns before finishing:',
                        'complete': ' when the hero returns having finished:'}[kind] + (f'\n{persona}' if persona else ''))
        lines += [f'  {i}. {s}' for i, s in enumerate(ss, 1)]
    return '\n'.join(lines), spoken

SYSTEM = """You are a voice director for World of Warcraft quest dialogue. An actor will perform each line with a cloned \
voice; you decide the emotional delivery from the full situation: who is speaking, where, what is at stake, and how \
this moment sits in the story. Quest givers are people in a living world: a farmer pestered by wolves is annoyed, not \
heroic; a commander on a besieged front is clipped and urgent; a grieving widow is sad; a goblin hustler is gleeful; a \
returning hero is greeted with relief or pride. Avoid flat narration, but do not overact: most lines are \
conversational, and emotion should be what a real person in that situation would show.

Weigh the stakes. The quest level and zone tell you how much is at risk: a low-level errand near a town or abbey \
(kobolds in the mine, wolves by the farm, a lost necklace) is everyday business -- deliver it lightly, briskly, even \
cheerfully; a person's habitual weariness is a faint colour, not the whole performance. Save grimness, dread and \
urgency for real danger: war, plague, death, the fate of a town or a people.

For each beat give:
1. "style": the delivery style that best fits, from this list:
{styles}
2. "emotion": a few words for how this beat is performed, specific to the moment and the person -- what an actor
would be told. Not a category ("angry", "happy") but the colour of it: "gruff and grudging, conceding a point he
hates", "breathless with excitement, barely holding the news in", "cold and clipped, every word a warning".
The style is the nearest of the list; the emotion is what the voice actually performs.
3. "intensity": 1-10, how much energy and volume the line gets. 2 = murmured or hushed, 4 = ordinary conversation, \
6 = animated, 8 = raised voice, 10 = shouting. MOST quest dialogue is ordinary conversation, 3-5: a style says WHAT \
the feeling is, intensity says HOW MUCH of it shows. A sly bargain is sly at 3-4, not at 8; even good news is usually \
a 5. Keep 7+ for real alarm, battle and triumph.

Direct each spoken line as ONE beat (first = 1, last = the final sentence) with one style for the whole line. Only \
when the feeling clearly turns partway (calm explanation, then a battle cry) use a second beat, starting at the \
sentence where it turns -- never more than two beats, never a beat of a single short sentence. A line performed in \
one breath sounds natural; every split risks a change of pace.

Some quest text is not spoken by anyone. Test every line: could the quest giver say these exact words aloud to the \
hero? If the text describes the quest giver in the third person ("Yenniku stands stunned before you", "Judging by \
the gaping wound in her side, Anilia is near death"), or tells the hero what they themselves do or see ("You place \
the Soul Gem upon his forehead. He shudders..."), the quest giver cannot be saying it: that line is \
"voice": "narrator", read by a storyteller. Corpses, objects, written notes and stunned or dying givers often read \
this way. A line the quest giver says, in the first person or to the hero, is "voice": "npc".

A sentence in ⟨ ⟩ is a stage direction ("⟨The apothecary wrings her hands.⟩"): a narrator reads it aloud automatically, whatever voice the line has, so judge "voice" only on the other sentences. Read it as the actor's cue: it tells you how the words around it are said. It belongs to the beat it sits in.

Answer with JSON only:
{"<kind>": {"voice": "npc" or "narrator",
            "note": "<one short actor's note: who, to whom, what feeling>",
            "subtext": "<what the speaker hides or really wants, or empty -- a deceiver stays warm on the surface>",
            "beats": [{"first": <first sentence number>, "last": <last sentence number>, "style": "<style>",
                       "emotion": "<a few words: how THIS beat is performed>", "intensity": <1-10>}]}, ...}
with one entry per spoken line kind that appears (accept / progress / complete / gossip)."""

# delivery styles: each is a real performance from the client (game_voices/), used as IndexTTS-2's emotion
# reference while the NPC's own clip gives the voice; a female speaker takes the female performance.
STYLES = {   # style: (what it is, male clip, female clip)
    'rallying_cry':      ('rousing a crowd to battle, loud and fierce',
                          'Thrall/WG_Thrall_HOR03.wav', 'Lady_Sylvanas_Windrunner/HR_Sylvanas_HR15.wav'),
    'urgent_orders':     ('a commander giving urgent orders in a crisis, clipped and driving',
                          'High_Overlord_Saurfang/IC_Saurfang_Intro04.wav', 'Lady_Jaina_Proudmoore/HR_Jaina_HR14.wav'),
    'grim_resolve':      ('grim, determined, the stakes are deadly serious',
                          'High_Overlord_Saurfang/IC_Saurfang_Intro03.wav', 'Lady_Sylvanas_Windrunner/HR_Sylvanas_HR13.wav'),
    'alarmed':           ('alarmed or exasperated by bad news, quick and agitated',
                          'Brann_Bronzebeard/HS_BrannBronzebeard_SjonnirVictorySpeech01.wav', 'Lady_Jaina_Proudmoore/WG_Jaina_ALL04.wav'),
    'triumphant_praise': ('proud, triumphant praise of a victory',
                          'King_Varian_Wrynn/CR_Varian_TwinsAComplete01.wav', 'Tyrande_Whisperwind/CAV_Tyrande_WispIntro01.wav'),
    'steady_explaining': ('steady, serious explanation of a situation',
                          'Thrall/WG_Thrall_HORIntro05.wav', 'Lady_Jaina_Proudmoore/FS_Jaina_FS04.wav'),
    'sorrow':            ('grief, a heavy personal loss',
                          'High_Overlord_Saurfang/IC_Saurfang_EndHor01.wav', 'Lady_Jaina_Proudmoore/IC_Jaina_TurnIn06.wav'),
    'contempt':          ('scornful, menacing contempt for an enemy',
                          'Thrall/WG_Thrall_HOR21.wav', 'Lady_Sylvanas_Windrunner/WG_Sylvanas_HOR03.wav'),
    'cheerful':          ('cheerful, chatty, enthusiastic',
                          'Brann_Bronzebeard/HS_BrannBronzebeard_ArriveTribunal.wav', 'Lady_Jaina_Proudmoore/IC_Jaina_Event02.wav'),
    'courteous':         ('polite, formal courtesy',
                          'Thrall/CR_Thrall_HArrival03.wav', 'Lady_Jaina_Proudmoore/WG_Jaina_HORIntro05.wav'),
    'exasperated':       ('put-upon, grumbling exasperation at trouble or bad news; a busy person fed up with it',
                          'Brann_Bronzebeard/UR_Brann_Archivum07.wav', 'Lady_Sylvanas_Windrunner/HR_Sylvanas_Wall03.wav'),
    # five from the style survey (2026-10-12): clean designed performances, one continuous take per sex
    'pleading':          ('asking for help in trouble or danger -- a captive, a victim, someone desperate',
                          'style_sets/designed/pleading_male.wav', 'style_sets/designed/pleading_female.wav'),
    'relieved_grateful': ('relief and thanks: the danger is past, the job is done, you came back',
                          'style_sets/designed/relieved_grateful_male.wav', 'style_sets/designed/relieved_grateful_female.wav'),
    'wry':               ('dry, ironic, self-deprecating -- a raised eyebrow in the voice',
                          'style_sets/designed/wry_male.wav', 'style_sets/designed/wry_female.wav'),
    'sly':               ('sly, conspiratorial, scheming, selling something -- a knowing half-smile',
                          'style_sets/designed/sly_male.wav', 'style_sets/designed/sly_female.wav'),
    # (2026-10-12) mocking, a smirk you can hear: a brat, a rogue gloating, a sarcastic merchant (Billy Maclure)
    'smug':              ('smug, sarcastic, mocking -- a smirk you can hear, pleased with yourself, talking down',
                          'style_sets/designed/smug_male.wav', 'style_sets/designed/smug_female.wav'),
    # (2026-10-12) a real whisper: "Psst!", a secret, a warning under the breath (the producer: Remy's whispered "Hey")
    'hushed':            ('whispered, under the breath -- a secret, a "psst", a warning no one else should hear',
                          'style_sets/designed/hushed_male.wav', 'style_sets/designed/hushed_female.wav'),
    'mystical':          ('serene, otherworldly, prophetic -- seers, shamans, druids, spirits',
                          'style_sets/designed/mystical_male.wav', 'style_sets/designed/mystical_female.wav'),
    'weary_regret':      ('wistful sadness for something lost or past -- real regret, NOT relief, humility or annoyance',
                          'Muradin_Bronzebeard/IC_Muradin_TurnIn06.wav', 'Lady_Jaina_Proudmoore/IC_Jaina_TurnIn05.wav'),
}

# Race-matched performances (2026-10-11): an emotion clip also lends a little of its speaker's voice -- Brann's dwarven
# gravel made Marshal McBride sound like someone else for two sentences. Human men take their emotion from human men
# (Varian, Tirion, Rhonin, Brandon); everyone else uses STYLES above until their own sets are chosen.
STYLES_BY_GROUP = {
    'human_male': {
        'rallying_cry':      'King_Varian_Wrynn/WG_Varian_ALLIntro01.wav',
        'urgent_orders':     'King_Varian_Wrynn/IC_Varian_Wrynn_DBA04.wav',
        'grim_resolve':      'Highlord_Tirion_Fordring/Misc_Tirion_LHPostFight11.wav',
        'alarmed':           'King_Varian_Wrynn/WG_Varian_ALL04.wav',
        'triumphant_praise': 'King_Varian_Wrynn/CR_Varian_TwinsAComplete01.wav',
        'steady_explaining': 'Rhonin/UR_Rhonin_Event06.wav',
        'sorrow':            'Highlord_Tirion_Fordring/CR_TirionFordring_YetiLose01.wav',
        'contempt':          'King_Varian_Wrynn/CR_Varian_JaraxxusExit01.wav',
        'cheerful':          'style_sets/designed/cheerful_male.wav',   # designed 2026-10-12: Rhonin's Event03 climbed to a
                                                           # near-shout and carried its game mastering into Billy's render
        'courteous':         'Highlord_Tirion_Fordring/CR_TirionFordring_AArrival01.wav',
        'exasperated':       'King_Varian_Wrynn/CR_Varian_AArrival02.wav',
        'weary_regret':      'Captain_Brandon/IC_Captain_Brandon_Survived01.wav',
    },
}

def style_group(race, sex):
    r = (race or '').lower().replace('ss:', '')
    sx = 'female' if sex == 'female' else 'male'
    if r == 'human' and sx == 'male': return 'human_male'
    key = {'human': 'human', 'orc': 'orc', 'dwarf': 'dwarf', 'troll': 'troll', 'forest troll': 'troll', 'ice troll': 'troll',
           'tauren': 'tauren', 'taunka': 'tauren', 'undead': 'undead', 'blood elf': 'blood_elf', 'night elf': 'night_elf',
           'draenei': 'draenei', 'broken': 'draenei', 'gnome': 'gnome', 'goblin': 'goblin'}.get(r)
    return f'{key}_{sx}' if key else None

def _set_clip(group, style, seen=()):
    """data/style_sets/<group>/<style>.wav, following the reviewers' fallbacks (another style or another group)"""
    if not group or group in seen: return None
    path = os.path.join('style_sets', group, style + '.wav')
    if os.path.exists(path): return path
    sel = os.path.join('style_sets', f'selection_{group}.json')
    if os.path.exists(sel):
        fb = (json.load(open(sel))['picks'].get(style) or {}).get('fallback')
        if fb:
            if fb in STYLES: return _set_clip(group, fb, seen + (group,)) if fb != style else None
            return _set_clip(fb, style, seen + (group,))
    return None

def style_clip(style, sex, race=None):
    """emotion reference for a style: the speaker's race/sex set (style_sets/, reviewed 2026-10-11; human men in
    STYLES_BY_GROUP), else the general clip -- female for a female speaker, male otherwise"""
    grp = style_group(race, sex) or ('human_female' if sex == 'female' else 'human_male')   # unique races -> human
    g = STYLES_BY_GROUP.get(grp, {})
    if style in g: return g[style] if g[style].startswith('style_sets/') else 'game_voices/' + g[style]
    p = _set_clip(grp, style)
    if p: return p
    human = 'human_female' if sex == 'female' else 'human_male'      # a fallback chain that dead-ends: same-sex human
    if style in STYLES_BY_GROUP.get(human, {}):
        c = STYLES_BY_GROUP[human][style]; return c if c.startswith('style_sets/') else 'game_voices/' + c
    p = _set_clip(human, style)
    if p: return p
    d = STYLES[style]; c = d[2] if sex == 'female' else d[1]
    return c if c.startswith('style_sets/') else 'game_voices/' + c

def schema(kinds):
    beat = {'type': 'object', 'required': ['first', 'last', 'style', 'emotion', 'intensity'], 'properties': {
        'first': {'type': 'integer'}, 'last': {'type': 'integer'}, 'style': {'type': 'string', 'enum': list(STYLES)},
        'emotion': {'type': 'string'},
        'intensity': {'type': 'integer'}}}
    line = {'type': 'object', 'required': ['voice', 'note', 'subtext', 'beats'], 'properties': {
        'voice': {'type': 'string', 'enum': ['npc', 'narrator']},
        'note': {'type': 'string'}, 'subtext': {'type': 'string'},
        'beats': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'items': beat}}}
    return {'type': 'object', 'required': list(kinds), 'properties': {k: line for k in kinds}}

def ask(prompt, kinds):
    body = {'model': MODEL, 'temperature': 0.3, 'max_tokens': 1600,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'direction', 'schema': schema(kinds)}},
            'messages': [{'role': 'system', 'content': SYSTEM.replace('{styles}', '\n'.join(f'   {k}: {v[0]}' for k, v in STYLES.items()))}, {'role': 'user', 'content': prompt}]}
    r = urllib.request.Request(LLM, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(r, timeout=300))['choices'][0]['message']['content']

def letters(t):
    return re.sub(r'[^a-z0-9]', '', t.lower())

def read_as_ok(text, read_as):
    """the performance script may change punctuation only: same letters and digits, in the same order -- and it may
    not add colons or ellipses (the model over-applies them; a pause the text does not have becomes a Kirk pause)"""
    if not (bool(read_as) and letters(text) == letters(read_as)): return False
    # an ellipsis may be swapped for a dash or comma (Remy "Two Times": "for me...for me?" read as two sentences,
    # 2026-10-12), never ADDED -- the model over-applies them, and a pause the text does not have is a Kirk pause
    if read_as.count(':') > text.count(':') or read_as.count('...') > text.count('...'): return False
    # pause marks may be swapped (comma -> dash, comma -> question mark), never added
    pauses = lambda t: len(re.findall(r'\.\.\.|--|\s-\s|[,;:]', t))
    return pauses(read_as) <= pauses(text)

def validate(d, spoken, repair=False):
    """-> {kind: {note, beats: [{text, emotion(8 floats, IndexTTS order)}]}} or raises.
    repair (the last try): beats numbered with a gap or an overlap are renumbered instead of refused -- a beat
    starts where the previous one ended, its style and emotion kept (the first night lost 16 lines in 7 quests to
    "beat 3-3 after 0 of 4", 2026-10-13)"""
    out = {}
    for kind, ss in spoken.items():
        e = d[kind]; beats = []; nxt = 1
        for b in e['beats']:
            a, z = int(b['first']), min(int(b['last']), len(ss))
            if a > len(ss) and beats: break          # a beat past the end: the previous one already covers the line
            if repair and a != nxt:
                if z < nxt: continue                 # wholly inside what earlier beats cover
                a = nxt
            if a != nxt or z < a: raise ValueError(f'{kind}: beat {a}-{z} after {nxt - 1} of {len(ss)}')
            text = ' '.join(ss[a - 1:z])
            beats.append({'sentences': [a, z], 'text': text, 'style': b.get('style'),
                          'emotion': (b.get('emotion') or '').strip()[:200],
                          'intensity': max(1, min(10, int(b.get('intensity') or 5)))})
            nxt = z + 1
        if nxt <= len(ss):          # beats stopped short: the last beat carries the rest
            rest = ' '.join(ss[beats[-1]['sentences'][1]:])
            beats[-1]['sentences'][1] = len(ss); beats[-1]['text'] = ' '.join(ss[beats[-1]['sentences'][0] - 1:])
        out[kind] = {'voice': e.get('voice') or 'npc', 'note': e.get('note', ''), 'subtext': e.get('subtext', ''),
                     'beats': beats}
    return out

def direct(qid, tries=3):
    prompt, spoken = context(qid)
    err = None
    for i in range(tries):
        try: return validate(json.loads(ask(prompt + (f'\n\n(Your last answer was invalid: {err}. Fix it.)' if err else ''), spoken)),
                             spoken, repair=i == tries - 1)
        except Exception as e: err = str(e)[:200]
    raise RuntimeError(f'{qid}: {err}')


# Performance scripts (punctuation for reading) are NOT made by the model here: four Gemma designs were unreliable
# (2026-10-11). They live in data/scripts.json -- original sentence -> reading -- reviewed once by Claude and added to
# by ear; render.py applies them through read_as_ok().

if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0] in ('--all', '--quests'):
        # --quests <file> [--out <jsonl>]: only the quests listed (one id per line), e.g. pilot_quests.txt
        workers = int(args[args.index('--workers') + 1]) if '--workers' in args else 8
        # --compare: also quests whose lines are all reused (the pilot's pack-vs-ours comparison)
        need = sorted({r['questId'] for r in csv.DictReader(open('plan_v3.csv'))
                       if r['action'] == 'generate' or '--compare' in args}, key=int)
        if args[0] == '--quests':
            only = set(open(args[1]).read().split()); need = [q for q in need if q in only]
        path = args[args.index('--out') + 1] if '--out' in args else 'directions.jsonl'
        done = {json.loads(l)['questId'] for l in open(path)} if os.path.exists(path) else set()
        todo = [q for q in need if q not in done]
        print(len(need), 'quests with generated lines,', len(todo), 'to direct', flush=True)
        with open(path, 'a') as f, cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(direct, q): q for q in todo}
            for n, fu in enumerate(cf.as_completed(futs), 1):
                q = futs[fu]
                try: f.write(json.dumps({'questId': q, **fu.result()}) + '\n')
                except Exception as e: f.write(json.dumps({'questId': q, 'error': str(e)}) + '\n')
                if n % 100 == 0: f.flush(); print(f'  {n}/{len(todo)}', flush=True)
    else:
        for qid in args:
            print('=' * 100); print(context(qid)[0]); print('-' * 40)
            print(json.dumps(direct(qid), indent=1))
