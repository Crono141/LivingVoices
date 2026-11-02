"""Race and class in the voice (2026-10-31, the producer: "restore the dropped addresses as well"; the pilot "a huge
success"). A sentence with $R or $C is rendered once per race or class the hearer can be, and spliced into the line's
accepted take at playback (engine 0.4, PlaySpliced) in place of that sentence; the rest of the take is untouched, so
every race hears the same performance. A sentence that said "hero"/"traveler" says the class or race; one whose bare
address was dropped ("Luck to you.") gets it back ("Luck to you, brave paladin.").

    python3 ../tools/variants.py plan [--enqueue]      (from data/)

-> variants.json  {"<line>_s<i>_<word>": {base, i, beat, tok, word, text}} -- i: the sentence's index in the line as
                  render_line reads it (0-based, across beats); beat: the beat that holds it; text: what the clip says
                  (scripts.json readings kept); word: 'paladin', 'night_elf', 'blood_elf_mage' (both, 12 sentences)
   --enqueue: each clip into overnight.sqlite as its own line ('todo'), rendered by the runner like any other
Who can hear a line: the quest's AllowableRaces / AllowableClasses; with no race limit, the giver's side (its faction
template's groups: 2 Alliance, 4 Horde; neutral = all ten); classes only those the allowed races can be.
Not split: only a line not directed yet (the next night plans it). A line with a stage direction or a sound, a
narrator's or another speaker's beat or a morphed voice is split too (2026-11-01) and carries 'risk': splices.py hears
it spliced before its clips ship.
"""
import csv, json, os, re, sqlite3, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import direct, render, overnight

RACES = {1: 'human', 2: 'orc', 4: 'dwarf', 8: 'night elf', 16: 'undead', 32: 'tauren', 64: 'gnome', 128: 'troll',
         512: 'blood elf', 1024: 'draenei'}
CLASSES = {1: 'warrior', 2: 'paladin', 4: 'hunter', 8: 'rogue', 16: 'priest', 32: 'death knight', 64: 'shaman',
           128: 'mage', 256: 'warlock', 1024: 'druid'}
ALLIANCE, HORDE = 1101, 690
CAN = {'human': 'warrior paladin hunter rogue priest mage warlock death_knight',
       'dwarf': 'warrior paladin hunter rogue priest shaman mage death_knight',
       'night elf': 'warrior hunter rogue priest druid death_knight', 'gnome': 'warrior rogue mage warlock death_knight',
       'draenei': 'warrior paladin hunter priest shaman mage death_knight',
       'orc': 'warrior hunter rogue shaman warlock death_knight', 'undead': 'warrior rogue priest mage warlock death_knight',
       'tauren': 'warrior hunter shaman druid death_knight', 'troll': 'warrior hunter rogue priest shaman mage death_knight',
       'blood elf': 'paladin hunter rogue priest mage warlock death_knight'}
SR, SC = 'Zqrace', 'Zqclass'            # stand in for $R / $C until the sentence is final; no rule in the pipeline knows them
TOKEN = re.compile(r'\$([rRcC])(?![a-z])')
STAND = {'R': 'traveler', 'C': 'hero'}

def db(sql):
    r = subprocess.run(['mariadb', f'--defaults-extra-file={LV.DB_CNF}', '-N', '-B', '-e', sql],
                       capture_output=True)
    return [l.split('\t') for l in r.stdout.decode(errors='replace').splitlines() if l]

def sides():
    """creature entry -> 'A' | 'H' | '' (both): who the giver serves, from its faction template's groups"""
    ft = {}
    for i, g, f, e in db('SELECT ID, FactionGroup, FriendGroup, EnemyGroup FROM acore_world.factiontemplate_dbc'):
        g, f, e = int(g), int(f), int(e)
        a, h = bool((g | f) & 2 or e & 4), bool((g | f) & 4 or e & 2)
        ft[i] = 'A' if a and not h else 'H' if h and not a else ''
    return {c: ft.get(f, '') for c, f in db('SELECT entry, faction FROM acore_world.creature_template')}

def an(word): return 'an' if word[0] in 'aeiou' else 'a'

def finish(t, words):
    """the sentinels -> the words; 'a Zqrace' -> 'an orc'; a sentence that starts with one gets its capital"""
    for s, w in words:
        if not w: continue
        t = re.sub(rf'\b([Aa])n? ({s})\b', lambda m: (an(w).capitalize() if m.group(1) == 'A' else an(w)) + ' ' + m.group(2), t)
        t = re.sub(rf'^(\W*){s}', lambda m: m.group(1) + w[0].upper() + w[1:], t)
        t = t.replace(s, w)
    return t

def variant_text(sent_sentinel, sent_normal, words):
    """what the clip says. Kept: the line's own reading of the sentence (scripts.json), with the stand-in swapped
    for the word, when the reading still says the stand-in; else the sentence built again with the address kept"""
    reading = render.SCRIPTS.get(sent_normal)
    if reading:
        t, ok = reading, True
        for s, w in words:
            st = STAND['R' if s == SR else 'C']
            if len(re.findall(rf'\b{st}\b', t, re.I)) != len(re.findall(s, sent_sentinel)): ok = False; break
            t = re.sub(rf'\b{st}\b', s, t, flags=re.I)
        if ok: return finish(t, words)
    return finish(render.scripted(sent_sentinel), words)

def plan(enqueue=False):
    rows = list(csv.DictReader(open('plan_v3.csv')))
    D = overnight.load_directions([overnight.DIRECTIONS])
    QT = {r['ID']: r for r in direct.sqltable('quest_template')}
    AD = {r['ID']: r for r in direct.sqltable('quest_template_addon')}
    side = sides()
    c = sqlite3.connect('overnight.sqlite')
    status = dict(c.execute('SELECT name, status FROM lines'))
    out, skipped, lines = {}, {}, 0
    for r in rows:
        nm = overnight.name_of(r)
        if r['npc_id'] == 'none' or status.get(nm) not in ('done', 'review', 'todo', 'new', 'rendered'): continue
        q, kind, v = r['questId'], r['kind'], r['variant']
        raw = (direct.Q.get(q) or {}).get(direct.KINDS[kind]) or ''
        if not TOKEN.search(raw): continue
        d = D.get(q, {}).get(kind)
        g = overnight.as_generated(r)
        if not d: skipped['no direction'] = skipped.get('no direction', 0) + 1; continue
        # (2026-11-01, the producer: "I want everything covered") the lines once left out are split too; the clip renders
        # as its beat does (render_line: the morph, the narrator's stage direction, a sound, another speaker's casting).
        # Their takes are harder to cut (narration and sounds between the words, an echo over the pauses), so splices.py
        # listens to each such line spliced before any of its clips ship: 'risk' says why
        risk = ','.join(k for k, on in (('stage', '<' in raw or '*' in raw or direct.STAGE[0] in raw),
                                        ('narrator', d.get('voice') == 'narrator'),
                                        ('speaker', any(b.get('speaker') for b in d['beats'])),
                                        ('morph', bool(g and g.get('morph')))) if on)
        # the line's sentences as render_line reads them, once as written and once with the tokens as sentinels
        sent = lambda text: [(bi, s) for bi, t in enumerate(render.beat_texts(q, kind, v, d['beats'])) for s in direct.sentences(t)]
        orig = direct.Q[q][direct.KINDS[kind]]
        try:
            normal = sent(None)
            direct.Q[q][direct.KINDS[kind]] = TOKEN.sub(lambda m: SR if m.group(1) in 'rR' else SC, raw)
            marked = sent(None)
        finally:
            direct.Q[q][direct.KINDS[kind]] = orig
        if len(normal) != len(marked): skipped['sentences differ'] = skipped.get('sentences differ', 0) + 1; continue
        qt = QT.get(q, {}); rm = int(qt.get('AllowableRaces') or 0); cm = int(AD.get(q, {}).get('AllowableClasses') or 0)
        races = [n for b, n in RACES.items() if rm & b] if rm else None
        if not races:
            s_ = side.get(r['npc_id'], '') if r['npc_id'].isdigit() else ''
            races = [n for b, n in RACES.items() if (ALLIANCE if s_ == 'A' else HORDE if s_ == 'H' else 1791) & b]
        classes = [n for b, n in CLASSES.items() if (not cm or cm & b) and any(n.replace(' ', '_') in CAN[x].split() for x in races)]
        n_here = 0
        for i, ((bi, s_n), (_, s_m)) in enumerate(zip(normal, marked)):
            hasR, hasC = SR in s_m, SC in s_m
            if not (hasR or hasC): continue
            combos = ([(x, y) for x in races for y in classes if y.replace(' ', '_') in CAN[x].split()] if hasR and hasC
                      else [(x, None) for x in races] if hasR else [(None, y) for y in classes])
            for x, y in combos:
                key = '_'.join(w.replace(' ', '_') for w in (x, y) if w)
                out[f'{nm}_s{i}_{key}'] = dict(base=nm, i=i, beat=bi, tok=('R' if hasR else '') + ('C' if hasC else ''), word=key,
                                               text=variant_text(s_m, s_n, [(SR, x), (SC, y)]), **({'risk': risk} if risk else {}))
                n_here += 1
        lines += bool(n_here)
    json.dump(out, open('variants.json', 'w'), indent=1, ensure_ascii=False)
    words = sum(len(x['text'].split()) for x in out.values())
    print(f'{lines} lines -> {len(out)} clips, {words} words (~{words / 2.6 / 3600:.1f} h of speech); not split: {skipped}')
    if enqueue:
        base = {overnight.name_of(r): r for r in rows}
        n = 0
        for vn, x in out.items():
            b = base[x['base']]
            n += c.execute('INSERT OR IGNORE INTO lines (name, questId, kind, variant, npc_id, npc_name, words, status, updated) '
                           'VALUES (?,?,?,?,?,?,?,?,?)', (vn, b['questId'], b['kind'], b['variant'], b['npc_id'], b['npc_name'],
                                                          len(x['text'].split()), 'todo', overnight.now())).rowcount
        c.commit(); print(n, 'clips queued')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'plan': lambda: plan('--enqueue' in sys.argv)}[sys.argv[1]]()
