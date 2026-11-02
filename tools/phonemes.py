"""IPA from speech (wav2vec2-lv-60-espeak-cv-ft, <models_dir>/ASR) and a coarse phoneme distance, for checking how a
name was pronounced without a person listening (2026-10-13). The model's tokenizer wants phonemizer only to ENCODE text;
decoding reads vocab.json directly."""
import itertools, json, re
import lvconfig as LV
M = f'{LV.MODELS}/ASR/wav2vec2-lv-60-espeak-cv-ft'
_m = None
def _load():
    global _m
    if _m is None:
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2FeatureExtractor
        import torch
        fe = Wav2Vec2FeatureExtractor.from_pretrained(M)
        model = Wav2Vec2ForCTC.from_pretrained(M).to('cuda' if torch.cuda.is_available() else 'cpu').eval()
        _m = (fe, model, {v: k for k, v in json.load(open(f'{M}/vocab.json')).items()})
    return _m

def ipa(y, sr=16000):
    import torch
    fe, model, inv = _load()
    x = fe(y, sampling_rate=sr, return_tensors='pt').input_values.to(next(model.parameters()).device)
    with torch.no_grad(): ids = model(x).logits.argmax(-1)[0].tolist()
    return [inv[i] for i, _ in itertools.groupby(ids) if inv[i] not in ('<pad>', '<s>', '</s>', '<unk>')]

# coarse classes: vowels of a kind and r-colouring merged, so accent and recognizer noise do not count as mistakes
COARSE = [('ɔːɹ', 'oR'), ('ɑːɹ', 'aR'), ('ɚ', 'eR'), ('ɝ', 'eR'), ('ɜː', 'eR'), ('əl', 'el'), ('ɐ', 'e'),
          ('ɑː', 'a'), ('ɑ', 'a'), ('æ', 'a'), ('ɒ', 'o'), ('ɔː', 'o'), ('ɔ', 'o'), ('oʊ', 'o'), ('o', 'o'),
          ('ə', 'e'), ('ʌ', 'e'), ('ɛ', 'E'), ('e', 'E'), ('eɪ', 'A'), ('aɪ', 'I'), ('ɑɪ', 'I'), ('aʊ', 'W'), ('ɔɪ', 'Y'),
          ('iː', 'i'), ('i', 'i'), ('ɪ', 'i'), ('uː', 'u'), ('u', 'u'), ('ʊ', 'u'), ('ɹ', 'R'), ('r', 'R'), ('ʁ', 'R'),
          ('ɡ', 'g'), ('θ', 'T'), ('ð', 'T'), ('ʃ', 'S'), ('ʒ', 'Z'), ('tʃ', 'C'), ('dʒ', 'J'), ('ŋ', 'N'), ('x', 'k'), ('ʔ', '')]

_TABLE = None
def coarse(s):
    """IPA string or token list -> a list of coarse phoneme symbols (length marks dropped first, so the table is
    matched on its stripped keys, longest first -- else "ɑː" split the diphthong "ɑɪ")"""
    global _TABLE
    if _TABLE is None:
        t = {}
        for a, b in COARSE + [('ɫ', 'l'), ('ᵻ', 'i'), ('ɾ', 't')]: t.setdefault(a.replace('ː', ''), b)
        _TABLE = sorted(t.items(), key=lambda x: -len(x[0]))
    if isinstance(s, list): s = ''.join(s)
    s = re.sub(r"[ˈˌː./\[\]\s'\-]", '', s)
    out, i = [], 0
    while i < len(s):
        for a, b in _TABLE:
            if a and s.startswith(a, i):
                if b: out.append(b)
                i += len(a); break
        else: out.append(s[i]); i += 1
    return out

def distance(a, b):
    """edit distance between two coarse phoneme lists, as a share of the longer"""
    a, b = coarse(a), coarse(b)
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        p, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (x != y))
    return d[len(b)] / max(len(a), len(b), 1)
