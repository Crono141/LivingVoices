"""Overexcited reads (2026-10-28, the producer): some undead men get carried away at a question mark -- Doctor Serratus,
8600-accept: "sharpest of edges... yes? WELL NO MATTER" climbing, and his last "no?" a three-second wail,
"noooooOOOOUUUUEEEEEE". The speech check hears the right words and passes it. Two measures, from the words aligned to
the take (pause_check.align) and the voice's pitch (autocorrelation, 10 ms frames, against the speaker's own median):

  hum   -- sound as loud as speech where the aligner sees no word: a vowel or hum held on after a word ("jerkinnnnnnn",
           7882-complete: 2.6 s at -22..-13 dB after 'jerkins.'; "Apothecarioummmm", 4642-accept: 1.9 s; Serratus'
           last "no?": 3.3 s). A real pause sits far below HUM_DB. (2026-10-28) The first version tracked pitch, and a
           hum climbing past the tracker's range read as silence; loudness has no such blind spot.
  carry -- the pitch of the words after a question mark against the speaker's median. Reported, never a fault: in
           the producer's calibration, five lines at +7..+11 sounded fine, so it does not tell an excited read apart.

  report(path, text) -> dict(hum_s, hum_after, carry_st, carry_after, flag)
  ~/.venv python delivery_check.py <file.mp3> <text>       (card 1; from data/)
"""
import re, sys
import numpy as np

SR = 16000
HUM_DB, HUM_S, CARRY_N = -30.0, 0.75, 3
# (2026-10-28, the producer, after hearing the 1.5 s catches) "I'd want everything over .75 seconds caught and sent back
# for another pass. At that length a trail off sounds gutteral or like flavor, not like a error" -- a retake is cheap,
# his listening is not. (Normal undead men: median 0.25 s, 95% under 0.7 s.)
HELD = re.compile(r'([a-z])\1\1', re.I)   # a sound the text itself draws out ("Mmmmmm....", "Kymaerrrokk", "Ssstrike")

def f0(x, lo=60, hi=320, hop=160, win=640):
    """pitch per 10 ms frame (Hz, NaN where unvoiced); hi=320 keeps a hiss from reading as an octave up"""
    out = []
    for i in range(0, len(x) - win, hop):
        s = x[i:i + win] - x[i:i + win].mean()
        if np.sqrt(np.mean(s ** 2)) < 0.01: out.append(np.nan); continue
        ac = np.correlate(s, s, 'full')[win - 1:]; ac /= ac[0] + 1e-9
        a, b = SR // hi, SR // lo; k = a + int(np.argmax(ac[a:b]))
        out.append(SR / k if ac[k] > 0.45 else np.nan)
    return np.array(out)

def report(path, text, hi=320):
    import pause_check, render
    from asr_check import decode_audio
    W = pause_check.align(path, render.say_numbers(text))
    x = decode_audio(open(path, 'rb').read()); F = f0(x, hi=hi); t = np.arange(len(F)) * 0.01
    med = np.nanmedian(F)
    st = lambda v: 12 * np.log2(v / med)
    # hum: the longest run of 50 ms frames at speech loudness inside any gap between aligned words (or after the last)
    def loud_run(a, b):
        seg = x[int(a * SR):int(b * SR)]; best = cur = 0
        for j in range(0, len(seg) - 800 + 1, 800):
            if 20 * np.log10(np.sqrt(np.mean(seg[j:j + 800] ** 2)) + 1e-9) >= HUM_DB: cur += 1; best = max(best, cur)
            else: cur = 0
        return best * 0.05
    hum = (0.0, '')
    for i, (w, a, b) in enumerate(W):
        if HELD.search(w): continue
        r = loud_run(b, W[i + 1][1] if i + 1 < len(W) else len(x) / SR)
        if r > hum[0]: hum = (r, w)
    # carry: the next few words after each '?' (not the line's last word), against the speaker's median
    def word_st(a, b):
        v = F[(t >= a) & (t < b)]; v = v[~np.isnan(v)]
        return float(np.median(st(v))) if len(v) >= 3 else None
    carry = (None, '')
    for i, (w, a, b) in enumerate(W[:-1]):
        if not w.endswith('?'): continue
        nxt = [x for x in (word_st(*W[j][1:]) for j in range(i + 1, min(i + 1 + CARRY_N, len(W)))) if x is not None]
        if nxt and (carry[0] is None or np.mean(nxt) > carry[0]): carry = (float(np.mean(nxt)), w)
    flag = [f'held sound: {hum[0]:.1f}s after "{hum[1]}"'] if hum[0] >= HUM_S else []
    return dict(hum_s=round(hum[0], 2), hum_after=hum[1], carry_st=None if carry[0] is None else round(carry[0], 1),
                carry_after=carry[1], flag=flag)

if __name__ == '__main__':
    print(report(sys.argv[1], sys.argv[2]))
