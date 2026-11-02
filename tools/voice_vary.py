"""One reference, many speakers (2026-10-14): a race's reference voice made into a different man by moving its pitch,
formant and pitch range independently -- Praat's "Change Gender" (parselmouth), one pass. The producer's call: three
fixed pitches made a town of three men, and pitch moved with formant (or formant held) still sounded like one man.

  pitch_st  semitones to move the voice's median pitch (the note he speaks on)
  formant   ratio for the throat's resonances: < 1 a bigger man, > 1 a slighter one (pitch untouched)
  range     how far his pitch rises and falls: < 1 flatter, > 1 more animated

  python ../tools/voice_vary.py <src> <dst> <pitch_st> <formant> <range>     (the project venv; CPU)
"""
import sys

def vary(src, dst, pitch_st=0.0, formant=1.0, range_=1.0):
    import parselmouth
    from parselmouth.praat import call
    snd = parselmouth.Sound(src)
    median = call(snd.to_pitch(), 'Get quantile', 0, 0, 0.5, 'Hertz')
    new = median * 2 ** (pitch_st / 12)
    out = call(snd, 'Change gender', 60, 400, float(formant), float(new), float(range_), 1.0)
    out.save(dst, 'WAV')
    return median, new

if __name__ == '__main__':
    m, n = vary(sys.argv[1], sys.argv[2], *map(float, sys.argv[3:6]))
    print(f'median pitch {m:.0f} Hz -> {n:.0f} Hz')
