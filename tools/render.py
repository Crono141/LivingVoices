"""Render quest lines: plan row + direction -> one finished clip. The renderer the pilot and the overnight runs share.

Run from data/ with the ComfyUI venv:
  ~/ComfyUI/venv/bin/python ../tools/render.py --quests pilot_quests.txt --directions pilot_directions.jsonl \
      [--compare] [--url http://127.0.0.1:42422] [--listen <dir>]

- speaker reference (the voice): designed_voices/<npc>.mp3 for 'design:' lines (objects/items: narrator.mp3),
  the client's own clip for 'game:' lines, the NPC's own pack clip for pack refs (local zip, else a ranged fetch);
  trimmed to ~12 s, which IndexTTS-2 clones best from.
- each beat: IndexTTS-2 single beam, the beat's style clip (direct.STYLES, by the speaker's sex) as the emotion
  reference at alpha 0.65; beats are pace-matched (+-15%) and joined with a 0.35 s pause.
- $G lines: the variant's own text, split into the same numbered sentences the direction used.
- --compare: also render OUR version of every reused line (pack vs ours), and copy the pack clip beside it.
Outputs: render/<qid>-<kind>[-<v>].mp3, render_compare/... ; with --listen, a copy per NPC folder + INDEX.txt.
"""
import collections, csv, json, os, re, shutil, struct, subprocess, sys, time, urllib.request, urllib.error, zipfile, zlib
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import direct
from direct import STYLES, style_clip

ROOT = f'{LV.COMFY_OUT}'
ALPHA = 0.55          # 0.65 let the style clip's own voice bleed into the NPC's (McBride, 2026-10-11)
GPAT = re.compile(r'\$[Gg]\s*([^:;]+?)\s*:\s*([^:;]+?)\s*;')
PACKS = json.load(open('packs.json'))
IDX = {'spoken': 'sq.json', 'mrthinger': 'AI_VoiceOverData_Vanilla.json'}
_idx_cache, _zips = {}, {}

def args_get(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default
URL = args_get('--url', LV.RENDERERS["1"])
# where the ComfyUI behind URL writes: the pipeline's own instances (comfy2.sh) write straight into ROOT; the ComfyUI on
# card 0 (shared with other work) writes under its own output folder, so its parts go to <comfy_subdir>/... there
OUTBASE, PREFIX = ROOT, ''
def use_server(url):
    global URL, OUTBASE, PREFIX
    URL = url; _uploaded.clear()
    own = {LV.RENDERERS[k].rstrip('/') for k in LV.OWN_RENDERERS if k in LV.RENDERERS}
    if url.rstrip('/') in own: OUTBASE, PREFIX = ROOT, ''     # the voice-over's own instances (tools/comfy2.sh)
    else: OUTBASE, PREFIX = LV.OUTPUTS, LV.COMFY_SUBDIR.rstrip('/') + '/'

# ---------------------------------------------------------------- text
def variant_clean(t, v):
    if v == 'f': t = GPAT.sub(r'\2', t)
    else: t = GPAT.sub(r'\1', t)
    return direct.clean(t)

SCRIPTS = {}       # original sentence -> the same words punctuated for reading (scripts.json; Claude review + by ear)
if os.path.exists('scripts.json'):
    for k, v in json.load(open('scripts.json')).items():
        if not k.startswith('_') and direct.read_as_ok(k, v): SCRIPTS[k] = v

# (2026-10-18) a title or nickname said as a name, set apart with an ellipsis: "What do you want... stranger?"
# (tools/title_check.py: the model decides which closing phrases are titles; casual tags like "mon" and "lad" are not)
# A casual tag ("mon", "lad", "friend") can be read as a plain word too, but a pause before every one gets old: it is
# set apart once in a beat (nearly every line is one), and not where the beat already has a title (the producer)
_T = json.load(open('titles.json')) if os.path.exists('titles.json') else {}
TITLES, CASUAL = _T.get('title', {}), _T.get('casual', {})

def scripted(t):
    out, used = [], False
    for x in (drop_address(SCRIPTS.get(s, s)) for s in direct.sentences(t)):
        if x in TITLES: x = TITLES[x]; used = True
        out.append(x)
    if not used:
        for i, x in enumerate(out):
            if x in CASUAL: out[i] = CASUAL[x]; break
    return ' '.join(out)

# Spoken lines leave out a bare address to the player ("Your first task is one of cleansing, adventurer." ->
# "...cleansing."; "Greetings, Mage!" -> "Greetings!"): the quest window shows the real name, the voice cannot, and a
# stand-in on every line is distracting (the producer, 2026-10-11). Only an address set off by a comma at the edge of
# a sentence or clause goes; "you are a hero with...", "Thank you, hero of the Alliance." stay.
ADDRESS = (r"(?:adventurers?|heroes|hero|travelers?|champions?|death knights?|warriors?|paladins?|hunters?|rogues?|"
           r"priests?|shamans?|mages?|warlocks?|druids?|humans?|dwarf|dwarves|gnomes?|night elf|night elves|"
           r"draenei|orcs?|trolls?|taurens?|undead|blood elf|blood elves)")
ADJ = r"(?:(?:young|brave|dear|good|noble|mighty|fellow|my|little|wise)\s+){0,2}"
TRAIL = re.compile(r",\s+" + ADJ + ADDRESS + r"(?=\s*(?:[.!?]|--|,))", re.I)
LEAD = re.compile(r"^(\W*)" + ADJ + ADDRESS + r",\s+(\w)", re.I)

def drop_address(sentence):
    out = TRAIL.sub('', sentence)
    out = LEAD.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    return out if re.search(r'[A-Za-z]', out) else sentence

# ---------------------------------------------------------------- numbers, numerals and initialisms said in words
# (2026-10-26, the producer's review of the lines that failed six seeds) IndexTTS-2's English normaliser re-tokenises
# a whole text that holds a digit, and in doing so splits every apostrophe off its word: "You'll find a farm... Steal
# 10 pumpkins" reached the model as "You ' ll", read "you el el"; "Lady Rouack's... pages 18 and 20" as "Rouack ess".
# Without a digit it leaves the text alone. It also read "Buzzbox 827" as "eight hundred and twenty seven", "5200" as
# "five thousand two hundred", and Roman numerals as letters ("Chapter eye vee"). So every number is spelled here, the
# producer's way: a model number digit by digit ("Buzzbox eight two seven", "four seven one one F T Z"), round
# thousands in hundreds ("fifty-two hundred"), counts as counts; "Chapter IV" -> "Chapter four"; D.E.H.T.A. letter by
# letter. No digit is left for the normaliser.
_ONES = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
         'seventeen eighteen nineteen').split()
_TENS = 'x x twenty thirty forty fifty sixty seventy eighty ninety'.split()
_ORD = {'one': 'first', 'two': 'second', 'three': 'third', 'five': 'fifth', 'eight': 'eighth', 'nine': 'ninth', 'twelve': 'twelfth'}
_DIGIT = ['oh'] + _ONES[1:10]
_LETTER = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', ('ay bee see dee ee eff gee aitch eye jay kay el em en oh pee cue ar ess '
                                                   'tee you vee double-you ex why zee').split()))
_SAID_AS_WORD = {'STOUT': 'Stout', 'BOOM': 'Boom', 'AWOL': 'ay-wall'}     # initialisms said as a word
_ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12,
          'XIII': 13, 'XIV': 14, 'XV': 15, 'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20}

def cardinal(n):
    """1234 -> 'one thousand two hundred thirty-four' (no 'and')"""
    if n < 20: return _ONES[n]
    if n < 100: return _TENS[n // 10] + ('' if n % 10 == 0 else '-' + _ONES[n % 10])
    if n < 1000: return _ONES[n // 100] + ' hundred' + ('' if n % 100 == 0 else ' ' + cardinal(n % 100))
    for size, word in ((10 ** 9, 'billion'), (10 ** 6, 'million'), (1000, 'thousand')):
        if n >= size: return cardinal(n // size) + ' ' + word + ('' if n % size == 0 else ' ' + cardinal(n % size))

def count_word(n):
    """a count: 5200 -> 'fifty-two hundred' (a round hundred between 1,100 and 9,900), else the cardinal"""
    return cardinal(n // 100) + ' hundred' if 1100 <= n <= 9900 and n % 100 == 0 and n % 1000 else cardinal(n)

def ordinal(n):
    w = cardinal(n); head, last = re.match(r'(.*?)([a-z]+)$', w).groups()
    return head + (_ORD.get(last) or (last[:-1] + 'ieth' if last.endswith('y') else last + 'th'))

def model_number(s):
    """the digits of a name or model: 'Buzzbox 827' -> eight two seven, 4711 -> four seven one one, 002 -> oh oh two;
    two digits as a number ('Area 52'), round ones as said ('Sparklematic 5200', 'Super Reaper 6000', 'Incarcinatrix 900')"""
    n = int(s)
    if s[0] == '0' and len(s) > 1: return ' '.join(_DIGIT[int(d)] for d in s)
    if len(s) <= 2 or (len(s) == 3 and n % 100 == 0) or (len(s) == 4 and n % 1000 == 0): return cardinal(n)
    if len(s) == 4 and n % 100 == 0: return count_word(n)
    return ' '.join(_DIGIT[int(d)] for d in s)

def letters(s):
    return ' '.join(_LETTER[ch] for ch in s)

def code_words(tok):
    """a code of capitals and digits -- OOX-22/FE, XT-002, K3, X6000, SI:7, 4711-FTZ -- piece by piece: capitals as
    letters ('oh oh ex'), numbers as a model's; a piece in mixed case ('A-Me') kept as written"""
    out = []
    for p in re.findall(r'[A-Za-z]+|\d+', tok):
        out.append(model_number(p) if p.isdigit() else letters(p) if p.isupper() and len(p) <= 4 else p)
    return ' '.join(out)

def say_numbers(t):
    # a lone I after a lowercase keyword with a word after it is the pronoun: "the book I sent you" (2026-10-28,
    # 1160-complete); "Book I of the Annals" and "chapter I." stay numerals
    def roman(m):
        n, after = m.group(2), t[m.end():m.end() + 2]
        if n not in _ROMAN or n == 'I' and m.group(1)[0].islower() and re.match(r'\s\w', after): return m.group(0)
        return f'{m.group(1)} {cardinal(_ROMAN[n])}'
    t = re.sub(r'\b((?i:chapter|volume|vol\.|phase|rank|part|book|act|mark|tier|stage|level|section))\s+([IVX]{1,5})\b', roman, t)
    # (the producer) after a name a numeral is a ruler's: "Prince William III" -> "the Third"; a lone I, V or X is not
    # taken ("Then I", "Hall of Ages V"?)
    t = re.sub(r'\b([A-Z][a-z]+)\s+((?:II|III|IV|VI{1,3}|IX|XI{1,3}|XIV|XVI{0,3}|XIX|XX))\b(?![\w\u2019\'])',
               lambda m: f'{m.group(1)} the {ordinal(_ROMAN[m.group(2)]).capitalize()}', t)
    def initialism(m):
        w = m.group(0).replace('.', ''); said = _SAID_AS_WORD.get(w) or letters(w)
        # the last dot may also end the sentence: kept as a full stop when a new sentence follows
        return said + ('.' if re.match(r'\s+[A-Z]', t[m.end():]) or m.end() == len(t) else '')
    t = re.sub(r'\b(?:[A-Z]\.){3,}', initialism, t)
    # codes: capitals and digits joined (K3, X6000, SGM-3, OOX-22/FE, 4711-FTZ, SI:7, X 52 after pronounce.json)
    t = re.sub(r'\b(?=[\w:/-]*\d)(?=[\w:/-]*[A-Z])(?:[A-Z]+\d+[A-Z\d]*|[A-Z][A-Za-z]*(?:[-:/ ]\d+)(?:[-/][A-Z\d]+)*|'
               r'\d+-[A-Z]+)\b', lambda m: code_words(m.group(0)) if not re.fullmatch(r'[A-Z][a-z]+ \d+', m.group(0)) else m.group(0), t)
    # a model number after its name, mid-sentence ("the Sparklematic 5200", "Buzzbox 827"); a sentence's first word is no name
    def named(m):
        if re.search(r'(^|[.!?]["\')\u2019\u201d]*\s+)$', t[:m.start()]): return m.group(0)
        return f'{m.group(1)} {model_number(m.group(2))}'
    t = re.sub(r'\b([A-Z][\w\u2019\'-]*[a-z])\s(\d{3,})\b(?![,.]\d|%)', named, t)
    t = re.sub(r'\b(\d+)(?:st|nd|rd|th)\b', lambda m: ordinal(int(m.group(1))), t)
    t = re.sub(r'\b(\d+(?:\.\d+)?)\s?%', lambda m: m.group(1) + ' percent', t)
    t = re.sub(r'\b(\d{1,2})\s?([ap])\.?m\b\.?', lambda m: f'{cardinal(int(m.group(1)))} {m.group(2).upper()} M', t, flags=re.I)
    t = re.sub(r'#\s?(\d+)', lambda m: 'number ' + m.group(1), t)
    t = re.sub(r'\((\d+)\)\s*', lambda m: cardinal(int(m.group(1))) + ', ', t)
    t = re.sub(r'\b(\d+)\.(\d+)\b', lambda m: f'{cardinal(int(m.group(1)))} point {" ".join(_ONES[int(d)] for d in m.group(2))}', t)
    t = re.sub(r'\b\d{1,3}(?:,\d{3})+\b', lambda m: cardinal(int(m.group(0).replace(',', ''))), t)
    t = re.sub(r'\b0\d+\b', lambda m: ' '.join(_DIGIT[int(d)] for d in m.group(0)), t)
    return re.sub(r'\d+', lambda m: count_word(int(m.group(0))), t)

PRON = json.load(open('pronounce.json')) if os.path.exists('pronounce.json') else {}
VOICE_CAST = json.load(open('voice_cast.json')) if os.path.exists('voice_cast.json') else {}
def speakable(t, accent='neutral', dialect=None):
    """what the voice reads: pronounce.json respellings (whole words; '*shire' place names -> '-sher'), and every
    apostrophe inside a word made typographic: IndexTTS-2's normaliser expands "it's/that's/he's..." to "it is" with a
    regex on the straight apostrophe BEFORE it maps the curly one back -- so "it’s" reaches the model as "it's"
    (McBride, pilot 2026-10-11)."""
    # respellings BEFORE the apostrophes are curled: every name with one in it (Atal'ai, Drak'atal: 741 entries) is
    # keyed with a straight apostrophe, and none of them had ever matched (found 2026-10-16)
    for w, r in PRON.get('words', {}).items():
        t = re.sub(rf'\b{re.escape(w)}\b', r, t)
    t = say_numbers(t)            # after the respellings (X-52 -> 'X 52'), so no digit reaches the normaliser
    t = re.sub(r"(?<=\w)'(?=\w)", "\u2019", t)
    # (2026-10-18, the producer) a hyphen between two words is read as a pause: "Nether (pause) Rocket", "Demolisher
    # (pause) class" -- a space, after the respellings (X-52 and the like are keyed with theirs)
    t = re.sub(r'(?<=[A-Za-z])-(?=[A-Za-z])', ' ', t)
    for suf, r in PRON.get('_suffix', {}).items():
        r = r.get(accent, r.get('neutral', suf)) if isinstance(r, dict) else r
        t = re.sub(rf'\b([A-Z][a-z]+){suf}\b', lambda m: m.group(1) + r, t)
    return dialect_text(t, dialect) if dialect else t

# (2026-10-16, the producer: "it certainly sells the accent a lot better") every troll speaks with the dialect on;
# goblins not (their New York accent survives the clone); dwarves tried and dropped (no gain, some lines worse)
DIALECT_BY_RACE = {'troll': 'troll'}
def dialect_of(row):
    return row.get('dialect') or DIALECT_BY_RACE.get((row.get('race') or '').lower().replace('ss:', ''))

def dialect_text(t, dialect):
    """an accent's tics spelled out (pronounce.json _dialect): 'the' -> 'de' for a troll, capitals kept"""
    D = PRON.get('_dialect', {}).get(dialect) or {}
    for w, r in D.get('words', {}).items():
        t = re.sub(rf'\b{w}\b', r, t); t = re.sub(rf'\b{w.capitalize()}\b', r.capitalize(), t)
    if D.get('ing'): t = re.sub(r'\b([A-Za-z]{2,}[^aeiouAEIOU\W])ing\b', '\\1in\u2019', t)
    return t

# ---------------------------------------------------------------- sound effects written into the text
# (2026-10-12, the producer) "*Whir* *Click* *Zzzap*" and the like are sound effects, not words: data/sfx.json
# (tools/build_sfx.py) says what each marker becomes -- a game sound spliced in, the speaker's cry emote, a word
# the voice says ("Hic!"), the word itself ("*my*" is emphasis), or nothing ("*grin*"). An unknown marker: nothing.
SFX = json.load(open('sfx.json')) if os.path.exists('sfx.json') else {}
MARK = re.compile(r'\*([^*\n]{1,40})\*')
CRY_RACE = {'night elf': 'nightelf', 'blood elf': 'bloodelf', 'undead': 'scourge', 'forsaken': 'scourge'}

def inline_markers(t):
    """markers that become a word or nothing, resolved in the text; sound markers are kept for split_sounds"""
    def sub(m):
        how = SFX.get(m.group(1).strip().lower(), 'drop')
        if how == 'word': return m.group(1)
        if how.startswith('say:'): return how[4:]
        if how == 'drop': return ''
        return m.group(0)
    return re.sub(r'\s+([.,!?;:])', r'\1', re.sub(r' {2,}', ' ', MARK.sub(sub, t))).strip()

def cry_clip(race, sex, emote='cry'):
    """the client's emote (cry, sigh, yawn) for the speaker's race and sex, else the human one"""
    r = (race or '').lower().replace('ss:', '')
    r = CRY_RACE.get(r, r.replace(' ', ''))
    sx = 'female' if sex == 'female' else 'male'
    for c in (f'sfx/{emote}_{r}_{sx}.wav', f'sfx/{emote}_human_{sx}.wav'):
        if os.path.exists(c): return c
    return None

def split_sounds(t, race, sex):
    """[('say', text) | ('sound', path)] in order of the text"""
    out, pos, turn = [], 0, collections.Counter()
    for m in MARK.finditer(t):
        before = t[pos:m.start()].strip()
        if re.search(r'[A-Za-z0-9]', before): out.append(('say', before))
        how = SFX.get(m.group(1).strip().lower(), '')
        if how.startswith('cycle:'):      # variety: the next of the list each time it comes up in the line (the chicken)
            key = m.group(1).strip().lower(); opts = how[6:].split(','); how = opts[turn[key] % len(opts)]; turn[key] += 1
        paths = ([how] if how.startswith('sfx/') else [SFX.get(how[6:], '')] * 2 if how.startswith('twice:')
                 else [cry_clip(race, sex, how[6:])] if how.startswith('emote:') else [])
        out += [('sound', p) for p in paths if p and os.path.exists(p)]
        pos = m.end()
    rest = t[pos:].strip()
    if re.search(r'[A-Za-z0-9]', rest): out.append(('say', rest))
    return out

def spoken_text(t):
    """only what the voice says (for the speech-recognition check): markers resolved, sound markers removed; a stage
    direction is said too (by the narrator)"""
    t = t.replace(direct.STAGE[0], ' ').replace(direct.STAGE[1], ' ')
    return re.sub(r'\s{2,}', ' ', MARK.sub('', inline_markers(t))).strip()

STAGE_RE = re.compile(f'{direct.STAGE[0]}([^{direct.STAGE[1]}]*){direct.STAGE[1]}')

def split_stage(t):
    """[('stage', text) | ('line', text)] in order: stage directions apart from the speaker's words"""
    out, pos = [], 0
    for m in STAGE_RE.finditer(t):
        if t[pos:m.start()].strip(): out.append(('line', t[pos:m.start()].strip()))
        if m.group(1).strip(): out.append(('stage', m.group(1).strip()))
        pos = m.end()
    if t[pos:].strip(): out.append(('line', t[pos:].strip()))
    return out

STAGE_EMOTION = 'a calm storyteller quietly setting the scene'

def render_stage(text, qid, tag, seed):
    """a stage direction in the narrator's voice: even, low-key, the same for every line"""
    nar = dict(NARRATOR_ROW, questId=qid, npc_name='narrator')
    t = text if re.search(r'[.!?\u2026]$', text) else text + '.'
    return render_beat(speakable(t), speaker_ref(nar), style_clip('steady_explaining', 'male', 'unknown'), tag,
                       seed=seed, alpha=alpha_for(3), emo_text=STAGE_EMOTION)

def beat_texts(qid, kind, v, beats):
    ss = direct.sentences(variant_clean(direct.Q[qid][direct.KINDS[kind]] or '', v))
    # a line break the text leaves unpunctuated ends a sentence too: "Wanted: Hogger$B$BA huge gnoll" was read as one
    # sentence, "Hogger a huge gnoll" (the producer, 2026-10-12); also item lists and verse. Only a paragraph's last
    # piece can lack an end mark (sentences() splits on . ! ?), so a full stop goes there
    ss = [s if re.search(r'[.!?:;,\u2026"\'\u2019\u201d)\]*\-\u27e9]$', s) else s + '.' for s in ss]
    out = []
    for i, b in enumerate(beats):
        a, z = b['sentences']
        if i == len(beats) - 1: z = len(ss)              # variant split differently: the last beat takes the rest
        out.append(' '.join(ss[a - 1:z]))
    return [t for t in out if t]

# ---------------------------------------------------------------- references
# (2026-10-20) the reference cache is shared by both cards' workers and each step skips a file that exists: Noraani's
# trimmed reference was uploaded while the other card was still writing it (0 bytes in ComfyUI's input, two lines
# failed). Every cache file is written under a temporary name and renamed into place, whole.
def _part(dst):
    b, e = os.path.splitext(dst); return f'{b}.part{os.getpid()}{e}'

def pack_clip(ref, dst):
    """'<pack>:<path in zip>' -> local file (local zip, else a ranged fetch of that one member)"""
    pack, name = ref.split(':', 1)
    if os.path.exists(f'packs/{pack}.zip'):
        if pack not in _zips: _zips[pack] = zipfile.ZipFile(f'packs/{pack}.zip')
        open(t := _part(dst), 'wb').write(_zips[pack].read(name)); os.replace(t, dst); return dst
    j = IDX.get(pack, f'idx_{pack}.json')
    if j not in _idx_cache: _idx_cache[j] = json.load(open(j))
    m, csz, usz, off = _idx_cache[j][name]
    b = subprocess.run(['curl', '-sL', '-r', f'{off}-{off + csz + 700}', PACKS[pack]], capture_output=True, check=True).stdout
    nl, el = struct.unpack('<HH', b[26:30]); d = b[30 + nl + el:30 + nl + el + csz]
    if m == 8: d = zlib.decompressobj(-15).decompress(d)
    open(t := _part(dst), 'wb').write(d); os.replace(t, dst); return dst

# Family voices: an NPC with no clip of its own in its pack clones from a representative clip of the pack voice that
# would have spoken it -- 'speakstone:BEF' (SpeakStone's code: race + sex) or 'spoken:human-female-official' (a Spoken
# Quests voice). The representative is the longest reused offer line of that voice. (race sample, 2026-10-11)
SS_CODE_RACE = {'Hu': 'Human', 'Dw': 'Dwarf', 'Gn': 'Gnome', 'NE': 'Night Elf', 'Dr': 'Draenei', 'Or': 'Orc', 'Tr': 'Troll',
                'Ta': 'Tauren', 'Ud': 'Undead', 'BE': 'Blood Elf', 'Go': 'Goblin'}
_family = {}
def family_clip(ref):
    if ref in _family: return _family[ref]
    pack, voice = ref.split(':', 1); best = None
    if pack == 'speakstone':
        race = SS_CODE_RACE.get(voice[:2], 'ss:' + voice[:2]); sex = 'female' if voice.endswith('F') else 'male'
        for r in csv.DictReader(open('plan_v3.csv')):
            if r['action'] == 'reuse' and r['source_pack'].startswith('speakstone') and r['race'] == race and r['sex'] == sex \
                    and r['kind'] == 'accept' and (best is None or int(r['words']) > int(best['words'])):
                best = r
        out = f"{best['source_pack']}:{best['file_in_pack']}" if best else None
    elif pack == 'spoken':
        import gzip
        sq = {k.rsplit('/', 1)[1]: k for k in json.load(open('sq.json')) if '/sounds/quests/' in k}
        rank = lambda l: (l.get('source') == 'accept', len(l.get('originalText') or ''))   # offers first, then longest
        for l in json.load(gzip.open('spoken_corpus.json.gz'))['lines']:
            if l.get('voice') == voice and (l.get('fileName') or '') + '.ogg' in sq and (best is None or rank(l) > rank(best)):
                best = l
        out = f"spoken:{sq[best['fileName'] + '.ogg']}" if best else None
    else:
        out = None
    _family[ref] = out
    return out

def speaker_ref(row):
    os.makedirs('refs_cache', exist_ok=True)
    ref = row['clone_ref']
    if ref.startswith('design:') or row.get('_ours'):
        # an unknown race is the narrator, except a child (Illiyana, Anilia: people, with their own designed voices)
        key = ('narrator' if row['npc_id'].startswith(('go:', 'item:'))
               or (row['race'] == 'unknown' and not row['clone_ref'].endswith('_child')) else row['npc_id'])
        src = f'designed_voices/{key}.mp3'
        if not os.path.exists(src): raise FileNotFoundError(f'no designed voice for {key} ({row["npc_name"]})')
    elif ref.startswith('game:'):
        src = ref[5:]
    else:
        if '/' not in ref.split(':', 1)[1]:                       # a family voice, not the NPC's own clip
            fam = family_clip(ref)
            if not fam: raise FileNotFoundError(f'no representative clip for family voice {ref}')
            ref = fam
        safe = re.sub(r'[^A-Za-z0-9.]+', '_', ref)[-120:]
        src = f'refs_cache/{safe}'
        if not os.path.exists(src): pack_clip(ref, src)
    # '+' and '-' kept: pitch-shifted references differ only by sign (p+2 / p-2 both became p_2 and shared one cache
    # entry -- the 2026-10-14 grid rendered +2 and -2 from the same voice)
    dst = f'refs_cache/ref12_{re.sub(r"[^A-Za-z0-9.+-]+", "_", src)[-100:]}.wav'
    if not os.path.exists(dst):   # first ~12 s, faded out, mono 24 kHz
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-t', '12', '-af', 'afade=t=out:st=11.7:d=0.3',
                        '-ac', '1', '-ar', '24000', t := _part(dst)], check=True); os.replace(t, dst)
    return dst if src.endswith('/narrator.mp3') else trim_pauses(dst)   # the narrator: rated excellent as he is

TRIM_CAP = 0.3
def trim_pauses(ref, cap=TRIM_CAP, SR=24000):
    """the reference with every silence (under -40 dB) cut to `cap` seconds: IndexTTS-2 copies a reference's pauses into
    the speech (index-tts #337). The producer's lever tests (2026-10-16/17): a 0.15 s cap all but ended the
    mid-sentence pauses but rushed long lines; 0.3 s kept most of the gain and read long lines best"""
    dst = ref.rsplit('.', 1)[0] + f'_trim{int(cap * 100)}.wav'
    if os.path.exists(dst): return dst
    import numpy as np
    x = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', ref, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                                     capture_output=True, check=True).stdout, np.float32)
    f = 240; n = len(x) // f; frames = x[:n * f].reshape(n, f)
    quiet = 20 * np.log10(np.sqrt((frames ** 2).mean(1) + 1e-12)) < -40
    keep = np.ones(n, bool); run = 0; lim = int(cap * SR / f)
    for i in range(n):
        run = run + 1 if quiet[i] else 0
        if run > lim: keep[i] = False
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', '-', t := _part(dst)],
                   input=frames[keep].ravel().astype('<f4').tobytes(), check=True); os.replace(t, dst)
    return dst

# ---------------------------------------------------------------- ComfyUI
_uploaded = {}
use_server(URL)
def upload(path):
    if path in _uploaded: return _uploaded[path]
    r = requests.post(URL + '/upload/image', files={'image': (os.path.basename(path), open(path, 'rb'))},
                      data={'type': 'input', 'subfolder': 'wowvo', 'overwrite': 'true'}, timeout=60)
    r.raise_for_status(); j = r.json(); _uploaded[path] = f"{j['subfolder']}/{j['name']}"; return _uploaded[path]

CLIENT_ID = 'livingvoices'   # our jobs in a ComfyUI queue, told apart from the user's own (overnight.user_busy)
JOB_MAX_S = 30 * 60      # one ComfyUI job: the longest lines take a few minutes, a cold model load a minute more
def comfy(wf):
    r = urllib.request.Request(URL + '/prompt', data=json.dumps({'prompt': wf, 'client_id': CLIENT_ID}).encode(), headers={'Content-Type': 'application/json'})
    try: pid = json.load(urllib.request.urlopen(r, timeout=60))['prompt_id']
    except urllib.error.HTTPError as e: raise RuntimeError(e.read()[:800])
    # (2026-10-22) a job ComfyUI no longer has -- restarted, its queue lost -- never reaches the history, and this loop
    # would wait on it all night: a job that is neither queued nor in the history three checks running (10 s apart),
    # or still not done after 30 minutes, is a failed render (the worker retries it)
    t0, missing = time.time(), 0; next_q = t0 + 10
    while True:
        h = json.load(urllib.request.urlopen(f'{URL}/history/{pid}', timeout=30))
        if pid in h: break
        if time.time() - t0 > JOB_MAX_S: raise RuntimeError(f'ComfyUI job {pid} not done after {JOB_MAX_S // 60} min')
        if time.time() >= next_q:
            next_q = time.time() + 10
            q = json.load(urllib.request.urlopen(f'{URL}/queue', timeout=30))
            queued = any(j[1] == pid for j in q.get('queue_running', []) + q.get('queue_pending', []))
            missing = 0 if queued else missing + 1
            if missing >= 3 and pid not in json.load(urllib.request.urlopen(f'{URL}/history/{pid}', timeout=30)):
                raise RuntimeError(f'ComfyUI job {pid} lost: neither queued nor finished (ComfyUI restarted?)')
        time.sleep(1)
    st = h[pid]['status']
    if st.get('status_str') != 'success':
        # the error itself, not the tail of ComfyUI's message dump (that was the node's settings: the overnight
        # report had nothing to go on, 2026-10-13)
        err = [m[1] for m in st.get('messages', []) if m[0] == 'execution_error']
        if err: raise RuntimeError(f"{err[0].get('node_type')}: {err[0].get('exception_type')}: {err[0].get('exception_message')}"[:800])
        raise RuntimeError(json.dumps(st.get('messages'))[-800:])
    f = [a for o in h[pid]['outputs'].values() for a in o.get('audio', [])][0]
    return f"{OUTBASE}/{f['subfolder']}/{f['filename']}"

def alpha_for(intensity):
    """the direction's intensity (1-10) -> IndexTTS-2's emotion strength: 4 (ordinary talk) ~0.39, 8 ~0.63
    (the old fixed 0.55 was ~6.5 -- every line a little hotter than most quest dialogue wants)"""
    # (2026-10-17, the lever tests) +0.15 over that scale, never above 0.6: stronger emotion cut the mid-sentence
    # pauses; the old 0.75 top (an intensity-10 beat) ran Dillinger's orders away from him
    return round(max(0.2, min(0.6, 0.30 + 0.06 * (intensity or 5))), 2)

def alpha_was(intensity):
    """the scale before 2026-10-17, for the narrator (rated excellent on it); None = the engine's ALPHA"""
    return round(max(0.2, min(0.75, 0.15 + 0.06 * intensity)), 2) if intensity else None

WOMAN_ALPHA = 0.7

def asked(text):
    """a question as '???' (2026-10-18, by ear): one '?' often came out level; '???' won three of four (Shai, Topher,
    Magtoor) -- the fourth, 'Report, soldier?', drew out the 'soldier' instead. A beat that is one short question
    alone keeps '??' (sample 3: Aronen, Janela, Tore and the torches all fell at '???' -- slow, or corrupted)"""
    one = len(direct.sentences(text)) == 1 and len(text.split()) <= 12
    return re.sub(r'\?+', '??' if one else '???', text)

def calm(text, intensity):
    """a beat directed at 4 or below reads '!' as a full stop: IndexTTS-2 follows the punctuation over a gentle style
    clip, so Abercrombie's weary 'haven't eaten me!' climbed to a 6-7 (pilot 2026-10-12)"""
    return text.replace('!', '.') if (intensity or 5) <= 4 else text

# IndexTTS-2 sampling, settable for the lever test (2026-10-16): the model's own segment limit (120 is calibrated for
# Chinese token density -- index-tts #775: long English segments drift late) and the sampler's temperature
SEG_TOKENS, TEMPERATURE = 120, 0.8

def render_beat(text, speaker, emo_clip, tag, seed=1, alpha=None, emo_text=None):
    """emo_clip: a style reference performance (the default). emo_text: instead, a description of the emotion,
    turned into IndexTTS-2's emotion control by its own QwenEmotion model (test arm, 2026-10-12)"""
    wf = {'1': {'class_type': 'IndexTTSEngineNode', 'inputs': {
              'model_path': 'IndexTTS-2', 'device': 'cuda', 'emotion_alpha': alpha if alpha is not None else ALPHA, 'use_random': False,
              'max_text_tokens_per_segment': SEG_TOKENS, 'interval_silence': 200, 'temperature': TEMPERATURE, 'top_p': 0.8, 'top_k': 30,
              'do_sample': True, 'length_penalty': 0.0, 'num_beams': 1, 'repetition_penalty': 10.0, 'max_mel_tokens': 1500,
              'use_fp16': True, 'use_deepspeed': False, 'emotion_control': ['5', 0]}},
          '2': {'class_type': 'LoadAudio', 'inputs': {'audio': upload(speaker)}},
          '5': ({'class_type': 'QwenEmotionNode', 'inputs': {'qwen_model': 'qwen0.6bemo4-merge', 'emotion_text': emo_text}}
                if emo_text else {'class_type': 'LoadAudio', 'inputs': {'audio': upload(emo_clip)}}),
          '3': {'class_type': 'UnifiedTTSTextNode', 'inputs': {'TTS_engine': ['1', 0], 'text': text, 'narrator_voice': 'none',
              'seed': seed, 'opt_narrator': ['2', 0], 'enable_chunking': True, 'max_chars_per_chunk': 400, 'enable_audio_cache': False}},
          '4': {'class_type': 'SaveAudio', 'inputs': {'audio': ['3', 0], 'filename_prefix': f'{PREFIX}render_parts/{tag}'}}}
    try:
        return comfy(wf)
    except Exception as e:
        # IndexTTS-2's QwenEmotion parser keeps a value Qwen quoted ({"..": "0.3"}) as a string and then fails on
        # "'<' not supported between instances of 'str' and 'float'" -- the same every time for that phrase (5261,
        # 2026-10-13). That beat takes its style clip's emotion instead.
        if emo_text and "'str' and 'float'" in str(e):
            print(f'   ({tag}: QwenEmotion could not read "{emo_text}"; the style clip carries the emotion)', flush=True)
            return render_beat(text, speaker, emo_clip, tag, seed, alpha, None)
        # IndexTTS-2's "Sizes of tensors must match ... Expected size 1 but got size 2" on a long beat it cuts into
        # segments (Keeper Bel'dugur, 736, both seeds; 2026-10-13): the beat is read in two halves, split between
        # sentences, and joined with the usual sentence pause
        ss = direct.sentences(text)
        if 'Sizes of tensors must match' in str(e) and len(ss) > 1:
            h = len(ss) // 2
            print(f'   ({tag}: IndexTTS-2 tensor-size error; read as two halves of {h} and {len(ss) - h} sentences)', flush=True)
            parts = [render_beat(' '.join(x), speaker, emo_clip, f'{tag}{k}', seed, alpha, emo_text)
                     for k, x in (('a', ss[:h]), ('b', ss[h:]))]
            out = parts[0].rsplit('.', 1)[0] + '_halves.flac'
            join(parts, out); return out
        raise

# ---------------------------------------------------------------- pace + join
def speech_rate(path, words):
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-af',
                          'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse',
                          '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout
    return words / max(len(out) / 4 / 8000, 0.1)

# A line slower than its voice's floor (words a second, ends trimmed, pauses counted) is sped up to the floor, pitch
# kept, at most PACE_MAX -- measured, not a fixed factor (the producer, 2026-10-13). Calibrated on the takes he judged:
# Maywiki 2.24 too slow -> 2.69 right; Wilhelm 2.38 wanted ~2.74; Hamuul (tauren) 2.34 good; the Elwynn pilot's median
# 3.01, slowest tenth 2.53. Faster lines are left alone. Speeding the REFERENCE instead cost the troll women their accent.
# Every line is measured (0.04 s; 0.1 s when it is sped up -- the producer: "run it against everybody"). The default
# floor sits just under the approved Elwynn pilot's slowest tenth, so it only catches outliers; the known-slow voices
# and the deliberately slow ones have their own (overnight.PACE_FLOOR_BY_SRC).
PACE_FLOOR, PACE_MAX = 2.5, 1.25

def take_rate(base):
    """the words a second of a line's accepted take (pre-morph copy if any): a race/class clip is read at its take's pace
    (2026-11-02: 48 of the 91 clips on review failed only as 'slow' -- 8601's take at 2.5 w/s, its clips at 1.2-1.9)"""
    try:
        p = base.split('-'); q, kind, v = p[0], p[1], (p[2] if len(p) > 2 else '')
        meant = spoken_text(scripted(variant_clean(direct.Q[q][direct.KINDS[kind]] or '', v)))
        src = f'render/{base}.check.mp3' if os.path.exists(f'render/{base}.check.mp3') else f'render/{base}.mp3'
        return speech_rate(src, len(meant.split())) if meant.split() and os.path.exists(src) else None
    except Exception: return None

def heard_right(t, meant):
    """pronounce.json _heard_right: word -> regexes of the transcript that are that word heard right but spelled the
    recognizer's way ("Torrin" for tauren); applied only when the text says the word"""
    for w, pats in PRON.get('_heard_right', {}).items():
        if w.startswith('_') or not re.search(rf'\b{re.escape(w)}\b', meant, re.I): continue
        for pat in pats: t = re.sub(pat, w, t)
    return t

def pace_up(dst, text, floor):
    w = len(spoken_text(text.replace(direct.STAGE[0], ' ').replace(direct.STAGE[1], ' ')).split())
    r = speech_rate(dst, w) if w else floor
    if r >= floor: return 1.0
    f = round(min(floor / r, PACE_MAX), 3)
    tmp = dst + '.slow.mp3'; os.replace(dst, tmp)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-af', f'atempo={f}', '-b:a', '128k', dst], check=True)
    os.remove(tmp); return f

def one_long_pause(dst, gap=0.5, short=0.4, longest=1.0, thresh=-35):
    """the producer's gap shortener (2026-10-14): a Forsaken drawls between sentences, and every line paced like that
    wears on a player -- so the line's longest pause stays (at most `longest` s, the dramatic one) and every other
    pause over `gap` s is cut to `short` s. Runs before the pace check, which then measures the tightened line."""
    import numpy as np
    sr = 24000
    y = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', dst, '-f', 'f32le', '-ac', '1', '-ar', str(sr), '-'],
                                     capture_output=True, check=True).stdout, dtype=np.float32)
    hop = int(0.01 * sr); n = len(y) // hop
    if n < 10: return 0
    db = 20 * np.log10(np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    loud = db > thresh; idx = np.flatnonzero(loud)
    if len(idx) < 2: return 0
    runs, start = [], None                       # silent runs strictly inside the speech (ends left alone)
    for i in range(idx[0], idx[-1] + 1):
        if not loud[i] and start is None: start = i
        if loud[i] and start is not None:
            if (i - start) * 0.01 > gap: runs.append((start, i))
            start = None
    if not runs: return 0
    keep = max(runs, key=lambda r: r[1] - r[0])
    out, pos = [], 0
    for a, b in runs:
        want = int((min(longest, (b - a) * 0.01) if (a, b) == keep else short) * sr)
        a, b = a * hop, b * hop
        if b - a <= want: continue
        mid = a + want // 2                      # keep the pause's edges (breath tails, onsets), drop its middle
        out.append(y[pos:mid]); pos = b - (want - want // 2)
    out.append(y[pos:])
    tmp = dst + '.gaps.mp3'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', '-', '-b:a', '128k', tmp],
                   input=np.concatenate(out).tobytes(), check=True)
    os.replace(tmp, dst); return len(runs) - 1

def even_pace(parts, texts):
    if len(parts) < 2: return parts
    w = [len(t.split()) for t in texts]; r = [speech_rate(p, n) for p, n in zip(parts, w)]
    target = sum(w) / sum(n / x for n, x in zip(w, r)); out = []
    for p, x in zip(parts, r):
        f = max(0.87, min(1.15, target / x))
        if abs(f - 1) < 0.03: out.append(p); continue
        q = p.rsplit('.', 1)[0] + '_paced.flac'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', p, '-af', f'atempo={f:.3f}', q], check=True); out.append(q)
    return out

TRIM_END = 'areverse,silenceremove=start_periods=1:start_threshold=-40dB:start_silence=0.02,areverse'

def join(parts, dst, sounds=()):
    """the parts in order, 0.35 s apart. `sounds`: the indexes of sound effects, which land on the end of the word before
    them (that part's trailing silence cut, no gap; their own leading silence cut) and leave 0.1 s after: (2026-10-26,
    the producer) 'Information<snort> for the Horde', not 'information... <snort>... for the Horde'"""
    n = len(parts); inp = sum((['-i', p] for p in parts), [])
    gap = lambda i: 0 if i + 1 in sounds else 0.1 if i in sounds else 0.35
    flt = ''.join(f'anullsrc=r=24000:cl=mono,atrim=0:{gap(i)}[s{i}];' for i in range(n - 1) if gap(i))
    pre = lambda i: (TRIM_END + ',' if i + 1 in sounds else '') + \
        ('silenceremove=start_periods=1:start_threshold=-45dB,' if i in sounds else '')
    flt += ''.join(f'[{i}:a]aresample=24000,aformat=channel_layouts=mono,{pre(i)}anull[a{i}];' for i in range(n))
    k = n + sum(1 for i in range(n - 1) if gap(i))
    flt += ''.join(f'[a{i}]' + (f'[s{i}]' if i < n - 1 and gap(i) else '') for i in range(n)) + f'concat=n={k}:v=0:a=1,loudnorm=I=-18:TP=-1.5[o]'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *inp, '-filter_complex', flt, '-map', '[o]', '-ar', '24000', '-b:a', '128k', dst], check=True)

# ---------------------------------------------------------------- one line
NARRATOR_ROW = {'npc_id': 'go:narrator', 'race': 'unknown', 'sex': 'male', 'clone_ref': 'design:narrator'}

def beat_emotion_text(d, b):
    """the director's own words for a beat: its style's description and the line's subtext"""
    if b.get('emotion'):                            # the director's own words for this beat (2026-10-12)
        return b['emotion']
    return f"{STYLES[b['style']][0]}. {d.get('subtext') or d.get('note') or ''}".strip()

SPEAKER_ROW = None   # npc id -> that character's casting row as rendered (overnight.py sets it); for a beat's 'speaker'

def render_line(row, d, dst, seed=1, emotion='text', texts=None):
    # per-voice settings from the casting (2026-10-13): a voice cloned from a raid boss's yells reads calmer with the
    # style clip as its emotion at a fixed strength (V2: Freya, Chu'a'lor, Hydraxis); pause_cap trims long gaps
    emotion = row.get('emotion_mode') or emotion
    fixed_alpha = float(row['alpha_fixed']) if row.get('alpha_fixed') else None
    # emotion='text' (2026-10-12, the producer's pick after the Billy/Maybell tests): the director's per-beat emotion
    # phrase is IndexTTS-2's emotion (QwenEmotion); 'clip' = the style's reference performance, as before
    # (2026-10-12) the director marks text nobody speaks -- a scene described, the hero's actions narrated -- as
    # voice "narrator": the storyteller reads it, not the quest giver (Anilia's "Judging by the gaping wound...")
    if d.get('voice') == 'narrator':
        row = dict(row, **NARRATOR_ROW)
    # texts: (2026-10-31) the beats' words given, already as read (a race/class sentence, variants.py), not the quest's
    given = texts is not None
    beats = d['beats']; texts = texts if given else beat_texts(row['questId'], row['kind'], row['variant'], beats)
    is_narrator = row['npc_id'].startswith(('go:', 'item:'))      # NARRATOR_ROW too: he keeps his old emotion scale
    spk = speaker_ref(row); sex = row['sex'] if row['sex'] in ('male', 'female') else 'male'
    tag = os.path.basename(dst).rsplit('.', 1)[0]
    if not given: texts = [scripted(t) for t in texts]          # scripts.json readings, sentence by sentence
    accent = VOICE_CAST.get(row['npc_id'], {}).get('accent', 'neutral')
    # each beat: speech, with any sound effects written into the text spliced in where they stand
    order, say_parts, say_texts = [], [], []
    # (2026-10-13) a stage direction in a beat is the narrator's, spliced in where it stands; not paced with the speech
    pieces = [(i, b, what, x) for i, (t, b) in enumerate(zip(texts, beats)) for what, x in split_stage(t)]
    for k, (i, b, kind_, t) in enumerate(pieces):
        if kind_ == 'stage':
            order.append(('stage', render_stage(t, row['questId'], f'{tag}_{i}_s{k}', seed))); continue
        # (2026-10-31, the producer) a beat may be another character's words inside the line: Buzzbox 827's narration
        # quotes Wizbang ("Hello? Uhh... Hello! You fixed it!"), which the narrator had read. The beat's 'speaker' (an
        # npc id) is voiced with that character's own casting (SPEAKER_ROW, set by the runner)
        brow = SPEAKER_ROW(b['speaker']) if b.get('speaker') and SPEAKER_ROW else None
        b_row, b_spk, b_narr = (brow, speaker_ref(brow), False) if brow else (row, spk, is_narrator)
        b_sex = b_row['sex'] if b_row['sex'] in ('male', 'female') else 'male'
        b_alpha = (float(b_row['alpha_fixed']) if b_row.get('alpha_fixed') else None) if brow else fixed_alpha
        b_accent = VOICE_CAST.get(b_row['npc_id'], {}).get('accent', 'neutral') if brow else accent
        for j, (what, x) in enumerate(split_sounds(inline_markers(t), b_row['race'], b_sex)):
            j = f'{k}{j}'
            if what == 'sound':
                order.append(('sound', x)); continue
            # (2026-10-18, the producer's blind floor test) a woman's beat is read at least at 5 -- her '!' kept -- and at
            # strength 0.7: at the director's usual 4 a third of the women came out flat (12 of 37 in the samples; men
            # 2 of 39), and in the test this setting or the floor alone beat the old one on 7 of 8 lines, good women too
            woman = b_row['sex'] == 'female' and not b_narr
            inten = max(5, b.get('intensity') or 5) if woman else b.get('intensity')
            # -- up to 5 only: above it, the usual scale (sample 3: Proudhorn's urgent 6 at 0.7, "way too frantic")
            alpha = b_alpha or (WOMAN_ALPHA if woman and inten <= 5 else alpha_for(inten) if not b_narr else alpha_was(inten))
            p = render_beat(asked(speakable(calm(x, inten), b_accent, dialect_of(b_row))), b_spk, style_clip(b['style'], b_sex, b_row['race']),
                            f'{tag}_{i}_{j}', seed=seed, alpha=alpha, emo_text=beat_emotion_text(d, b) if emotion == 'text' else None)
            order.append(('say', len(say_parts))); say_parts.append(p); say_texts.append(x)
    paced = even_pace(say_parts, say_texts)
    # (2026-10-16) a morphed voice with narration in its line: only the speaker's parts are morphed (OOX-22/FE's robot
    # filter had reached the narrator too); the speech check hears the plain join
    # (2026-10-26) and a sound effect is not morphed either: beast_growl's octave under Mangletooth's snort made it a grumble
    split_morph = row.get('morph') and any(what in ('stage', 'sound') for what, _ in order)
    sounds = {i for i, (what, _) in enumerate(order) if what == 'sound'}
    if split_morph:
        import morph_presets
        join([x if what != 'say' else paced[x] for what, x in order], dst[:-4] + '.check.mp3', sounds)
        morphed = []
        for k, p in enumerate(paced):
            m = f'{p.rsplit(".", 1)[0]}_morph.wav'; morph_presets.morph(p, m, row['morph']); morphed.append(m)
        paced = morphed
    join([x if what != 'say' else paced[x] for what, x in order], dst, sounds)
    if row.get('pause_cap') == 'one_long':  # undead men: one long pause kept, the rest shortened (2026-10-14)
        one_long_pause(dst)
    elif row.get('pause_cap'):              # the Bone Witch: gaps over 0.45 s cut to 0.3 s (approved 2026-10-13)
        tmp = dst + '.gaps.mp3'; os.replace(dst, tmp)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-af', 'silenceremove=stop_periods=-1:stop_duration=0.45:'
                        'stop_threshold=-32dB:stop_silence=0.3', '-b:a', '128k', dst], check=True); os.remove(tmp)
    floor = row.get('pace_floor') or PACE_FLOOR
    if floor: pace_up(dst, ' '.join(texts), float(floor))
    import stretch_sounds                   # drawn-out sounds ("Ssstrike", "sorrrrrowful"): the sound itself, stretched
    if stretch_sounds.words_in(' '.join(texts)):
        subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.venv', 'bin', 'python'), '-W', 'ignore',
                        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stretch_sounds.py'), os.path.abspath(dst), ' '.join(texts)],
                       env=dict(os.environ, CUDA_VISIBLE_DEVICES=''), check=False)
    if row.get('morph') and not split_morph:  # a novelty morph on the finished line (morph_presets.py; approved 2026-10-13)
        # the speech check listens to the line BEFORE the morph: a beast growl hides the words from the recognizer
        # (Stanley scored 0.00, Umpi was heard as "Ribbage" -- 2026-10-14), not from a player who knows the voice
        shutil.copy(dst, dst[:-4] + '.check.mp3')
        import morph_presets
        tmp = dst + '.plain.mp3'; os.replace(dst, tmp); morph_presets.morph(tmp, dst, row['morph']); os.remove(tmp)
    if row['clone_ref'].endswith('_child'):      # child lines: de-ess the finished line, never the reference (2026-10-12)
        tmp = dst + '.raw.mp3'; os.replace(dst, tmp)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-af', 'deesser=i=0.5:m=0.5:f=0.5:s=o', '-b:a', '128k', dst], check=True)
        os.remove(tmp)
    return ' / '.join(f"[{b['style']}]" for b in beats[:len(texts)])

if __name__ == '__main__':
    quests = set(open(args_get('--quests')).read().split())
    D = {}
    for l in open(args_get('--directions')):
        x = json.loads(l)
        if 'error' not in x: D[x['questId']] = x
    compare = '--compare' in sys.argv; listen = args_get('--listen')
    # start on an empty card: Voice Design (or anything else) left loaded beside IndexTTS-2 and the pinned Gemma
    # ran card 1 out of memory on the longest lines (pilot, 2026-10-11)
    requests.post(URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)
    os.makedirs('render', exist_ok=True); os.makedirs('render_compare', exist_ok=True)
    rows = [r for r in csv.DictReader(open('plan_v3.csv')) if r['questId'] in quests and r['npc_id'] != 'none']
    jobs = [(r, False) for r in rows if r['action'] == 'generate'] + ([(r, True) for r in rows if r['action'] == 'reuse'] if compare else [])
    jobs.sort(key=lambda j: (j[0]['npc_id'], int(j[0]['questId'])))       # one speaker at a time
    index = []; t0 = time.time(); done = 0
    for r, ours_of_reused in jobs:
        name = f"{r['questId']}-{r['kind']}" + (f"-{r['variant']}" if r['variant'] else '')
        d = D.get(r['questId'], {}).get(r['kind'])
        if not d: print('!! no direction', name, flush=True); continue
        dst = f"{'render_compare' if ours_of_reused else 'render'}/{name}.mp3"
        try:
            if not os.path.exists(dst): render_line(dict(r, _ours=ours_of_reused), d, dst)
        except Exception as e:
            print('!!', name, r['npc_name'], str(e)[:300], flush=True); continue
        done += 1
        print(f"{done}/{len(jobs)} {name} {r['npc_name']} {'(ours vs pack)' if ours_of_reused else ''} {time.time() - t0:.0f}s", flush=True)
        if listen:
            who = re.sub(r'[^A-Za-z0-9]+', '_', r['npc_name'] or 'unknown').strip('_')
            os.makedirs(f'{listen}/{who}', exist_ok=True)
            shutil.copy(dst, f"{listen}/{who}/{name}_{'ours' if ours_of_reused else 'new'}.mp3")
            if ours_of_reused:
                ext = r['file_in_pack'].rsplit('.', 1)[1]
                pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", f"{listen}/{who}/{name}_pack.{ext}")
            index.append(f"{who}/{name}  {r['npc_name']}  [{r['kind']}] {d['note']}  "
                         + ' / '.join(b['style'] for b in d['beats'])
                         + (f"  -- pack: {r['source_pack']}" if ours_of_reused else f"  -- voice: {r['clone_ref'].split(':')[0]}"))
    if listen: open(f'{listen}/INDEX.txt', 'w').write('\n'.join(sorted(index)) + '\n')
    print('done', done, 'of', len(jobs), f'in {time.time() - t0:.0f}s')
