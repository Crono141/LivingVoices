"""The overnight voice-over run (2026-10-12): every generated line in the plan, rendered 1-9 AM on both cards.

A SQLite queue (data/overnight.sqlite) holds one row per line. Each night:
  - a director thread asks the pinned Gemma (arbiter 8101, direct.direct) to direct the quests whose lines are
    still undirected; their lines become 'todo' (directions appended to data/directions.jsonl);
  - the director first casts the quest's speakers who have no designed voice description yet (Gemma,
    design_voices.cast -> voice_cast.json) and writes each new speaker's producer's note from its own dialogue and
    what others say of it (actor_read.ensure -> actor_notes.json); every beat it directs carries an emotion phrase,
    which the renderer gives IndexTTS-2 as the emotion (render.render_line emotion='text');
  - two render workers, one per card -- card 1 on the voice-over's own ComfyUI (tools/comfy2.sh, 42422), card 0
    on the user's ComfyUI through the arbiter (42400) -- claim 'todo' lines and render them with render.render_line
    into data/render/. A line whose designed voice does not exist yet waits; when no ready line is left, the worker
    designs a batch of missing voices on card 1 (Qwen3 Voice Design from the casting, as design_voices.py does), freeing the
    card between Voice Design and IndexTTS-2 (the two together ran card 1 out of memory). Card 0's worker never submits while anyone else's job is queued or running there;
  - at the window's end the workers finish the line in hand, both ComfyUIs are told to /free, card 1's is stopped;
  - a speech-recognition check (check_renders' scoring, card 1) scores the night's lines; a line under 0.85 goes
    back to 'todo' with the next seed (six seeds, then 'review'; first takes before retakes), and a report lands in data/overnight_reports/.
    When the queue runs dry before the window closes, the check runs then and the workers start again on its retakes
    (while 20 minutes or more are left), as many rounds as the night allows.

Run from data/ with the ComfyUI venv:
  ~/ComfyUI/venv/bin/python ../tools/overnight.py enqueue [--quests <file>] [--directions <jsonl> ...]
  ~/ComfyUI/venv/bin/python ../tools/overnight.py run [--until 09:00] [--cards 0,0b,1] [--force]   (the timer's job)
  ~/ComfyUI/venv/bin/python ../tools/overnight.py status
  ~/ComfyUI/venv/bin/python ../tools/overnight.py check                (normally run by 'run' at the end)
Enable with tools/systemd/ (see the README there); nothing runs until the timer is enabled.
"""
import concurrent.futures as cf, csv, datetime as dt, json, os, shutil, sqlite3, subprocess, sys, threading, time, urllib.request, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV

# OVERNIGHT_DB / OVERNIGHT_DIRECTIONS point a test at its own queue and directions; OVERNIGHT_DATA at its own data folder
DB = os.environ.get('OVERNIGHT_DB', 'overnight.sqlite'); DIRECTIONS = os.environ.get('OVERNIGHT_DIRECTIONS', 'directions.jsonl')
REPORTS = 'overnight_reports'
CARDS = dict(LV.RENDERERS)      # (2026-11-01) card 0's second renderer, the voice-over's own (comfy2.sh 0b)
OWN = dict(LV.OWN_RENDERERS)                    # renderers whose ComfyUI the run starts and stops (comfy2.sh [instance])
VO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START, END = '01:00', '09:00'
GOOD, SEEDS = 0.85, 6
ODD_MIN = 0.5          # seconds: a shorter pause is never an odd one (the producer, 2026-10-26)
MIN_ROUND = dt.timedelta(minutes=20)    # less time than this left after a mid-night check: the retakes wait for the next night
# a take still slower than this after the gap cut and the speed-up (words a second) is a failed take and gets the next
# seed -- unless the text itself is halting (two or more "..."), when the slowness is the dialogue's (the producer, 2026-10-14;
# Bethor Iceshard's 405 drew every word out, 1.6 w/s, over one "...")
SLOW_TAKE, HALTING, SLOW_MIN_WORDS = 2.0, 2, 10     # a short line ("Yes?") is all lead-in and tail: not judged
# (2026-11-02) a race/class clip is slow only when it is also slower than CLIP_SLOW of its own take's pace: 878's and 5045's
# takes (a snorting quillboar, 1.7-1.9 w/s) were approved at that pace, and their clips matched it
CLIP_SLOW = 0.85
_lock = threading.Lock()

def db():
    c = sqlite3.connect(DB, timeout=60, isolation_level=None)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute("""CREATE TABLE IF NOT EXISTS lines (name TEXT PRIMARY KEY, questId TEXT, kind TEXT, variant TEXT,
                 npc_id TEXT, npc_name TEXT, words INTEGER, status TEXT, seed INTEGER DEFAULT 1, tries INTEGER DEFAULT 0,
                 card TEXT, secs REAL, audio_s REAL, score REAL, heard TEXT, err TEXT, night TEXT, updated TEXT)""")
    c.execute('CREATE INDEX IF NOT EXISTS st ON lines(status, questId)')
    c.execute("CREATE TABLE IF NOT EXISTS voices (key TEXT PRIMARY KEY, status TEXT, card TEXT, err TEXT, updated TEXT)")
    # (2026-10-25) every take the check scores, kept: a line that fails all its seeds goes to review with its best take
    # (the producer: "take the highest score of each and review those"). raw = the recognizer's score before a fault
    # caps it under GOOD; faults = how many (odd pauses, dropped words), the tie-break
    c.execute("""CREATE TABLE IF NOT EXISTS takes (name TEXT, seed INTEGER, raw REAL, fault TEXT, faults INTEGER, heard TEXT,
                 night TEXT, path TEXT, created TEXT, PRIMARY KEY (name, seed))""")
    # (2026-10-26) a line sent back after review gets six new seeds (7-12): the old ones would render the same takes
    # again wherever its text and voice are unchanged. last_seed is where it goes to review; empty = SEEDS
    if 'last_seed' not in [r[1] for r in c.execute('PRAGMA table_info(lines)')]:
        c.execute('ALTER TABLE lines ADD COLUMN last_seed INTEGER')
    return c

# the queue's seed column counts attempts (1, 2, 3...); the model's seed is drawn from the line and the attempt, so
# no two lines share their starting point and a take can still be rendered again exactly (2026-10-15: every line's
# first take had been seed 1, its retries 2 and 3)
def take_seed(name, attempt): return zlib.crc32(f'{name}:{attempt}'.encode()) % (2 ** 31 - 1) + 1

def now(): return dt.datetime.now().isoformat(timespec='seconds')
def name_of(r): return f"{r['questId']}-{r['kind']}" + (f"-{r['variant']}" if r['variant'] else '')
def night_of(t=None):
    t = t or dt.datetime.now(); return (t - dt.timedelta(hours=12)).date().isoformat()    # the night it began

# (2026-10-12, the producer) EVERY line is ours now: in his A/B our renders beat the community packs. A line the plan
# used to reuse from a pack is generated like the rest, its speaker cloned from that speaker's longest pack recording
# (one reference per speaker, so all its lines share a voice -- the voice players know from the packs, no design).
# Objects and items the packs read keep that recording (as_generated -> None).
_PACK_REF = None
def pack_refs():
    """npc_id -> the pack recording a speaker is cloned from: the longest -- or for a woman, of her recordings of 25+
    words, the one whose pitch moves most (ref_spread.json; 2026-10-18, the producer's blind test: the livelier
    recording won all four, Modera to excellent -- a clone copies its reference's range)"""
    global _PACK_REF
    if _PACK_REF is None:
        spread = json.load(open('ref_spread.json')) if os.path.exists('ref_spread.json') else {}
        best = {}
        for r in csv.DictReader(open('plan_v3.csv')):
            if r['action'] == 'reuse' and r['npc_id'] != 'none' and r['source_pack'] and r['file_in_pack']:
                w = int(r['words'] or 0); ref = f"{r['source_pack']}:{r['file_in_pack']}"
                s = spread.get(ref) if r['sex'] == 'female' and w >= 25 else None
                key = (s is not None, s or 0, w)
                if r['npc_id'] not in best or key > best[r['npc_id']][0]:
                    best[r['npc_id']] = (key, ref)
        _PACK_REF = {k: v[1] for k, v in best.items()}
    return _PACK_REF

# (race, sex) whose pack recordings beat our clones of them (the producer, 2026-10-13: the accent survives only in the
# pack's own take): their reused lines play the pack and are not rendered; their other lines are cloned from the pack
# voice as the plan says
# (2026-10-29, for the release) Empty: the packs give no permission to redistribute their audio (SpeakStone has no
# licence at all; Spoken Quests' MIT covers its code, not the audio), so every line ships in our own voice. Was: troll,
# dwarf and orc women (10-13, 10-17: our clones lost all texture) and forest troll men (10-18).
KEEP_PACK = set()
OWN_PACK_VOICE = {('Orc', 'female')}

# (2026-10-13) race_cast.py: trolls, tauren, undead, dwarves and goblins voiced from Blizzard's own recordings, cast
# per NPC from the voices the producer approved in the bake-off; npc_id -> {ref, tempo (the finished line's speed)}
# each known-slow voice's speaking-rate floor (render.pace_up; words a second): where Wilhelm and Maywiki sounded
# right. Tauren were approved at their own pace; everything else is not measured at all
PACE_FLOOR_BY_SRC = {'dwarf': 2.7, 'troll': 2.7, 'tauren': 2.3}     # tauren: approved at their own, slower pace
_RACE_CAST = None
def race_cast():
    global _RACE_CAST
    if _RACE_CAST is None:
        _RACE_CAST = json.load(open('race_cast.json')) if os.path.exists('race_cast.json') else {}
    return _RACE_CAST

_MORPHS = None
def as_generated(r):
    """a plan row as we render it, with its speaker's own morph (morphs.json: the ghost check's filters, 2026-10-16)"""
    global _MORPHS
    if _MORPHS is None:
        _MORPHS = json.load(open('morphs.json')) if os.path.exists('morphs.json') else {}
    g = _as_generated(r)
    return dict(g, morph=_MORPHS[g['npc_id']]) if g and g['npc_id'] in _MORPHS else g

def _as_generated(r):
    """a plan row as we render it: a reused line becomes ours, cloned from its speaker's pack voice"""
    if r['action'] == 'reuse' and (r['race'], r['sex']) in KEEP_PACK:
        return None
    # (2026-10-29, the producer, ours against the pack) orc women are cloned like troll women: each from her own pack
    # voice. Vlagga's one clip, pitch-shifted for every orc woman (race_cast, 10-17), came out "completely flat, every
    # one"; she keeps it, and so do the few with no pack recording of their own
    if (r['race'], r['sex']) in OWN_PACK_VOICE and r['npc_name'] != 'Vlagga Freyfeather' and pack_refs().get(r['npc_id']):
        return dict(r, action='generate', clone_ref=pack_refs()[r['npc_id']])
    rc = race_cast().get(r['npc_id'])
    if rc and not r['clone_ref'].startswith('game:'):
        return dict(r, action='generate', clone_ref=rc.get('clone_ref') or f"game:{rc['ref']}", pace_floor=PACE_FLOOR_BY_SRC.get(rc['src'].split('_')[0]),
                    **{k: rc[k] for k in ('emotion_mode', 'alpha_fixed', 'pause_cap', 'morph') if rc.get(k)})
    if r['action'] != 'reuse':
        return r
    if r['npc_id'].startswith(('go:', 'item:')):
        # a pack-read object or item keeps the pack's own recording: the pack's narrator IS our narrator now (his
        # reading, cloned, is designed_voices/narrator.mp3), and his take reads the poster's breaks right ("Wanted:
        # Hogger. A huge gnoll...") -- the producer, 2026-10-12. (2026-10-29) For the release he reads it in our render
        # too: the pack's recording may not be redistributed (KEEP_PACK).
        return dict(r, action='generate', clone_ref='design:narrator')
    ref = pack_refs().get(r['npc_id'])
    return dict(r, action='generate', clone_ref=ref) if ref else None

def load_directions(paths):
    D = {}
    for p in paths:
        if not os.path.exists(p): continue
        for l in open(p):
            x = json.loads(l)
            if 'error' not in x: D[x['questId']] = x
    return D

# ---------------------------------------------------------------- enqueue
def enqueue(quests=None, extra_dirs=()):
    """every generated line (or those of the listed quests); a line whose render exists is 'done', a directed one
    'todo', the rest 'new'. Directions from other files (the pilot's) are copied into directions.jsonl."""
    c = db(); D = load_directions([DIRECTIONS]); add = load_directions(extra_dirs)
    with open(DIRECTIONS, 'a') as f:
        for q, x in add.items():
            if q not in D: f.write(json.dumps(x) + '\n'); D[q] = x
    n = {'new': 0, 'todo': 0, 'done': 0}
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['npc_id'] == 'none' or (quests and r['questId'] not in quests): continue
        r = as_generated(r)
        if not r: continue
        nm = name_of(r)
        st = 'done' if os.path.exists(f'render/{nm}.mp3') else 'todo' if r['kind'] in D.get(r['questId'], {}) else 'new'
        cur = c.execute('INSERT OR IGNORE INTO lines (name, questId, kind, variant, npc_id, npc_name, words, status, updated) '
                        'VALUES (?,?,?,?,?,?,?,?,?)', (nm, r['questId'], r['kind'], r['variant'], r['npc_id'],
                                                       r['npc_name'], int(r['words'] or 0), st, now()))
        if cur.rowcount: n[st] += 1
    print('queued', n)

# ---------------------------------------------------------------- the window
def until_dt(hhmm):
    h, m = map(int, hhmm.split(':')); t = dt.datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > dt.datetime.now() else t + dt.timedelta(days=1)

def in_window():
    t = dt.datetime.now().strftime('%H:%M'); return START <= t < END

# ---------------------------------------------------------------- director
def director(stop_at, workers=6):
    """direct the undirected quests, a few at a time, until the window closes or none are left"""
    import direct, design_voices, actor_read
    c = db()
    # directed lines (an earlier night's, or another file's) whose speakers were never cast: cast them first
    qs = {r[0] for r in c.execute("SELECT DISTINCT questId FROM lines WHERE status='todo'")}
    if qs:
        try: design_voices.cast(qs)
        except Exception as e: print('!! casting:', str(e)[:300], flush=True)
    while dt.datetime.now() < stop_at:
        qs = [r[0] for r in c.execute("SELECT DISTINCT questId FROM lines WHERE status='new' ORDER BY CAST(questId AS INT) LIMIT ?",
                                      (workers * 4,))]
        if not qs: return
        try: design_voices.cast(set(qs))       # speakers who need a designed voice get their casting first
        except Exception as e: print('!! casting:', str(e)[:300], flush=True)
        # (2026-10-12) the producer's note for each speaker, read from its own dialogue (actor_read.py), before its
        # quests are directed -- the director reads it with the character's profile
        try:
            speakers = {r['npc_id'] for r in csv.DictReader(open('plan_v3.csv')) if r['questId'] in set(qs)}
            direct.ACTOR_NOTES.update(actor_read.ensure(speakers))
        except Exception as e: print('!! notes:', str(e)[:300], flush=True)
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(direct.direct, q): q for q in qs}
            for fu in cf.as_completed(futs):
                q = futs[fu]
                try:
                    x = {'questId': q, **fu.result()}
                    with _lock, open(DIRECTIONS, 'a') as f: f.write(json.dumps(x) + '\n')
                    for kind in [k for k, v in x.items() if isinstance(v, dict)]:
                        c.execute("UPDATE lines SET status='todo', updated=? WHERE questId=? AND kind=? AND status='new'", (now(), q, kind))
                    # a kind with no direction had nothing to speak: the whole text is a stage direction
                    # ("<King Magni slams his fist down in anger.>") -- all 24 of the first night's (2026-10-13)
                    c.execute("UPDATE lines SET status='silent', err='nothing to speak: a stage direction only', updated=? "
                              "WHERE questId=? AND status='new'", (now(), q))
                except Exception as e:
                    c.execute("UPDATE lines SET status='dir_failed', err=?, updated=? WHERE questId=? AND status='new'",
                              (str(e)[:300], now(), q))

# ---------------------------------------------------------------- render worker (one process per card)
def others_busy(url):
    """anything queued or running on that ComfyUI -- on card 0 that is the user's own work: wait for it"""
    try: q = json.load(urllib.request.urlopen(url + '/queue', timeout=10))
    except Exception: return True
    return bool(q.get('queue_running') or q.get('queue_pending'))

def user_busy():
    """a job of the user's own (not ours: render.CLIENT_ID) on card 0's ComfyUI -- card 0's second renderer waits for it"""
    try: q = json.load(urllib.request.urlopen(CARDS['0'] + '/queue', timeout=10))
    except Exception: return True
    return any(not (len(j) > 3 and isinstance(j[3], dict) and j[3].get('client_id') == 'livingvoices')
               for j in q.get('queue_running', []) + q.get('queue_pending', []))

def free(url):
    try:
        urllib.request.urlopen(urllib.request.Request(url + '/free', data=json.dumps({'unload_models': True, 'free_memory': True}).encode(),
                                                      headers={'Content-Type': 'application/json'}), timeout=60)
    except Exception as e: print(f'[{url}] /free failed: {e}', flush=True)

# (2026-10-20) the night's first check runs before any render, and only a ComfyUI render makes the arbiter clear the
# cards: at 01:00 a 27B model (29 GB) still held them, and Whisper died of out-of-memory. The pinned Gemma stays.
ARBITER, PINNED = LV.LLM_URL, LV.LLM_PINNED
def free_llms():
    try:
        for m in json.load(urllib.request.urlopen(ARBITER + '/models', timeout=10))['data']:
            if m['id'] not in PINNED and m.get('status', {}).get('value') == 'loaded':
                urllib.request.urlopen(urllib.request.Request(ARBITER + '/models/unload', data=json.dumps({'model': m['id']}).encode(),
                                                              headers={'Content-Type': 'application/json'}), timeout=120)
                print(f'unloaded {m["id"]} for the speech check', flush=True)
    except Exception as e: print(f'!! could not ask the arbiter to unload its models: {e}', flush=True)

def voice_key(r):
    """the designed voice a line needs (render.speaker_ref's rule), or None when it clones from a pack/game clip"""
    if not r['clone_ref'].startswith('design:'): return None
    if r['npc_id'].startswith(('go:', 'item:')) or (r['race'] == 'unknown' and not r['clone_ref'].endswith('_child')): return 'narrator'
    return r['npc_id']

def voice_ready(key): return key is None or os.path.exists(f'designed_voices/{key}.mp3')

def load_cast():
    for _ in range(5):
        try: return json.load(open('voice_cast.json'))
        except (ValueError, OSError): time.sleep(2)            # the director is mid-write
    return {}

def design_batch(card, c, keys, url, n=20):
    """design up to n missing voices (claimed in the voices table so the two cards never design the same one)"""
    import render
    cast = load_cast(); made = 0; claimed = False
    for key in keys:
        if made >= n: break
        if key not in cast: continue
        c.execute("INSERT OR IGNORE INTO voices (key, status, updated) VALUES (?, 'todo', ?)", (key, now()))
        if not c.execute("UPDATE voices SET status='designing', card=?, updated=? WHERE key=? AND status IN ('todo') RETURNING key",
                         (card, now(), key)).fetchone(): continue
        if not claimed: free(url); claimed = True          # IndexTTS-2 out before Voice Design comes in
        k = cast[key]
        wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
                  'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
                  'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
              '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0],
                  'voice_description': k['description'], 'reference_text': k['reference_text'], 'language': 'English',
                  'character_name': f'wow_npc_{key}', 'overwrite_character': True}},
              '3': {'class_type': 'SaveAudio', 'inputs': {'audio': ['2', 1], 'filename_prefix': f'{render.PREFIX}voice_test/designed/parts/{key}'}}}
        try:
            src = render.comfy(wf)
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-ac', '1', '-ar', '24000', '-b:a', '192k',
                            f'designed_voices/{key}.mp3'], check=True)
            c.execute("UPDATE voices SET status='done', updated=? WHERE key=?", (now(), key)); made += 1
        except Exception as e:
            c.execute("UPDATE voices SET status='failed', err=?, updated=? WHERE key=?", (str(e)[:300], now(), key))
            c.execute("UPDATE lines SET status='failed', err=? WHERE status='todo' AND npc_id=?", ('voice design failed', key))
    if claimed: free(url)                                  # and Voice Design out again before rendering
    return made

ABORT_AFTER = 5

def work(card, stop_at):
    import render
    url = CARDS[card]; render.use_server(url); c = db()
    rows = {name_of(r): g for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] != 'none' and (g := as_generated(r))}
    # (2026-10-31) race/class sentences (variants.py): each renders as its base line's speaker, one sentence long
    VAR = json.load(open('variants.json')) if os.path.exists('variants.json') else {}
    rows.update({vn: rows[x['base']] for vn, x in VAR.items() if x['base'] in rows})
    by_npc = {}
    for g in rows.values(): by_npc.setdefault(g['npc_id'], g)
    render.SPEAKER_ROW = by_npc.get                # a beat in another character's voice (render_line, 'speaker')
    D = load_directions([DIRECTIONS]); os.makedirs('render', exist_ok=True)
    free(url)                                   # start on an empty card (Voice Design or a day's models left loaded)
    VBEATS = json.load(open('variant_beats.json')) if os.path.exists('variant_beats.json') else {}
    done = 0; t0 = time.time(); streak = []        # names failed back to back (the producer: 5 in a row -> stop)
    waited = {}                                        # (2026-11-01) seconds slept, by reason: 0b idled ~80 of 330 min by day
    def nap(why, s): waited[why] = waited.get(why, 0) + s; time.sleep(s)
    while dt.datetime.now() < stop_at - dt.timedelta(minutes=2):
        if others_busy(url): nap('own queue busy', 30); continue
        if card == '0b' and user_busy(): nap("user's ComfyUI busy", 30); continue
        # (2026-10-19) every line's first take before any retake, then every second take before a third...: the whole set
        # gets a take early, and the retakes come in batches at the end
        q = c.execute("SELECT name, seed FROM lines WHERE status='todo' ORDER BY seed, CAST(questId AS INT), name LIMIT 3000").fetchall()
        # a name this worker has no row for (queued after it started: a race/class clip planned mid-run killed card 1 with
        # a KeyError, 2026-10-31) waits for the next round's worker, which reads the plan and variants.json again
        cand, seed_of = [n for n, _ in q if n in rows], dict(q)
        ready = [n for n in cand if voice_ready(voice_key(rows[n]))]
        missing = list(dict.fromkeys(voice_key(rows[n]) for n in cand if not voice_ready(voice_key(rows[n]))))
        # (2026-10-24) a missing voice that holds back an earlier take than the next ready line (2,835 first takes behind
        # 448 undesigned voices while the cards rendered retakes: the retakes counted as "ready", so the 150-line
        # trigger never fired for two nights) is designed now, not when the ready lines run low
        ahead = bool(missing) and (not ready or any(seed_of[n] < seed_of[ready[0]] for n in cand
                                                     if not voice_ready(voice_key(rows[n]))))
        if card == '1' and missing and (len(ready) < 150 or ahead):     # design ahead, so card 0 never runs dry
            made = design_batch(card, c, missing, url)
            if made: print(f'[card {card}] designed {made} voices', flush=True); continue
        row = None
        for n in ready[:20]:
            row = c.execute("UPDATE lines SET status='running', card=?, updated=? WHERE name=? AND status='todo' RETURNING name, seed",
                            (card, now(), n)).fetchone()
            if row: break
        if not row:
            # Voice Design runs on card 1 only: card 0's ComfyUI (the user's service) cannot load torchcodec's FFmpeg
            # libraries (system FFmpeg 9; torchcodec takes 4-8), so the designer's save fails there (2026-10-12)
            if missing and card == '1':
                made = design_batch(card, c, missing, url)
                if made: print(f'[card {card}] designed {made} voices', flush=True); continue
                nap('voices not designed', 30); continue        # casting not there yet, or the other card is on them
            if missing: nap('waiting for voices', 30); continue  # card 0: wait for card 1 to design them
            if c.execute("SELECT 1 FROM lines WHERE status='new' LIMIT 1").fetchone(): nap('director behind', 20); continue   # director behind
            break
        nm, seed = row; r = rows[nm]
        d = D.get(r['questId'], {}).get(r['kind'])
        if not d: D = load_directions([DIRECTIONS]); d = D.get(r['questId'], {}).get(r['kind'])
        try:
            if not d: raise RuntimeError('no direction')
            s0 = time.time(); dst = f'render/{nm}.mp3'
            if os.path.exists(dst): os.remove(dst)            # a re-take with the next seed
            if nm in VAR:                                     # the sentence alone, read as its beat is directed
                x = VAR[nm]
                # (2026-11-02) read at least at its take's pace (render.take_rate; pace_up's 1.25x cap holds): a clip slower
                # than the take around it was 48 of the 91 on review
                pr = render.take_rate(x['base'])
                # (2026-11-02, the producer's notes) a clip's own emotion where its beat's misfits three words: 12509's
                # "Well done, warlock." cackled, 11585's "Throm-Ka, orc!" lost the orc's gravel (data/variant_beats.json)
                ov = VBEATS.get(nm) or VBEATS.get(f"{x['base']}_s{x['i']}", {})      # the one clip, else its sentence
                render.render_line(dict(r, pace_floor=max(float(r.get('pace_floor') or render.PACE_FLOOR), pr)) if pr else r,
                                   dict(d, beats=[dict(d['beats'][x['beat']], sentences=[1, 1], **ov)]), dst,
                                   seed=take_seed(nm, seed), texts=[x['text']])
            else:
                render.render_line(r, d, dst, seed=take_seed(nm, seed))
            secs = time.time() - s0
            dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', dst],
                                       capture_output=True, text=True).stdout or 0)
            c.execute("UPDATE lines SET status='rendered', secs=?, audio_s=?, night=?, err=NULL, updated=? WHERE name=?",
                      (round(secs, 1), round(dur, 1), night_of(), now(), nm))
            done += 1; streak = []
            if done % 25 == 0: print(f'[card {card}] {done} lines, {time.time() - t0:.0f}s', flush=True)
        except Exception as e:
            c.execute("UPDATE lines SET status=CASE WHEN tries+1 >= 2 THEN 'failed' ELSE 'todo' END, tries=tries+1, err=?, "
                      "updated=? WHERE name=?", (str(e)[:500], now(), nm))
            print(f'[card {card}] !! {nm}: {str(e)[:200]}', flush=True)
            streak.append(nm)
            if len(streak) >= ABORT_AFTER:
                # the card, not the lines (ComfyUI down, out of memory...): stop before the whole queue is marked
                # failed, and give the streak's lines back untouched for the next night
                c.executemany("UPDATE lines SET status='todo', tries=0 WHERE name=?", [(n,) for n in streak])
                msg = f'card {card} STOPPED at {now()}: {ABORT_AFTER} failures in a row; last: {str(e)[:300]}'
                os.makedirs(REPORTS, exist_ok=True); open(f'{REPORTS}/.abort_card{card}', 'w').write(msg)
                print(f'[card {card}] !! {msg}', flush=True); break
    free(url)
    print(f'[card {card}] stopped: {done} lines in {time.time() - t0:.0f}s' + (f'; slept {waited}' if waited else ''), flush=True)

# ---------------------------------------------------------------- check (speech recognition, card 1)
CHECK_WORKERS = 3
LLM_SLOTS_NIGHT, LLM_SLOTS_DAY = 8, 6     # Gemma (8101) has 8 parallel slots; by day the bots' chat keeps 2

def card1_free_mib():
    try:
        return int(subprocess.run(['nvidia-smi', '-i', '1', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                                  capture_output=True, text=True, timeout=20).stdout.split()[0])
    except Exception: return 0

def check():
    """score every 'rendered' line against the text it was meant to say; good -> 'done', else the next seed"""
    c = db(); todo = [r[0] for r in c.execute("SELECT name FROM lines WHERE status='rendered'")]
    if not todo: return {}
    res, odd = score(todo)
    os.makedirs('render/takes', exist_ok=True)
    for nm, r in res.items():
        score_, heard, raw, fault, faults = verdict(r, odd.get(nm))
        rate, halting, words = r[2:5]
        res[nm] = (score_, heard, rate, halting, words)            # counted with the night's retries
        seed, last = c.execute("SELECT seed, last_seed FROM lines WHERE name=?", (nm,)).fetchone()
        keep_take(c, nm, seed, raw, fault, faults, heard)
        if score_ >= GOOD: c.execute("UPDATE lines SET status='done', score=?, heard=?, updated=? WHERE name=?", (score_, heard, now(), nm))
        elif seed < (last or SEEDS):
            c.execute("UPDATE lines SET status='todo', seed=seed+1, score=?, heard=?, updated=? WHERE name=?", (score_, heard, now(), nm))
        else:
            to_review(c, nm)
    return res

def score(todo):
    """the speech check's checkers on render/<name>.mp3 of each name, and the Gemma judge on their pauses -> (res, odd)"""
    free_llms()
    os.makedirs(REPORTS, exist_ok=True)
    libs = ':'.join(sorted(__import__('glob').glob(f'{VO}/.venv/lib/python3*/site-packages/nvidia/*/lib')))
    # (2026-11-01) several checkers on card 1 at once: one keeps a CPU core busy and the card at ~16%. Each holds ~3.7 GB
    # (Whisper + the aligner); as many as fit beside the pinned Gemma, at most CHECK_WORKERS, one for a short list
    k = 1 if len(todo) < 60 else max(1, min(CHECK_WORKERS, (card1_free_mib() - 1500) // 4000))
    procs = []
    for j in range(k):
        lst = os.path.abspath(f'{REPORTS}/.check_list{j}.txt'); open(lst, 'w').write('\n'.join(todo[j::k]))
        procs.append(subprocess.Popen([f'{VO}/.venv/bin/python', '-W', 'ignore', '-c', CHECK_SRC, lst], stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, cwd=os.getcwd(),
                                      env=dict(os.environ, CUDA_VISIBLE_DEVICES='1', LD_LIBRARY_PATH=libs)))
    print(f'{now()} speech check: {len(todo)} takes on {k} checker(s)', flush=True)
    outs = [(p, *p.communicate()) for p in procs]
    res, errs = {}, []
    for p, so, se in outs:
        # a line the check could not score stays 'rendered'; say why in the log (10579-progress failed silently for two nights)
        for l in se.splitlines():
            if l.startswith(('check failed', 'pause alignment failed', 'delivery check failed', 'stop check failed')): print('!!', l, flush=True)
        if p.returncode: errs.append(se[-1500:]); continue
        res.update(json.loads(so.strip().splitlines()[-1]))
    # a checker that died loses only its share: those lines stay 'rendered' for the next check
    if errs and not res: raise RuntimeError(errs[0])
    for e in errs: print('!! a speech checker failed; its lines wait for the next check:', e[-600:], flush=True)
    # a pause that breaks a phrase (pause_check: aligned to the script, the model judges each one) -- asked only of the
    # takes that pass everything else, all at once
    import pause_check, concurrent.futures as cf
    # (2026-10-26, the producer, after reviewing 686 odd-pause lines: "accept anything under 0.5 seconds") a pause
    # shorter than ODD_MIN is never a fault, whatever the model makes of it
    asks = {nm: [g for g in v[6] if g[0] >= ODD_MIN] for nm, v in res.items() if v[0] >= GOOD and not v[5] and v[6]}
    asks = {nm: g for nm, g in asks.items() if g}
    # (2026-11-01, the producer) each pause its own request, as many at once as Gemma's slots allow: all 8 before 09:00
    # (the night's batch may use them all), 6 after, leaving 2 for the realm's bots chatting by day
    flat = [(nm, g) for nm, gs in asks.items() for g in gs]
    with cf.ThreadPoolExecutor(LLM_SLOTS_NIGHT if dt.datetime.now().hour < 9 else LLM_SLOTS_DAY) as ex:
        verdicts = list(ex.map(lambda x: pause_check.judge([x[1]]), flat))
    odd = {}
    for (nm, _), v in zip(flat, verdicts):
        if v: odd.setdefault(nm, []).extend(v)
    return res, odd

def verdict(r, odd):
    """one take's checker result -> (score, heard, raw, fault, faults): the first fault found holds the score under GOOD"""
    score, heard, rate, halting, words, dropped, _gaps, *more = r
    delivery = more[0] if more else []
    stops = more[1] if len(more) > 1 else []
    misheard = more[2] if len(more) > 2 else []
    prate = more[3] if len(more) > 3 else None      # a race/class clip: its take's pace
    raw, fault, faults = score, (None if score >= GOOD else 'low score'), 0
    if score >= GOOD and rate < (min(SLOW_TAKE, CLIP_SLOW * prate) if prate else SLOW_TAKE) and halting < HALTING and words >= SLOW_MIN_WORDS:
        score, heard = round(min(score, GOOD - 0.001), 3), f'(slow take: {rate} w/s' + (f', its take {prate}' if prate else '') + f') {heard}'
        fault, faults = 'slow', 1
    # a word of the text the take never says (Thazz'ril's "get my pick", 2026-10-18): the letter score passed it at
    # 0.995 -- one word in a hundred -- so a whole word missing is a retake of its own (4 of sample 2's 120)
    elif score >= GOOD and dropped:
        score, heard = round(min(score, GOOD - 0.001), 3), f'(dropped: {", ".join(dropped)}) {heard}'
        fault, faults = 'dropped', len(dropped)
    # an odd pause is a retake like any other fault. (2026-10-19) It used to be kept, noted, on the last seed (107 of
    # the 10-18 night's takes); the producer: "I'd rather increase the seed attempts than keep bad takes" -- so six
    # seeds now, and a line that fails all six goes to review
    elif score >= GOOD and odd:
        score = round(min(score, GOOD - 0.001), 3)
        heard = '(odd pause: ' + '; '.join(f'{a} | {b} {g}s' for g, a, b in odd) + ') ' + heard
        fault, faults = 'odd pause', len(odd)
    elif score >= GOOD and delivery:
        score, heard = round(min(score, GOOD - 0.001), 3), f'(odd delivery: {"; ".join(delivery)}) {heard}'
        fault, faults = 'odd delivery', len(delivery)
    # (2026-10-30, the producer's listening test: 7 of 12 caught needed a retake, 2 took a spliced pause, 3 were fine;
    # "the hard stop is noticeable" on the spliced ones) a stop read through is a retake, never a splice
    elif score >= GOOD and misheard:
        score, heard = round(min(score, GOOD - 0.001), 3), f'(mispronounced: {", ".join(misheard)}) {heard}'
        fault, faults = 'mispronounced', len(misheard)
    elif score >= GOOD and stops:
        score, heard = round(min(score, GOOD - 0.001), 3), f'(missed stop: {"; ".join(stops)}) {heard}'
        fault, faults = 'missed stop', len(stops)
    return score, heard, raw, fault, faults

def keep_take(c, nm, seed, raw, fault, faults, heard):
    """the take just scored, copied to render/takes/ with its score (a retake deletes render/<line>.mp3)"""
    path = f'render/takes/{nm}.s{seed}.mp3'
    if os.path.exists(f'render/{nm}.mp3'): shutil.copy2(f'render/{nm}.mp3', path)
    c.execute("INSERT OR REPLACE INTO takes VALUES (?,?,?,?,?,?,?,?,?)",
              (nm, seed, round(raw, 3), fault, faults, heard, night_of(), path if os.path.exists(path) else None, now()))

def to_review(c, nm):
    """every seed failed: the best take (highest raw score, then fewest faults) becomes the line's file, for a human"""
    # (2026-10-31) only the latest night's takes: an older night's may predate the line's voice or text (26 and 27 came
    # back with a 10-23 take as "best", 983 with one from before Wizbang had his own beat)
    best = c.execute("SELECT seed, raw, fault, heard, path, (SELECT COUNT(*) FROM takes WHERE name=?1 AND night=n.night) "
                     "FROM takes, (SELECT MAX(night) night FROM takes WHERE name=?1) n WHERE name=?1 AND takes.night=n.night "
                     "AND path IS NOT NULL ORDER BY raw DESC, faults, seed LIMIT 1", (nm,)).fetchone()
    if best:
        seed, raw, fault, heard, path, n = best
        shutil.copy2(path, f'render/{nm}.mp3')
        heard = f'(best of {n} takes: seed {seed}, {fault or "no fault"}) {heard}'
        c.execute("UPDATE lines SET status='review', score=?, heard=?, updated=? WHERE name=?", (raw, heard, now(), nm))
    else:
        c.execute("UPDATE lines SET status='review', updated=? WHERE name=?", (now(), nm))

CHECK_SRC = r'''
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath('plan_v3.csv')), '..', 'tools'))
from asr_check import decode_audio, MODEL
from asr_report import rescore
from asr_check import words as wordlist
import difflib, re
import direct, render, pause_check, delivery_check, stop_check
from faster_whisper import WhisperModel, BatchedInferencePipeline
m = BatchedInferencePipeline(WhisperModel(MODEL, device='cuda', compute_type='float16'))
import csv
RACE = {}
for r in csv.DictReader(open('plan_v3.csv')):
    RACE['-'.join(x for x in (r['questId'], r['kind'], r['variant']) if x)] = r
STUTTER = re.compile(r"\b(?:([A-Za-z])(?:-\1)*-(?=\1)|([A-Za-z]{2})(?:-\2)+-(?=\2))", re.I)   # 'w-w-who', not 're-read'
out = {}
VAR = json.load(open('variants.json')) if os.path.exists('variants.json') else {}   # race/class sentences (variants.py)
# (2026-11-01) each take decoded and aligned once: the pause, held-sound and stop checks each aligned the same take to the
# same words, and ffmpeg was started six times a line -- 0.5 s of a short clip's 0.67 s (profiled on 30 race/class clips)
import asr_check, hashlib
_dec, _ali = {}, {}
_decode_audio, _align = asr_check.decode_audio, pause_check.align
def decode_cached(data):
    k = hashlib.blake2b(data, digest_size=16).digest()
    if k not in _dec: _dec[k] = _decode_audio(data)
    return _dec[k].copy()
def align_cached(path, text):
    k = (path, os.path.getmtime(path), text)
    if k not in _ali: _ali[k] = _align(path, text)
    return list(_ali[k])
asr_check.decode_audio, pause_check.align = decode_cached, align_cached
decode_audio = decode_cached
PRATE = {}                                          # a clip's take: words a second (render.take_rate)
def one(nm):
        _dec.clear(); _ali.clear()
        x = VAR.get(nm)
        base = x['base'] if x else nm
        p = base.split('-'); q, kind, v = p[0], p[1], (p[2] if len(p) > 2 else '')
        meant = render.spoken_text(x['text'] if x else render.scripted(render.variant_clean(direct.Q[q][direct.KINDS[kind]] or '', v)))
        src = f'render/{nm}.check.mp3' if os.path.exists(f'render/{nm}.check.mp3') else f'render/{nm}.mp3'   # pre-morph copy
        segs, _ = m.transcribe(decode_audio(open(src, 'rb').read()), language='en', batch_size=16, without_timestamps=True)
        t = ' '.join(s.text.strip() for s in segs)
        if not t.strip():   # the batched pipeline's voice detector can drop a short clip whole (443-progress, 2026-10-15)
            t = ' '.join(s.text.strip() for s in m.model.transcribe(decode_audio(open(src, 'rb').read()), language='en', vad_filter=False)[0])
        written = x['text'] if x else render.variant_clean(direct.Q[q][direct.KINDS[kind]] or '', v)
        halting = written.count('...') + written.count('\u2026')
        rate = render.speech_rate(src, len(meant.split())) if meant.split() else 9.9
        # a dialect speaker (a troll's 'de' for 'the'): both sides spelled the dialect's way, so either hearing counts
        dia = render.dialect_of(RACE.get(base, {}))
        ACCENT = set(render.PRON.get('_dialect', {}).get(dia, {}).get('words', {}).values()) if dia else set()
        # (2026-10-20) a stutter is one word ("s-s-snowy"), not three: the split letters were counted as dropped words
        said = STUTTER.sub('', meant)
        def hear(t):
            t = render.heard_right(t, meant)
            sc = rescore(render.dialect_text(t, dia), render.dialect_text(meant, dia)) if dia else rescore(t, meant)
            # (2026-10-22) a line that is only a stand-in for the player's name ("Adventurer!", 10579-progress) has no
            # words left once the stand-ins are dropped, and its None score failed the check every morning: the letters
            # as written are scored instead
            if sc is None:
                sc = difflib.SequenceMatcher(None, re.sub('[^a-z]', '', t.lower()), re.sub('[^a-z]', '', meant.lower()), autojunk=False).ratio()
            a = wordlist(render.dialect_text(t, dia) if dia else t); b = wordlist(render.dialect_text(said, dia) if dia else said, ours=True)
            dropped = [' '.join(b[j1:j2]) for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op == 'insert']
            # a laugh or a hum is a sound, not a word: the recognizer writes none down ("heh heh heh", "hah", "hm" -- four of
            # the Elwynn pilot's five reviews, 2026-10-18), so a dropped run made only of them is no retake. (2026-10-19) the
            # 10-18 night's check sent 'eh' (7), 'hmph' (4), 'argh' (2), 'ahem', 'aha' and 'shhh' to a retake the same way
            SOUND = re.compile(r'^(h[aeiu]+h+|h*m+|u+[hm]+|e+r+m*|a+h+|o+h+|ha+|(ha){2,}h?|(he){2,}h?|e+h+|h+m+p+h+|a+r+g+h+'
                               r'|a+h+e+m+|a+h+a+|s+h+|u+g+h+|g+r+|b+a+h+|p+a+h+|t+s+k+|h+o+)$')
            dropped = [d for d in dropped if not all(SOUND.match(w) for w in d.split())]
            # (2026-10-20) a troll's quick 'de' (or 'dat', 'wit'...) the recognizer writes as nothing ("You find crystals
            # yet?"): a dropped run made only of the accent's own words is heard; the letter score still holds the take
            return sc, [d for d in dropped if not all(w in ACCENT for w in d.split())]
        sc, dropped = hear(t)
        # (2026-10-20) the batched pipeline's voice detector also cuts a last word after a long pause ("...await you...
        # godslayer!": six takes of the C'Thun lines sent back, the plain recognizer hears "God Slayer"), so a dropped
        # word is listened for again without it, and the hearing that misses less is the one kept
        if dropped:
            t2 = ' '.join(s.text.strip() for s in m.model.transcribe(decode_audio(open(src, 'rb').read()), language='en', vad_filter=False)[0])
            sc2, dropped2 = hear(t2)
            if len(dropped2) < len(dropped): t, sc, dropped = t2, sc2, dropped2
        try: gaps = pause_check.gaps(src, meant)
        except Exception as e: gaps = []; print('pause alignment failed', nm, str(e)[:120], file=sys.stderr)
        # (2026-10-28) a sound held on after a word -- Doctor Serratus' three-second "noooOOOUUEEE?", "jerkinnnnnn",
        # "Apothecarioummmm" -- that the speech check passes: delivery_check, every voice, over 0.75 s a retake
        delivery = []
        try: delivery = delivery_check.report(src, meant)['flag']
        except Exception as e: print('delivery check failed', nm, str(e)[:120], file=sys.stderr)
        # (2026-10-30) a full stop read straight through -- Arcanist Helion's "your power. When you", 8346-accept: the
        # words touch (under 0.1 s) with no silence between them; stop_check, every . ! ? ; : a retake
        stops = []
        try: stops = [f'{s[3]} | {s[4]}' for s in stop_check.missed(src, meant)]
        except Exception as e: print('stop check failed', nm, str(e)[:120], file=sys.stderr)
        # (2026-10-31) a respelled name the speech check passes in any form, read wrong: "Defy us Brotherhood" came out
        # "Defy U.S." -- Whisper writes it with capitals, a good take as "Defy us". pronounce.json _heard_wrong: name ->
        # patterns of the transcript that mean it was read wrong
        misheard = [w for w, pats in render.PRON.get('_heard_wrong', {}).items()
                    if not w.startswith('_') and re.search(rf'\b{re.escape(w)}\b', meant, re.I) and any(re.search(p, t) for p in pats)]
        if x and x['base'] not in PRATE: PRATE[x['base']] = render.take_rate(x['base'])
        prate = PRATE.get(x['base']) if x else None
        out[nm] = (round(sc, 3), t[:300], round(rate, 2), halting, len(meant.split()), dropped, gaps, delivery, stops, misheard,
                   round(prate, 2) if prate else None)

# (2026-10-19) one line's failure no longer loses the night: the results come back as one JSON at the end, so a CUDA
# out-of-memory partway through the 10-18 night discarded every score (3,987 renders left unchecked). A failed line is
# retried once on an emptied cache, then left 'rendered' for the next check.
import torch
todo = open(sys.argv[1]).read().split()
for i, nm in enumerate(todo, 1):
    for attempt in (1, 2):
        try: one(nm); break
        except Exception as e:
            torch.cuda.empty_cache()
            if attempt == 2: print('check failed, left for the next night:', nm, str(e)[:160], file=sys.stderr)
    if i % 500 == 0: print(f'checked {i} of {len(todo)}', file=sys.stderr, flush=True)
print(json.dumps(out))
'''

# ---------------------------------------------------------------- status / report
def status(c=None):
    c = c or db()
    st = dict(c.execute('SELECT status, COUNT(*) FROM lines GROUP BY status').fetchall())
    words_left = c.execute("SELECT COALESCE(SUM(words),0) FROM lines WHERE status IN ('new','todo','running')").fetchone()[0]
    rate = c.execute("SELECT SUM(audio_s), SUM(words), SUM(secs) FROM lines WHERE audio_s > 0").fetchone()
    lines = [f'lines by status: {st}']
    if rate[0]:
        s_per_word = rate[0] / max(rate[1], 1); speed = rate[0] / max(rate[2], 1)
        left_h = words_left * s_per_word / 3600
        lines.append(f'rendered audio so far {rate[0] / 3600:.1f} h at {speed:.2f}x real time per card; '
                     f'~{left_h:.1f} h of speech left = ~{left_h / speed / 2.5 / 8:.1f} nights on three renderers')
    else: lines.append(f'{words_left} words left to render')
    return '\n'.join(lines)

def report(night, res, rounds=1):
    c = db(); os.makedirs(REPORTS, exist_ok=True)
    rows = c.execute("SELECT card, COUNT(*), SUM(audio_s), SUM(secs) FROM lines WHERE night=? GROUP BY card", (night,)).fetchall()
    bad = c.execute("SELECT name, npc_name, score, IFNULL(heard, err) FROM lines WHERE status IN ('review','failed') ORDER BY name").fetchall()
    retry = sum(1 for s, *_ in res if s < GOOD)       # every take the night scored, a line's retakes each counted
    txt = [f'Overnight voice-over, night of {night}', '']
    for card in CARDS:
        f = f'{REPORTS}/.abort_card{card}'
        if os.path.exists(f): txt += ['!! ' + open(f).read(), '']; os.remove(f)
    for card, n, a, s in rows: txt.append(f'card {card}: {n} lines, {(a or 0) / 60:.0f} min of speech in {(s or 0) / 60:.0f} min')
    txt += [f'speech check: {len(res)} scored, {retry} below {GOOD} queued for another seed' +
            (f' ({rounds} rounds: the queue ran dry and retakes were rendered the same night)' if rounds > 1 else ''),
            '', status(c), '']
    if bad: txt += [f'needs a human ({SEEDS} seeds failed the speech check, or the render failed twice):'] + \
                   [f'  {n} {who} {s} | {str(h)[:160]}' for n, who, s, h in bad[:60]] + \
                   ([f'  ... and {len(bad) - 60} more (overnight.py status)'] if len(bad) > 60 else [])
    p = f'{REPORTS}/{night}.txt'; open(p, 'w').write('\n'.join(txt) + '\n'); print('\n'.join(txt), flush=True)

# ---------------------------------------------------------------- run
def run(until=END, cards=('0', '0b', '1'), force=False):
    if not force and not in_window(): print('outside the 1-9 AM window; --force to run anyway'); return
    stop_at = until_dt(until); night = night_of()
    print(f'{now()} overnight run until {stop_at:%H:%M} on cards {",".join(cards)}', flush=True)
    c = db(); c.execute("UPDATE lines SET status='todo' WHERE status='running'")         # a crashed night's leftovers
    c.execute("UPDATE voices SET status='todo' WHERE status='designing'")
    # (2026-10-19) a check that failed last night left its lines 'rendered': score them first, while card 1 is free, so
    # tonight's workers re-render their retakes instead of a whole night passing with no check at all
    res = []
    try: res = list(check().values())
    except Exception as e: print('!! leftover speech check failed:', str(e)[-600:], flush=True)
    d = threading.Thread(target=director, args=(stop_at,), daemon=True); d.start()
    # (2026-10-21) once the first takes are through, the queue empties before 9 AM: score what's rendered then and
    # there and render its retakes the same night, round after round, instead of each round of retakes waiting a night
    rounds = 0
    while True:
        rounds += 1
        here = list(cards)
        for k in [k for k in here if k in OWN]:
            # card 1's instance has to come up (as before); card 0's second one is a bonus: the night goes on without it
            if subprocess.run([f'{VO}/tools/comfy2.sh', 'start', OWN[k]], check=(k == '1')).returncode:
                print(f'!! renderer {k} did not start; rendering without it', flush=True); here.remove(k)
        procs = [subprocess.Popen([sys.executable, '-W', 'ignore', __file__, 'work', card, stop_at.isoformat()]) for card in here]
        for p in procs: p.wait()
        for k in [k for k in here if k in OWN]: subprocess.run([f'{VO}/tools/comfy2.sh', 'stop', OWN[k]])
        try: scored = check()
        except Exception as e: print('!! speech check failed:', str(e)[-600:], flush=True); break
        res += scored.values()
        left = c.execute("SELECT COUNT(*) FROM lines WHERE status='todo'").fetchone()[0]
        # a round that rendered nothing (a worker that died at start, voices that never got designed) would only
        # restart ComfyUI again and again until 9 AM
        if not scored or not left or dt.datetime.now() > stop_at - MIN_ROUND or any(os.path.exists(f'{REPORTS}/.abort_card{k}') for k in cards):
            break
        print(f'{now()} queue ran dry before {stop_at:%H:%M}: scored, {left} retakes, rendering them now', flush=True)
    report(night, res, rounds)

if __name__ == '__main__':
    os.chdir(os.environ.get('OVERNIGHT_DATA', os.path.join(VO, 'data')))
    a = sys.argv[1:]; opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    if a[0] == 'enqueue':
        qs = set(open(opt('--quests')).read().split()) if opt('--quests') else None
        enqueue(qs, [a[i + 1] for i, x in enumerate(a) if x == '--directions'])
    elif a[0] == 'run': run(opt('--until', END), tuple(opt('--cards', '0,0b,1').split(',')), '--force' in a)
    elif a[0] == 'work': work(a[1], dt.datetime.fromisoformat(a[2]))
    elif a[0] == 'check': r = check(); print(len(r), 'scored')
    elif a[0] == 'status': print(status())
