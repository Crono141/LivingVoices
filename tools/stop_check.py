"""Stops read straight through (2026-10-30, the producer): the opposite of pause_check's pauses in the wrong place -- a
full stop the voice blows through without a breath. Arcanist Helion, 8346-accept: "Learn to master your power. When
you have sufficiently..." run together; 8325-complete: "your first task; for that, you are to be congratulated" with
not the hint of a pause. Commas are left alone: their pause is too brief to tell from speech, and some are never spoken.

The take is aligned to the script (pause_check.align) and at every . ! ? ; : (not an ellipsis, which pause_check's
halting read already covers) two things are measured: the aligned gap between the two words, and the longest run of
10 ms frames 35 dB under the take's loud speech (its 90th percentile) near the boundary. A run-through has both under
the limits; either alone is not enough (a dragon's echo or a breath fills a real pause, and the aligner can butt two
words that have a silence between them). Your two: gap 0.06 s, silence 0.04 and 0.00 s; their good stops 0.22-0.48 s.
On 1,500 finished lines, 2.4% had one.

  stops(path, text)        -> [(gap_s, quiet_s, dip_db, word_before, word_after, cut_s, i)] every stop measured
  missed(path, text)       -> the stops read through
  splice(src, dst, text)   -> a pause put in at each missed stop, as long as the take's own good stops (0.25-0.45 s)
"""
import re, subprocess
import numpy as np

SR = 16000
STOP = re.compile(r'[.!?;:]["”’)]*$')
MAX_GAP, MAX_QUIET, QUIET_DB = 0.10, 0.05, 35.0
# (2026-10-31) a title's full stop is not a stop: "Mr. Floppy", "Dr. Boom" read through is right. 14 of the night's
# 58 reviews were these, failing every seed.
ABBR = {'mr.', 'mrs.', 'ms.', 'dr.', 'st.', 'jr.', 'sr.', 'mt.', 'lt.', 'sgt.', 'capt.', 'col.', 'gen.', 'prof.', 'vs.'}
PAUSE_MIN, PAUSE_MAX, PAUSE_DEFAULT = 0.25, 0.45, 0.30

def _frames(x, sr):
    h = sr // 100
    return np.array([20 * np.log10(np.sqrt(np.mean(x[j:j + h] ** 2)) + 1e-9) for j in range(0, len(x) - h, h)])

def stops(path, text):
    import pause_check, render
    from asr_check import decode_audio
    W = pause_check.align(path, render.say_numbers(text))
    fr = _frames(decode_audio(open(path, 'rb').read()), SR)
    top = np.percentile(fr, 90); out = []
    for i in range(len(W) - 1):
        w = W[i][0]
        if not STOP.search(w) or w.rstrip('"”’)').endswith('...') or w.strip('"“”‘’(').lower() in ABBR: continue
        a, b = W[i][2], W[i + 1][1]
        lo, hi = int(max(0, a - 0.12) * 100), int((b + 0.12) * 100)
        seg = fr[lo:hi]; best = cur = 0
        for v in seg < top - QUIET_DB: cur = cur + 1 if v else 0; best = max(best, cur)
        # the cut: the quietest frame between the two words (a little either side, the aligner's edges are loose)
        c0, c1 = int(max(0, a - 0.05) * 100), max(int(max(0, a - 0.05) * 100) + 1, int((b + 0.05) * 100))
        cut = (c0 + int(np.argmin(fr[c0:c1]))) / 100 + 0.005
        out.append((round(b - a, 2), best / 100, round(float(seg.min() - top), 1) if len(seg) else 0.0, w, W[i + 1][0], cut, i))
    return out

def missed(path, text, S=None):
    return [s for s in (S if S is not None else stops(path, text)) if s[0] <= MAX_GAP and s[1] <= MAX_QUIET]

def splice(src, dst, text, S=None):
    """the take with a silence put in at each missed stop (10 ms fades either side of the cut); -> the stops spliced"""
    S = S if S is not None else stops(src, text)
    bad = missed(src, text, S); good = [s[1] for s in S if s not in bad and s[1] > 0.15]
    pause = float(np.clip(np.median(good), PAUSE_MIN, PAUSE_MAX)) if good else PAUSE_DEFAULT
    sr = 24000
    x = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', src, '-f', 's16le', '-ac', '1', '-ar', str(sr), 'pipe:1'],
                                     capture_output=True, check=True).stdout, np.int16).astype(np.float32)
    f = int(0.01 * sr); parts = []; last = 0
    for s in sorted(bad, key=lambda s: s[5]):
        k = int(s[5] * sr); a = x[last:k].copy(); a[-f:] *= np.linspace(1, 0, f)[-len(a[-f:]):]
        parts += [a, np.zeros(int(pause * sr), np.float32)]; last = k
    b = x[last:].copy()
    if bad: b[:f] *= np.linspace(0, 1, f)[:len(b[:f])]
    parts.append(b)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 's16le', '-ac', '1', '-ar', str(sr), '-i', 'pipe:0', '-b:a', '128k', dst],
                   input=np.concatenate(parts).astype(np.int16).tobytes(), check=True)
    return bad, pause
