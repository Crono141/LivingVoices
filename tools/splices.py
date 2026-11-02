"""Splice prep for the race/class sentences (variants.py), after rendering and before the build (run from data/,
with the speech check's venv: ../.venv/bin/python ../tools/splices.py [--limit N]):

  1. each base line's accepted take (render/<line>.mp3) aligned to its words once (pause_check.align, the stop check's
     aligner): the cut either side of each race/class sentence at the quietest point of the pause there, so each side
     keeps its half of the original pause -> data/splices.json {line: {mtime, cuts: {i: [from_ms, to_ms]}, ...}}
  2. each rendered clip (render/<line>_s<i>_<word>.mp3) trimmed, paced to the original sentence's words a second
     (0.87-1.15, as even_pace), its speech level matched to the original's (within 6 dB), padded with the original's
     silence either side of the cut, and written to render64/ at 64 kbps -- the file the build packs, which engine 0.4
     plays in place of take[from_ms:to_ms]
A take or clip newer than its record is done again. Lines whose take does not align word for word are left out (they
keep the stand-in) and listed.
"""
import json, os, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import direct, render, overnight, pause_check
SR = 24000

def pcm(path):
    x = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'], capture_output=True).stdout
    return np.frombuffer(x, np.float32).copy()

def frames_db(x, hop=SR // 100):
    n = len(x) // hop
    return 20 * np.log10(np.sqrt(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9) if n else np.array([-200.0])

def speech_span(x, lo=0, hi=None):
    f = frames_db(x); top = np.percentile(f, 95); hop = SR // 100
    a, b = lo // hop, (hi if hi is not None else len(x)) // hop
    on = [k for k in range(a, min(b, len(f))) if f[k] > top - 35]
    return (on[0] * hop, (on[-1] + 1) * hop) if on else (lo, hi if hi is not None else len(x))

def level(x):
    f = frames_db(x); return float(np.mean(f[f > np.percentile(f, 95) - 25]))

def quietest(x, t0, t1):
    f = frames_db(x); hop = SR // 100
    a, b = max(0, int((t0 - 0.05) * 100)), min(len(f), int((t1 + 0.05) * 100) + 1)
    return (a + int(np.argmin(f[a:b]))) * hop if b > a else int(t0 * SR)

def tempo(x, f):
    if abs(f - 1) < 0.03: return x
    p = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', '-', '-af', f'atempo={f:.3f}',
                        '-f', 'f32le', '-'], input=x.tobytes(), capture_output=True).stdout
    return np.frombuffer(p, np.float32).copy()

# what the take says aloud: a stage direction is (the narrator's), a sound marker is not (2026-11-01)
def words(t): return [w for w in render.say_numbers(render.spoken_text(t)).split() if pause_check._norm(w)]

_D = None
def spoken_sentences(base):
    global _D
    if _D is None: _D = overnight.load_directions([overnight.DIRECTIONS])
    p = base.split('-'); q, kind, v = p[0], p[1], (p[2] if len(p) > 2 else '')
    d = _D.get(q, {}).get(kind)
    return [render.scripted(s) for t in render.beat_texts(q, kind, v, d['beats']) for s in direct.sentences(t)]

def cuts_for(base, idx):
    """{i: (from, to, on, off, rate, level)} in samples, for the sentences idx of the line's accepted take"""
    take = f'render/{base}.mp3'; x = pcm(take)
    sents = spoken_sentences(base); per = [len(words(s)) for s in sents]
    W = pause_check.align(take, ' '.join(w for s in sents for w in words(s)))
    if len(W) != sum(per): raise ValueError(f'{len(W)} words aligned, {sum(per)} in the text')
    out = {}
    for i in idx:
        a = sum(per[:i]); b = a + per[i]
        if per[i] == 0: continue
        cutL = 0 if a == 0 else quietest(x, W[a - 1][2], W[a][1])
        cutR = len(x) if b >= len(W) else quietest(x, W[b - 1][2], W[b][1])
        on, off = speech_span(x, cutL, cutR)
        seg = x[on:off]
        out[i] = (cutL, cutR, on, off, per[i] / max(len(seg) / SR, 0.1), level(seg) if len(seg) else -30.0)
    return out

_whisper = None
def hear_spliced(base, r, ready, VAR):
    """the take with one clip in each of its race/class sentences, as engine 0.4 plays it, through the speech check's
    recognizer: (score >= GOOD, score, heard)"""
    global _whisper
    from faster_whisper import WhisperModel
    from asr_check import MODEL
    from asr_report import rescore
    if _whisper is None:
        try: _whisper = WhisperModel(MODEL, device='cuda', compute_type='float16')
        except Exception: _whisper = WhisperModel(MODEL, device='cpu', compute_type='int8')
    one = {}
    for vn in sorted(ready):
        i = str(VAR[vn]['i'])
        if i in r['cuts'] and i not in one and os.path.exists(f'render64/{vn}.mp3'): one[i] = vn
    if not one: return True, None, ''
    x = pcm(f'render/{base}.mp3'); out, pos = [], 0
    for i in sorted(one, key=int):
        a, b = (round(v * SR / 1000) for v in r['cuts'][i])
        out += [x[pos:a], pcm(f'render64/{one[i]}.mp3')]; pos = b
    y = np.concatenate(out + [x[pos:]])
    sents = spoken_sentences(base)
    for i, vn in one.items(): sents[int(i)] = VAR[vn]['text']
    meant = render.spoken_text(' '.join(sents))
    import scipy.signal
    dia = render.dialect_of(overnight.as_generated(next(r_ for r_ in PLAN() if overnight.name_of(r_) == base)) or {})
    def score(audio, meant):
        segs, _ = _whisper.transcribe(scipy.signal.resample_poly(audio, 2, 3).astype(np.float32), language='en')
        heard = ' '.join(s.text.strip() for s in segs)
        sc = rescore(render.dialect_text(heard, dia), render.dialect_text(meant, dia)) if dia else rescore(heard, meant)
        return (1.0 if sc is None else sc), heard
    sc, heard = score(y, meant)
    # a morph (a ghost's echo, a whisper) can hide words from the recognizer in the take itself: the spliced line has
    # to hear about as well as the take does, not better than it
    sc0, _ = score(x, render.spoken_text(' '.join(spoken_sentences(base))))
    return sc >= min(overnight.GOOD, sc0 - 0.05), sc, heard

_plan = None
def PLAN():
    global _plan
    if _plan is None:
        import csv; _plan = list(csv.DictReader(open('plan_v3.csv')))
    return _plan

def main(limit=None):
    VAR = json.load(open('variants.json'))
    st = dict(overnight.db().execute('SELECT name, status FROM lines'))
    rec = json.load(open('splices.json')) if os.path.exists('splices.json') else {}
    by_base = {}
    for vn, x in VAR.items(): by_base.setdefault(x['base'], {}).setdefault(x['i'], []).append(vn)
    done = failed = clips = heard_ok = 0; bad = []
    for base, sents in sorted(by_base.items()):
        if limit and done >= limit: break
        take = f'render/{base}.mp3'
        ready = [vn for vns in sents.values() for vn in vns if st.get(vn) in ('done', 'review') and os.path.exists(f'render/{vn}.mp3')]
        if not ready or not os.path.exists(take): continue
        r = rec.get(base)
        if r and r.get('error') and r['mtime'] >= os.path.getmtime(take): continue      # failed on this take: not every night
        if not r or r['mtime'] < os.path.getmtime(take) or set(map(str, sents)) - set(r['cuts']):
            try:
                c = cuts_for(base, sorted(sents))
                r = rec[base] = {'mtime': os.path.getmtime(take), 'cuts': {str(i): [round(v[0] * 1000 / SR), round(v[1] * 1000 / SR)] for i, v in c.items()},
                                 'raw': {str(i): list(map(float, v)) for i, v in c.items()}}
                done += 1
            except Exception as e:
                rec[base] = {'mtime': os.path.getmtime(take), 'cuts': {}, 'raw': {}, 'error': str(e)[:200]}; failed += 1; bad.append(base); continue
        if not r['cuts']: continue
        x = None
        for vn in ready:
            i = str(VAR[vn]['i']); dst = f'render64/{vn}.mp3'
            if i not in r['raw']: continue
            if os.path.exists(dst) and os.path.getmtime(dst) >= max(os.path.getmtime(f'render/{vn}.mp3'), r['mtime']): continue
            cutL, cutR, on, off, rate, lvl = r['raw'][i]
            v = pcm(f'render/{vn}.mp3'); v0, v1 = speech_span(v); v = v[v0:v1]
            n = len(words(VAR[vn]['text']))
            f = float(np.clip(rate / (n / max(len(v) / SR, 0.1)), 0.87, 1.15)) if n else 1.0
            v = tempo(v, f)
            g = float(np.clip(lvl - level(v), -6, 6)) if len(v) else 0.0
            v = v * 10 ** (g / 20)
            fade = min(int(0.005 * SR), len(v) // 2)
            if fade: v[:fade] *= np.linspace(0, 1, fade); v[-fade:] *= np.linspace(1, 0, fade)
            y = np.concatenate([np.zeros(int(on - cutL), np.float32), v, np.zeros(int(cutR - off), np.float32)])
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', '-', '-c:a', 'libmp3lame',
                            '-b:a', '64k', dst + '.tmp.mp3'], input=np.clip(y, -1, 1).astype(np.float32).tobytes(), check=True)
            os.replace(dst + '.tmp.mp3', dst); clips += 1
        # (2026-11-01) a line with narration, sounds, another voice or a morph between its words: heard spliced once (one
        # clip per sentence) before any of its clips ship; a splice the recognizer cannot follow keeps the stand-in
        risk = next((VAR[vn].get('risk') for vn in ready if VAR[vn].get('risk')), None)
        if risk and r.get('heard_mtime') != r['mtime']:
            ok, score, heard = hear_spliced(base, r, ready, VAR)
            r['heard_mtime'], r['heard'] = r['mtime'], f'{score} {heard[:200]}'
            if not ok:
                rec[base] = {'mtime': r['mtime'], 'cuts': {}, 'raw': {}, 'error': f'heard spliced ({risk}): {score} {heard[:150]}'}
                failed += 1; bad.append(base)
            else: heard_ok += 1
        if done % 50 == 0: json.dump(rec, open('splices.json', 'w'))
    json.dump(rec, open('splices.json', 'w'))
    print(f'splices: {done} takes aligned, {heard_ok} narrated/morphed lines heard spliced and kept, {failed} left out '
          f'({", ".join(bad[:8])}), {clips} clips prepared')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    main(int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None)
