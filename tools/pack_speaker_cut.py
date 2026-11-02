"""Pack-cloned speakers cloned partly from the pack's narrator (2026-10-16, the producer). A speaker the plan reused
from a community pack is cloned from its longest pack recording -- and the packs read a line's narration ("..." she
says, <He looks away.>) in their narrator's voice, so that recording is part narrator (Janice Felstone was mostly
narrator). Each such speaker gets a reference of only their own voice:
  clean    a recording of theirs with no narration in its text, if one runs >= CLEAN_WORDS words
  cut      else their own words cut out of the narrated recordings: Whisper's word times, aligned to the quest text;
           words inside the quotes (or outside <emotes>) are the speaker's; spans joined up to 15 s
  flagged  under MIN_SECS of their own voice, or a text whose quotes may only mark a term: left as they were, listed

  LD_LIBRARY_PATH=<venv nvidia libs> ../.venv/bin/python ../tools/pack_speaker_cut.py run     -> pack_speaker_cut.json + clone_refs/pack_cut_<npc>.flac
  ../.venv/bin/python ../tools/pack_speaker_cut.py apply   -> race_cast.json entries; their done lines re-queued
"""
import csv, datetime, difflib, json, os, re, sqlite3, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import direct, render, overnight as ov

OUT = 'pack_speaker_cut.json'
REVIEW = f'{LV.COMFY_OUT}/voice_test/review_2026-10-16/pack_speaker_cuts'
CLEAN_WORDS, MIN_SECS, MAX_SECS, SR = 15, 5.0, 15.0, 24000
NARRATION_HEARD = 0.6      # share of a recording's narration words Whisper hears in it: read aloud, so cut it out

def raw(questId, kind):
    t = direct.Q.get(questId, {}).get(direct.KINDS[kind]) or ''
    t = render.GPAT.sub(r'\1', t); t = re.sub(r'\$[bB]', ' ', t)
    return re.sub(r'\$[nN]\w*', 'adventurer', re.sub(r'\$[cC]', 'hero', re.sub(r'\$[rR]', 'traveler', t)))

def narrated(t):
    return any(not s for _, s in labelled(t))

def labelled(t):
    """[(word, is_speaker)]: inside the quotes when there are any, never inside <emotes>. Quotes round under a quarter
    of the words mark a term or a name inside the speech (Commander Hobb, Dark Ranger Vorel), not the speech itself"""
    quoted = '"' in t and quoted_share(t) >= 0.25; q = e = False; out = []; cur = ''; lab = None
    def flush():
        nonlocal cur
        if cur: out.append((cur, lab))
        cur = ''
    for ch in t:
        if ch == '"': flush(); q = not q; continue
        if ch == '<': flush(); e = True; continue
        if ch == '>': flush(); e = False; continue
        if ch.isspace(): flush(); continue
        if not cur: lab = (q or not quoted) and not e
        cur += ch
    flush()
    return [(norm(w), s) for w, s in out if norm(w)]

def quoted_share(t):
    parts = re.sub(r'<[^>]+>', ' ', t).split('"')
    inside = sum(len(x.split()) for x in parts[1::2]); return inside / max(1, inside + sum(len(x.split()) for x in parts[::2]))

def norm(w): return re.sub(r'[^a-z0-9]', '', w.lower())

_asr = None
def asr():
    global _asr
    if _asr is None:
        from faster_whisper import WhisperModel
        from asr_check import MODEL
        _asr = WhisperModel(MODEL, device='cuda', compute_type='float16')
    return _asr

def decode(path):
    b = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                       capture_output=True, check=True).stdout
    return np.frombuffer(b, np.float32)

def speaker_spans(path, text):
    """[(start, end)] seconds of the speaker's own words in a pack recording"""
    from asr_check import decode_audio
    segs, _ = asr().transcribe(decode_audio(open(path, 'rb').read()), language='en', word_timestamps=True)
    heard = [w for s in segs for w in s.words if norm(w.word)]
    want = labelled(text)
    sm = difflib.SequenceMatcher(None, [norm(w.word) for w in heard], [w for w, _ in want], autojunk=False)
    lab = [None] * len(heard)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n): lab[a + k] = want[b + k][1]
    for i in range(len(lab)):                 # a misheard word takes its neighbour's side
        if lab[i] is None: lab[i] = lab[i - 1] if i else next((x for x in lab if x is not None), False)
    spans = []
    for w, s in zip(heard, lab):
        if not s: continue
        a, b = max(0.0, w.start - 0.05), w.end + 0.1
        if spans and a - spans[-1][1] < 0.4: spans[-1][1] = b
        else: spans.append([a, b])
    nar = [w for w, sp in want if not sp]                 # how much of the narration is in the recording at all
    said = {norm(w.word) for w in heard}
    return [tuple(x) for x in spans if x[1] - x[0] >= 0.6], sum(1 for w in nar if w in said) / max(1, len(nar))

def todo():
    rc = ov.race_cast(); refs = ov.pack_refs(); by = {}
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['action'] == 'reuse' and r['file_in_pack'] and r['npc_id'] in refs and r['npc_id'] not in rc \
                and not r['npc_id'].startswith(('go:', 'item:')):           # objects and items: our narrator reads them
            by.setdefault(r['npc_id'], []).append(r)
    out = {}
    for npc, rs in by.items():
        best = next((r for r in rs if f"{r['source_pack']}:{r['file_in_pack']}" == refs[npc]), None)
        if best and narrated(raw(best['questId'], best['kind'])): out[npc] = rs
    return out

def run():
    os.makedirs(REVIEW, exist_ok=True); res = {}
    for npc, rs in todo().items():
        name = rs[0]['npc_name']
        rs = sorted(rs, key=lambda r: -int(r['words'] or 0))
        # SpeakStone mostly leaves its <emotes> unread: a speaker whose reference has no narration in the AUDIO is fine
        ref = ov.pack_refs()[npc]; r0 = next(r for r in rs if f"{r['source_pack']}:{r['file_in_pack']}" == ref)
        _, heard = speaker_spans(render.pack_clip(ref, f"refs_cache/cut_{npc}_{r0['questId']}{r0['kind']}.ogg"),
                                 raw(r0['questId'], r0['kind']))
        if heard < NARRATION_HEARD:
            res[npc] = dict(name=name, how='fine', heard=round(heard, 2)); print(npc, name, 'fine', round(heard, 2), flush=True); continue
        clean = [r for r in rs if not narrated(raw(r['questId'], r['kind']))]
        if clean and int(clean[0]['words'] or 0) >= CLEAN_WORDS:
            res[npc] = dict(name=name, how='clean', clone_ref=f"{clean[0]['source_pack']}:{clean[0]['file_in_pack']}",
                            words=int(clean[0]['words'])); print(npc, name, 'clean', flush=True); continue
        pieces, secs, notes = [], 0.0, []
        for r in rs:
            t = raw(r['questId'], r['kind'])
            if not narrated(t) or secs >= MAX_SECS: continue
            src = render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}",
                                                               f"refs_cache/cut_{npc}_{r['questId']}{r['kind']}.ogg")
            spans, heard = speaker_spans(src, t)
            if heard < NARRATION_HEARD: spans = [(0.0, len(decode(src)) / SR)]   # this one is all them
            x = decode(src)
            for a, b in spans:
                if secs >= MAX_SECS: break
                b = min(b, a + MAX_SECS - secs)
                pieces.append(x[int(a * SR):int(b * SR)]); pieces.append(np.zeros(int(0.25 * SR), np.float32)); secs += b - a
        if clean and secs < MIN_SECS:
            res[npc] = dict(name=name, how='clean', clone_ref=f"{clean[0]['source_pack']}:{clean[0]['file_in_pack']}",
                            words=int(clean[0]['words']), note=f'only {secs:.1f} s of their own words; a short clean one instead')
            print(npc, name, 'clean (short)', flush=True); continue
        if secs < MIN_SECS:
            res[npc] = dict(name=name, how='flagged', secs=round(secs, 1), note='; '.join(notes) or 'too little of their own voice')
            print(npc, name, 'FLAGGED', round(secs, 1), flush=True); continue
        wav = f'refs_cache/pack_cut_{npc}.wav'; dst = f'clone_refs/pack_cut_{npc}.flac'
        np.concatenate(pieces).astype('<f4').tofile(wav + '.raw')
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', wav + '.raw',
                        '-af', 'loudnorm=I=-20:TP=-2', '-ar', str(SR), dst], check=True)
        os.remove(wav + '.raw')
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', dst, f"{REVIEW}/{npc}_{re.sub(r'[^A-Za-z0-9]+', '_', name)}.mp3"], check=True)
        res[npc] = dict(name=name, how='cut', ref=dst, secs=round(secs, 1), **({'note': '; '.join(notes)} if notes else {}))
        print(npc, name, 'cut', round(secs, 1), '; '.join(notes), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)
    print({h: sum(1 for v in res.values() if v['how'] == h) for h in ('fine', 'clean', 'cut', 'flagged')})

def apply():
    res = json.load(open(OUT)); RC = json.load(open('race_cast.json'))
    now = datetime.datetime.now().isoformat(timespec='seconds'); n = 0
    c = sqlite3.connect(ov.DB, isolation_level=None)
    lines = {}
    for r in csv.DictReader(open('plan_v3.csv')): lines.setdefault(r['npc_id'], []).append(r)
    for npc, v in res.items():
        if v['how'] in ('flagged', 'fine') or npc in RC: continue
        why = "their pack reference had the pack narrator in it (2026-10-16): "
        if v['how'] == 'clean':
            RC[npc] = {'name': v['name'], 'src': 'pack_clean', 'clone_ref': v['clone_ref'], 'ref': '',
                       'why': why + 'a recording with no narration instead'}
        else:
            RC[npc] = {'name': v['name'], 'src': 'pack_speaker_cut', 'ref': v['ref'], 'tempo': 1.0,
                       'why': why + f"{v['secs']} s of their own words cut out"}
        for r in lines.get(npc, []):
            n += c.execute("UPDATE lines SET status='todo', seed=seed+1, updated=? WHERE questId=? AND kind=? AND status IN ('done','review')",
                           (now, r['questId'], r['kind'])).rowcount
    json.dump(RC, open('race_cast.json', 'w'), indent=1, ensure_ascii=False); open('race_cast.json', 'a').write('\n')
    print(sum(1 for v in res.values() if v['how'] in ('clean', 'cut')), 'speakers re-referenced;', n, 'done lines re-queued')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'run': run, 'apply': apply}[sys.argv[1]]()
