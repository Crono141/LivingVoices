"""Pauses in the wrong place (2026-10-18): the producer's most common note in samples 2 and 3 -- "harpies (pause) that
dwell here", "camouflage (pause) I've prepared", "nether (pause) rocket", 17 of 240 takes. Silence length alone does not
tell them apart (the bad ones run 0.4-0.8 s, as long as a breath between sentences), and Whisper's word times stretch
across the silences (every gap read as zero). So the take is aligned to the words we sent (torchaudio's MMS_FA forced
aligner), each silence of 0.3 s or more where the script has no punctuation is marked in its sentence, and the model
decides whether an actor would breathe there or whether it breaks a phrase. On the two samples: 11 of the 17 noted
pauses caught, 41 takes flagged in all (Anchorite (pause) Ahuurn and the like among the unnoted).

  gaps(path, text)   -> [(gap_s, word_before, word_after, context)]     (card 1, in the speech check's process)
  judge(gaps)        -> the gaps the model calls odd                     (Gemma, through the arbiter)
"""
import re, unicodedata

MIN_GAP, CONTEXT = 0.3, 12
PUNCT = re.compile(r'[.,!?;:…—\-"”)⟩]$')
_M = None

def _load():
    global _M
    if _M is None:
        import torch
        from torchaudio.pipelines import MMS_FA as B
        _M = (B.get_model().to('cuda' if torch.cuda.is_available() else 'cpu').eval(), B.get_tokenizer(), B.get_aligner())
    return _M

def _norm(w):
    w = unicodedata.normalize('NFKD', w.replace('’', "'")).encode('ascii', 'ignore').decode().lower()
    return re.sub(r"[^a-z']", '', w).strip("'")

def align(path, text):
    """[(word as written, start_s, end_s)] for every word of the text with a letter in it"""
    import torch
    from asr_check import decode_audio
    model, tok, aligner = _load()
    keep = [(w, n) for w in text.split() if (n := _norm(w))]
    wav = torch.tensor(decode_audio(open(path, 'rb').read())).unsqueeze(0).to(next(model.parameters()).device)
    with torch.inference_mode():
        em, _ = model(wav); spans = aligner(em[0], tok([n for _, n in keep]))
    ratio = wav.shape[1] / em.shape[1] / 16000
    out = [(w, s[0].start * ratio, s[-1].end * ratio) for (w, _), s in zip(keep, spans)]
    # (2026-10-19) hand the memory back: torch keeps what it freed cached for itself, and Whisper (CTranslate2) in the
    # same process cannot use that cache -- the night's check died of CUDA out-of-memory inside Whisper after a long clip
    del wav, em, spans
    if torch.cuda.is_available(): torch.cuda.empty_cache()
    return out

def gaps(path, text):
    # (2026-10-28) numbers as the voice says them: the aligner drops a word with no letters, so "Sparklematic 5200 is"
    # read the whole "fifty-two hundred" as a pause between Sparklematic and is (34 of the 10-26 night's 87 odd pauses)
    if re.search(r'\d', text):
        from render import say_numbers
        text = say_numbers(text)
    W = align(path, text); out = []
    for i in range(len(W) - 1):
        g, a, b = W[i + 1][1] - W[i][2], W[i][0], W[i + 1][0]
        if g >= MIN_GAP and not PUNCT.search(a) and not a.startswith('⟨') and not b.startswith('⟨'):
            ctx = (' '.join(w for w, *_ in W[max(0, i - CONTEXT):i + 1]) + f' [PAUSE {g:.1f} s] '
                   + ' '.join(w for w, *_ in W[i + 1:i + 1 + CONTEXT]))
            out.append((round(g, 2), a, b, ctx))
    return out

SYSTEM = """You review a voice actor's read of a World of Warcraft quest line. One silence in the read is marked [PAUSE n s] \
where it fell. No punctuation stands there in the script. Decide whether a skilled actor reading this line naturally might \
take that breath or beat there (between two clauses, before a list item, before a weighty word for effect), or whether \
it breaks a phrase that belongs together and sounds wrong to a listener (inside a name or compound, between a noun and \
the words that describe it, mid-way through a short phrase, too long for the spot).
Answer JSON: {"why": "<one short sentence>", "verdict": "natural" | "odd"}"""
SCHEMA = {'type': 'object', 'required': ['why', 'verdict'],
          'properties': {'why': {'type': 'string'}, 'verdict': {'type': 'string', 'enum': ['natural', 'odd']}}}

def judge(found):
    """the gaps the model hears as breaking a phrase; a failed call counts as natural (never a retake on a hiccup)"""
    import bakeoff
    odd = []
    for g in found:
        try: v = bakeoff.llm(SYSTEM, f'The read:\n...{g[3]}...', SCHEMA)
        except Exception: continue
        if v.get('verdict') == 'odd': odd.append((g[0], g[1], g[2]))
    return odd
