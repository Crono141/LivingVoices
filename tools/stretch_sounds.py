"""Drawn-out sounds (2026-10-13): naga hisses ("Ssstrike", "misssery", "Changesss") and drawn-out words ("sorrrrrowful",
"muuuussst"). The voice cannot be spelled into them -- extra letters are read as letter names or ignored (tested on
Sseratus and the whole list). So the word is spoken normally and the sound is stretched in the finished audio:
Whisper's word timings find the word, the phoneme recognizer finds the sound inside it (20 ms frames), and that
slice alone is time-stretched (rubberband, pitch kept) and spliced back with short crossfades.

data/stretch.json:  "<word as written in the quest text>": {"say": "<plain word>", "sound": "s" | "r" | "u" | ..., "at": "start" | "end" | "any", "factor": 3.0}
  python ../tools/stretch_sounds.py <line.mp3> <text>      (the project venv; CPU)  -- render.py calls it for lines that need it
"""
import json, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TABLE = 'stretch.json'
SOUNDS = {   # coarse target -> the recognizer's tokens that count as it
    's': {'s', 'z', 'ʃ'}, 'r': {'ɹ', 'ɚ', 'ɝ', 'r'}, 'u': {'ʌ', 'ʊ', 'u', 'uː', 'ə'}, 'e': {'ɛ', 'e', 'eɪ', 'iː', 'i', 'ɪ'},
    'a': {'æ', 'ɑ', 'ɑː', 'a', 'aɪ', 'eɪ'}, 'o': {'oʊ', 'ɔ', 'ɔː', 'o'}}

def table():
    return json.load(open(TABLE)) if os.path.exists(TABLE) else {}

def words_in(text):
    T = table(); return [w for w in T if re.search(rf'(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])', text)]

def phone_frames(y):
    """[(token, start_s, end_s)] from the phoneme recognizer's 20 ms frames"""
    import torch, phonemes as ph
    fe, model, inv = ph._load()
    x = fe(y, sampling_rate=16000, return_tensors='pt').input_values.to(next(model.parameters()).device)
    with torch.no_grad(): ids = model(x).logits.argmax(-1)[0].tolist()
    out, prev = [], None
    for i, t in enumerate(ids):
        tok = inv[t]
        if tok in ('<pad>', '<s>', '</s>', '<unk>'): prev = None; continue
        if out and tok == prev: out[-1] = (tok, out[-1][1], (i + 1) * 0.02)
        else: out.append((tok, i * 0.02, (i + 1) * 0.02))
        prev = tok
    return out

def hiss_runs(y, sr=16000):
    """[(start_s, end_s)] of sibilant stretches: 10 ms frames where the 4-8 kHz band outweighs 100-3000 Hz"""
    import librosa, numpy as np
    S = np.abs(librosa.stft(y, n_fft=512, hop_length=160)); f = librosa.fft_frequencies(sr=sr, n_fft=512)
    hi = S[(f > 4000) & (f < 8000)].sum(0); lo = S[(f > 100) & (f < 3000)].sum(0) + 1e-6
    on = (hi / lo > 1.0) & (S.sum(0) > S.sum(0).max() * 0.02)
    runs, start = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None: start = i
        if not v and start is not None:
            if i - start >= 3: runs.append((start * 0.01, i * 0.01))
            start = None
    return runs

def stretch(path, text):
    import librosa, numpy as np, soundfile as sf
    from faster_whisper import WhisperModel
    from asr_check import MODEL
    T = table(); todo = words_in(text)
    if not todo: return 0
    y, sr = librosa.load(path, sr=24000); y16 = librosa.resample(y, orig_sr=24000, target_sr=16000)
    wm = WhisperModel(MODEL, device='cpu', compute_type='int8')
    segs, _ = wm.transcribe(y16, language='en', word_timestamps=True)
    hw = [w for s in segs for w in (s.words or [])]
    cuts = []
    import difflib
    known = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    nk = [re.sub(r'[^a-z]', '', k.lower()) for k in known]
    nh = [re.sub(r'[^a-z]', '', h.word.lower()) for h in hw]
    ops = difflib.SequenceMatcher(None, nk, nh, autojunk=False).get_opcodes()
    def heard_at(i):
        """the Whisper word standing where the text's i-th word stands (Whisper spells names its own way: "Sseratus"
        in a troll's voice came back "Seixirathas")"""
        for tag, a1, a2, b1, b2 in ops:
            if a1 <= i < a2 and tag in ('equal', 'replace') and b2 > b1: return hw[min(b1 + (i - a1), b2 - 1)]
        return None
    for w in todo:
        rule = T[w]
        for i, k in enumerate(known):
            if k.strip("'") != w: continue
            h = heard_at(i)
            if h is None: continue
            a, b = max(0.0, h.start - 0.05), h.end + 0.05
            seg = y16[int(a * 16000):int(b * 16000)]
            if rule['sound'] == 's':
                # the hiss itself, measured: the run of frames where 4-8 kHz dominates (the recognizer marks a sound with
                # a single 20 ms spike, not its length -- stretching that added a tenth of a second)
                runs = hiss_runs(seg)
                if not runs: continue
                r0, r1 = runs[0] if rule['at'] == 'start' else runs[-1] if rule['at'] == 'end' else max(runs, key=lambda r: r[1] - r[0])
                cuts.append((a + r0, a + r1, float(rule.get('factor', 3.0))))
            else:
                ph = [p for p in phone_frames(seg) if p[0] in SOUNDS[rule['sound']]]
                if not ph: continue
                pick = ph[0] if rule['at'] == 'start' else ph[-1] if rule['at'] == 'end' else ph[len(ph) // 2]
                mid = a + (pick[1] + pick[2]) / 2          # a voiced sound: 120 ms around the recognizer's spike
                cuts.append((mid - 0.06, mid + 0.06, float(rule.get('factor', 3.0))))
    if not cuts: return 0
    cuts.sort(); out = []; pos = 0; fade = int(0.008 * sr)
    with tempfile.TemporaryDirectory() as t:
        for i, (s0, s1, f) in enumerate(cuts):
            i0, i1 = int(s0 * sr), int(s1 * sr)
            if i1 - i0 < int(0.03 * sr): i1 = i0 + int(0.03 * sr)
            out.append(y[pos:i0])
            src, dst = os.path.join(t, f'{i}.wav'), os.path.join(t, f'{i}s.wav')
            sf.write(src, y[i0:i1], sr)
            subprocess.run(['rubberband-r3', '-q', '-t', str(f), src, dst], check=True)
            seg, _ = librosa.load(dst, sr=sr)
            if fade and len(seg) > 2 * fade:
                seg[:fade] *= np.linspace(0, 1, fade); seg[-fade:] *= np.linspace(1, 0, fade)
            out.append(seg); pos = i1
        out.append(y[pos:])
        wav = os.path.join(t, 'joined.wav'); sf.write(wav, np.concatenate(out), sr)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', wav, '-b:a', '128k', path], check=True)
    return len(cuts)

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    print(stretch(sys.argv[1], ' '.join(sys.argv[2:])), 'sounds stretched')
