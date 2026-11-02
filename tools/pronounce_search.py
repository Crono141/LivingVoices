"""Pronunciations without a listener (2026-10-13; the producer: "too many words to listen for").

The target for a name is its OFFICIAL sound, as IPA: the Warcraft Wiki's (wiki_pronounce.py), or, where the wiki has
none, what Blizzard's own actors say in the game's recorded lines -- the line's text is in the database, Whisper's word
timings find the name in the clip, and a phoneme recognizer (phonemes.py) writes down what was said. Then candidate
spellings (the plain spelling, the wiki's respelling and mechanical variants of it, a spelling built from the target
IPA) are each spoken by the TTS in a carrier sentence, transcribed to IPA the same way, and the closest wins -- adopted
only when it beats the plain spelling clearly. No model guesses a pronunciation.

Run from data/ with the project venv (card 0 through the arbiter for the TTS; the recognizers on card 0):
  ../.venv/bin/python ../tools/pronounce_search.py voiced          index every recorded WoW line (text + sound file)
  ../.venv/bin/python ../tools/pronounce_search.py targets [N]     wiki words + the N most frequent uncovered words
  ../.venv/bin/python ../tools/pronounce_search.py search          render, compare, write the winners to pronounce.json
"""
import collections, csv, difflib, json, os, re, struct, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
VOICED, TARGETS, RESULT = 'wow_voiced_lines.json', 'pron_targets.json', 'pron_search.json'
SQL = f'{LV.AC_SQL}/'
CLIENT = f'{LV.WOW_DATA}/'
CLIPS = f'{LV.SCRATCH}/pron_clips'
CARRIER = 'We ride for {} at first light.'
ADOPT_MARGIN, ADOPT_MAX = 0.15, 0.30
# an article that names two words gives one respelling: it belongs to the other ("Arathi Empire" also says Arathor)
NOT_THIS_WORD = {'Arathor'}

# ---------------------------------------------------------------- 1. every recorded line
def voiced():
    from sqlrows import rows
    import mpyq
    MPQS = ['enUS/speech-enUS.MPQ', 'enUS/expansion-speech-enUS.MPQ', 'enUS/lichking-speech-enUS.MPQ',
            'enUS/patch-enUS.MPQ', 'enUS/patch-enUS-2.MPQ', 'enUS/patch-enUS-3.MPQ']
    def sqltable(name):
        txt = open(SQL + name + '.sql', encoding='utf-8', errors='replace').read()
        body = txt[txt.index('CREATE TABLE'):]; body = body[:body.index(') ENGINE')]
        c = [m.group(1) for m in re.finditer(r'^\s+`(\w+)`', body, re.M)]
        for r in rows(SQL + name + '.sql', null=''): yield dict(zip(c, r))
    where = {}
    for m in MPQS:
        for f in mpyq.MPQArchive(CLIENT + m, listfile=True).files or []:
            f = f.decode('utf-8', 'replace')
            if f.lower().endswith(('.wav', '.mp3', '.ogg')): where[f.lower()] = (CLIENT + m, f)
    b = open('dbc/SoundEntries.dbc', 'rb').read(); _, n, fc, rs, ss = struct.unpack('<4s4I', b[:20]); strs = b[20 + n * rs:]
    s = lambda o: strs[o:strs.index(b'\0', o)].decode('utf-8', 'replace')
    sound = {}
    for i in range(n):
        r = struct.unpack(f'<{fc}I', b[20 + i * rs:20 + (i + 1) * rs]); base = s(r[23]).rstrip('\\')
        sound[r[0]] = [((base + '\\') if base else '') + s(r[3 + j]) for j in range(10) if r[3 + j]]
    out, seen = [], set()
    def add(sid, text):
        for p in sound.get(sid, []):
            w = where.get(p.lower())
            if w and text and (w[1], text) not in seen and len(sound[sid]) == 1:     # one file: its text is known
                seen.add((w[1], text)); out.append({'text': text, 'mpq': w[0], 'file': w[1]})
    for r in sqltable('broadcast_text'):
        sid = int(r['SoundEntriesId'] or 0)
        if sid: add(sid, r['MaleText'] or r['FemaleText'])
    for r in sqltable('creature_text'):
        sid = int(r['Sound'] or 0)
        if sid: add(sid, r['Text'])
    json.dump(out, open(VOICED, 'w'), indent=0)
    print(len(out), 'recorded lines with known text')

def wc3():
    """Warcraft III's campaign dialogue and unit lines, transcribed once with word timings (Whisper knows WC3's names),
    so a name can be found in Blizzard's own voices where WoW's recordings never say it"""
    from faster_whisper import WhisperModel
    from asr_check import MODEL
    from mpqget import MPQ
    import librosa
    T = LV.SCRATCH
    wm = WhisperModel(MODEL, device='cuda', compute_type='float16'); out = []
    for a in ('war3.mpq', 'War3x.mpq', 'War3xLocal.mpq'):
        w = MPQ(f'{T}/{a}'); L = w.read('(listfile)').decode('latin1').split('\r\n')
        for f in L:
            fl = f.lower()
            if not fl.endswith(('.wav', '.mp3')) or not (fl.startswith('sound\\dialogue') or fl.startswith('units\\')): continue
            dst = f"{CLIPS}/wc3_{norm(f)[-70:]}.{fl.rsplit('.', 1)[1]}"; os.makedirs(CLIPS, exist_ok=True)
            if not os.path.exists(dst): open(dst, 'wb').write(w.read(f))
            try: y, _ = librosa.load(dst, sr=16000)
            except Exception: continue
            if len(y) < 8000: continue
            segs, _ = wm.transcribe(y, language='en', word_timestamps=True)
            words = [(x.word.strip(), round(x.start, 2), round(x.end, 2)) for s_ in segs for x in (s_.words or [])]
            if words: out.append({'file': dst, 'words': words})
        w.close()
    json.dump(out, open('wc3_transcripts.json', 'w'))
    print(len(out), 'WC3 clips transcribed')

def cinematics():
    """WoW's race-introduction narrations and cinematics, transcribed like WC3 and added to the same file: they say
    the homelands' names (Northshire, Teldrassil, Durotar, Mulgore, Eversong...) in Blizzard's own voices"""
    import glob as g
    from faster_whisper import WhisperModel
    from asr_check import MODEL
    from mpqget import MPQ
    import librosa
    wm = WhisperModel(MODEL, device='cuda', compute_type='float16')
    srcs = []
    for p in sorted(g.glob(CLIENT + '*.MPQ') + g.glob(CLIENT + '*/*.MPQ')):
        try: m = MPQ(p); L = m.read('(listfile)').decode('latin1').split('\r\n')
        except Exception: continue
        for f in L:
            if f.lower().startswith('sound\\cinematicvoices') and f.lower().endswith('.mp3'):
                dst = f"{CLIPS}/cin_{f.rsplit(chr(92), 1)[1]}"; os.makedirs(CLIPS, exist_ok=True)
                if not os.path.exists(dst): open(dst, 'wb').write(m.read(f))
                if dst not in srcs: srcs.append(dst)
        m.close()
    for v in g.glob(CLIENT + 'enUS/Interface/Cinematics/*_1024.avi') + g.glob(CLIENT + 'enUS/Interface/Cinematics/WOW_Intro_BC_800.avi')[:0]:
        dst = f"{CLIPS}/cin_{os.path.basename(v)[:-4]}.wav"
        if not os.path.exists(dst): subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', v, '-vn', '-ac', '1', '-ar', '16000', dst], check=True)
        srcs.append(dst)
    W3 = json.load(open('wc3_transcripts.json')) if os.path.exists('wc3_transcripts.json') else []
    have = {c['file'] for c in W3}
    for f in srcs:
        if f in have: continue
        y, _ = librosa.load(f, sr=16000)
        segs, _ = wm.transcribe(y, language='en', word_timestamps=True)
        words = [(x.word.strip(), round(x.start, 2), round(x.end, 2)) for s_ in segs for x in (s_.words or [])]
        W3.append({'file': f, 'words': words}); print(os.path.basename(f), len(words), 'words', flush=True)
    json.dump(W3, open('wc3_transcripts.json', 'w'))

def wc3_ipa(word, W3, k=3):
    """the name as WC3's actors said it: clips whose transcript has the word (Whisper's spelling), cut by its timing"""
    import librosa, phonemes as ph
    got = []
    for c in W3:
        hit = [x for x in c['words'] if norm(x[0]) == norm(word) or (len(norm(word)) > 5 and norm(x[0]).startswith(norm(word)))]
        if not hit: continue
        y, _ = librosa.load(c['file'], sr=16000); _, a, b = hit[0]
        seg = y[int(max(0, a - 0.04) * 16000):int((b + 0.06) * 16000)]
        if len(seg) >= 1600: got.append((''.join(ph.ipa(seg)), c['file']))
        if len(got) >= k: break
    if not got: return None
    best = min(got, key=lambda g: sum(ph.distance(g[0], o[0]) for o in got))
    return {'ipa': best[0], 'source': f'wc3: {os.path.basename(best[1])}', 'clips': len(got)}

# ---------------------------------------------------------------- 2. targets
def norm(w): return re.sub(r'[^a-z]', '', w.lower())

def wiki_targets():
    """single-word names with both a respelling and IPA (tight: no guessing which word of a long name a respelling is)"""
    W = json.load(open('wiki_pronunciations.json')); out = {}
    for title, v in W.items():
        if not v['ipa']: continue
        ipa = v['ipa'][0].strip('/[] '); resp = v['respell'][0] if v['respell'] else ''
        for nm in [title.split(' (')[0]] + v['bold']:
            ws = re.findall(r"[A-Za-z][A-Za-z']*[A-Za-z]", nm)
            iw = ipa.split(); rw = resp.split()
            if len(ws) == 1 and len(iw) == 1:
                out.setdefault(ws[0], {'ipa': ipa, 'respell': resp, 'source': f'wiki: {title}'})
            elif len(ws) == len(iw) and (not rw or len(rw) == len(ws)):
                for k, w in enumerate(ws):
                    out.setdefault(w, {'ipa': iw[k], 'respell': rw[k] if rw else '', 'source': f'wiki: {title}'})
    return out

def gap_words(n):
    """the n most frequent fantasy words of the quests that the wiki does not cover (wiki_pronounce.py's gap)"""
    import direct
    from wordfreq import zipf_frequency
    keys = {(r['questId'], r['kind']) for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] != 'none'}
    lines = collections.defaultdict(set)
    for q, k in keys:
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]", direct.clean(direct.Q.get(q, {}).get(direct.KINDS[k]) or '')):
            for part in w.strip("'").split('-'):
                part = part[:-2] if part.endswith("'s") else part
                if len(part) >= 3 and zipf_frequency(part.lower(), 'en') < 1.5: lines[part].add((q, k))
    def compound(w):
        lw = w.lower().rstrip('s')
        return any(zipf_frequency(lw[:i], 'en') >= 3.0 and zipf_frequency(lw[i:], 'en') >= 3.0 for i in range(3, len(lw) - 2))
    return [w for w in sorted(lines, key=lambda w: -len(lines[w])) if not compound(w)][:n], lines

def blizzard_ipa(word, voiced_lines, wm, k=3):
    """IPA of `word` as Blizzard's actors said it: up to k recorded lines whose text contains it; the name is found by
    aligning the known text with Whisper's words, cut out, and transcribed by the phoneme recognizer. The clip whose
    IPA is closest to the others wins (one bad cut cannot decide)"""
    import librosa, phonemes as ph
    from mpqget import MPQ
    hits = [v for v in voiced_lines if re.search(rf"\b{re.escape(word)}\b", v['text'], re.I)][:12]
    got = []
    for v in hits:
        if len(got) >= k: break
        os.makedirs(CLIPS, exist_ok=True)
        dst = f"{CLIPS}/{norm(v['file'])[-60:]}.wav"
        if not os.path.exists(dst):
            try: m = MPQ(v['mpq']); open(dst, 'wb').write(m.read(v['file'])); m.close()
            except Exception: continue
        try: y, _ = librosa.load(dst, sr=16000)
        except Exception: continue
        segs, _ = wm.transcribe(y, language='en', word_timestamps=True, initial_prompt=v['text'][:200])
        hw = [w for s in segs for w in (s.words or [])]
        known = re.findall(r"[A-Za-z][A-Za-z'\-]*", v['text'])
        ti = next((i for i, w in enumerate(known) if norm(w).startswith(norm(word))), None)
        if ti is None or not hw: continue
        sm = difflib.SequenceMatcher(None, [norm(w) for w in known], [norm(w.word) for w in hw])
        j = None
        for tag, a1, a2, b1, b2 in sm.get_opcodes():
            if a1 <= ti < a2 and tag in ('equal', 'replace'):
                j = min(b1 + (ti - a1), b2 - 1); break
        if j is None: continue
        a, b = max(0, hw[j].start - 0.04), hw[j].end + 0.06
        seg = y[int(a * 16000):int(b * 16000)]
        if len(seg) < 1600: continue
        got.append((''.join(ph.ipa(seg)), v['file'], v['text'][:90]))
    if not got: return None
    best = min(got, key=lambda g: sum(ph.distance(g[0], o[0]) for o in got))
    return {'ipa': best[0], 'source': f'blizzard: {best[1]} "{best[2]}"', 'clips': len(got)}

def targets(n=200):
    from faster_whisper import WhisperModel
    from asr_check import MODEL
    T = wiki_targets(); print(len(T), 'single-word wiki targets')
    gw, lines = gap_words(int(n))
    V = json.load(open(VOICED))
    wm = WhisperModel(MODEL, device='cuda', compute_type='float16')
    W3 = json.load(open('wc3_transcripts.json')) if os.path.exists('wc3_transcripts.json') else []
    for i, w in enumerate(gw):
        if w in T and not T[w]['source'].startswith('blizzard'): continue
        t = blizzard_ipa(w, V, wm) or wc3_ipa(w, W3)
        if t: T[w] = dict(t, respell='')
        if i % 20 == 0: print(f'{i}/{len(gw)} gap words; {sum(1 for x in T.values() if x["source"].startswith("blizzard"))} found in recordings', flush=True)
    for w in T: T[w]['lines'] = len(lines.get(w, ()))
    json.dump(T, open(TARGETS, 'w'), indent=1, ensure_ascii=False)
    c = collections.Counter(x['source'].split(':')[0] for x in T.values())
    print(len(T), 'targets:', dict(c))

# ---------------------------------------------------------------- 3. search
IPA_LETTERS = [('tʃ', 'ch'), ('dʒ', 'j'), ('aɪ', 'eye'), ('ɑɪ', 'eye'), ('eɪ', 'ay'), ('oʊ', 'oh'), ('aʊ', 'ow'), ('ɔɪ', 'oy'),
               ('ɑːɹ', 'ar'), ('ɔːɹ', 'or'), ('ɑː', 'ah'), ('ɔː', 'aw'), ('iː', 'ee'), ('uː', 'oo'), ('ɜː', 'er'), ('ɚ', 'er'),
               ('æ', 'a'), ('ɑ', 'ah'), ('ɒ', 'o'), ('ɔ', 'aw'), ('ə', 'a'), ('ʌ', 'u'), ('ɛ', 'e'), ('e', 'e'), ('ɪ', 'i'),
               ('i', 'ee'), ('ʊ', 'oo'), ('u', 'oo'), ('θ', 'th'), ('ð', 'th'), ('ʃ', 'sh'), ('ʒ', 'zh'), ('ŋ', 'ng'), ('ɹ', 'r'),
               ('ɾ', 't'), ('ʁ', 'r'), ('ɡ', 'g'), ('x', 'k'), ('ɫ', 'l'), ('əl', 'ul'), ('ᵻ', 'i'), ('ʔ', ''), ('j', 'y')]
VOWEL = set('aeiouy')

def from_ipa(ipa):
    """a plain spelling of the target IPA, hyphenated before each consonant that starts a new vowel's syllable"""
    s = re.sub(r"[ˈˌː./\[\]\s'\-]", '', ipa); out, i = [], 0
    tbl = sorted(IPA_LETTERS, key=lambda x: -len(x[0]))
    while i < len(s):
        for a, b in tbl:
            if s.startswith(a, i): out.append(b); i += len(a); break
        else: out.append(s[i]); i += 1
    word = ''.join(out)
    syl = re.sub(r'([aeiouy]+)([^aeiouy\-])(?=[aeiouy])', r'\1-\2', word)
    return [word, syl]

def candidates(word, t):
    c = [word]
    r = (t.get('respell') or '').replace('ə', 'uh').lower()
    if r:
        c.append(r)
        for a, b in (('ih', 'i'), ('uh', 'a'), ('ahl', 'al'), ('ah', 'a'), ('wihn', 'win'), ('ee', 'i')):
            if a in r: c.append(r.replace(a, b))
        c.append(r.replace('-', ''))
    c += from_ipa(t['ipa'])
    return list(dict.fromkeys(x for x in c if x))[:7]

def search():
    import librosa, render, phonemes as ph
    render.use_server(LV.RENDERERS["0"])
    T = json.load(open(TARGETS)); R = json.load(open(RESULT)) if os.path.exists(RESULT) else {}
    spk = render.speaker_ref({'npc_id': 'go:narrator', 'race': 'unknown', 'clone_ref': 'design:narrator', 'npc_name': 'n'})
    clip = render.style_clip('steady_explaining', 'male', 'Human')
    for n, (word, t) in enumerate(sorted(T.items(), key=lambda x: -x[1].get('lines', 0))):
        if word in R: continue
        scored = []
        for cand in candidates(word, t):
            p = render.render_beat(CARRIER.format(cand), spk, clip, f"pron_{norm(word)}_{len(scored)}", alpha=0.35,
                                   emo_text='calm and matter-of-fact')
            s = ''.join(ph.ipa(librosa.load(p, sr=16000)[0]))
            m = re.search(r'(?:f(?:ɔːɹ|ɚ|ɔː|ɜː|ə))(.*?)(?:ɹ?æt|ət)fɜːstlaɪt', s)
            if not m: continue
            scored.append((round(ph.distance(m.group(1), t['ipa']), 3), cand, m.group(1)))
        if not scored: R[word] = {'status': 'no_measure'}; continue
        plain = next((d for d, c, _ in scored if c == word), 1.0)
        best = min(scored)
        adopt = best[1] != word and best[0] <= plain - ADOPT_MARGIN and best[0] <= ADOPT_MAX
        R[word] = {'target': t['ipa'], 'source': t['source'], 'plain': plain, 'best': best[1], 'best_dist': best[0],
                   'heard': best[2], 'adopt': adopt, 'tried': scored,
                   'status': 'adopt' if adopt else 'fine' if plain <= ADOPT_MAX else 'review'}
        json.dump(R, open(RESULT, 'w'), indent=1, ensure_ascii=False)
        print(f"{n:4} {word:16} plain {plain:.2f} -> {best[1]!r} {best[0]:.2f}  {R[word]['status']}", flush=True)
    apply_results(R)

def apply_results(R=None):
    """winners into pronounce.json (both capitalisations), recorded under _auto with their evidence"""
    R = R or json.load(open(RESULT)); P = json.load(open('pronounce.json'))
    auto = P.setdefault('_auto', {})
    W = json.load(open('wiki_pronunciations.json'))
    def trusted(w, r):
        # only the wiki is an authority: targets measured from Blizzard's audio came out as garbage on short cuts
        # (the recognizer heard Chinese: Durotar "tɕiou5ʐə1thɑ5"; "Theramore" -> "de-ra-maw"), 2026-10-13
        if not r.get('source', '').startswith('wiki: '): return False
        # the word must BE the article's name (Highborne got Quel'dorei's respelling, Arathor got Arathi's) ...
        v = W.get(r['source'][6:], {}); names = [r['source'][6:]] + v.get('bold', [])
        if not any(norm(w) in [norm(x) for x in re.findall(r"[A-Za-z][A-Za-z']*[A-Za-z]", n)] for n in names): return False
        # ... and a plain reading nowhere near the target means the target is some other word's
        return r['plain'] < 0.8 and w not in NOT_THIS_WORD
    for w, r in R.items():
        if r.get('status') != 'adopt': continue
        if not trusted(w, r): r['status'] = 'review_untrusted'; continue
        for form in {w, w[:1].upper() + w[1:], w.lower()}:
            if form not in P['words'] or form in auto:
                P['words'][form] = r['best'] if form[:1].islower() or not r['best'][:1].isalpha() else r['best'][:1].upper() + r['best'][1:]
                auto[form] = f"{r['source']} | target {r['target']} | plain {r['plain']} -> {r['best_dist']}"
    json.dump(P, open('pronounce.json', 'w'), indent=1, ensure_ascii=False)
    st = collections.Counter(r.get('status') for r in R.values())
    print('pronounce.json updated:', dict(st))

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    a = sys.argv[1:]
    {'voiced': voiced, 'wc3': wc3, 'cinematics': cinematics, 'targets': lambda: targets(*(a[1:] or [200])), 'search': search, 'apply': apply_results}[a[0]]()
