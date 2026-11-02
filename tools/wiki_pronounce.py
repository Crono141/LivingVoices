"""Official pronunciations from the Warcraft Wiki (warcraft.wiki.gg), 2026-10-13: the producer wanted an existing
guide, not a model's guesses. Articles carry {{IPA|...}} and/or {{respell|...}} in their opening, many sourced from
Blizzard (BlizzCon, Hearthstone announcements, the Exploring Azeroth books). IPA-only entries are converted to a
respelling by a fixed symbol table -- no model.

  ../.venv/bin/python ../tools/wiki_pronounce.py harvest    -> data/wiki_pronunciations.json  (name -> entries)
  ../.venv/bin/python ../tools/wiki_pronounce.py gap        how much of the game's fantasy vocabulary is still uncovered
Run from data/.
"""
import collections, csv, json, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
UA = {'User-Agent': 'LivingVoices pronunciation lookup (personal project)'}
API = 'https://warcraft.wiki.gg/api.php'
OUT = 'wiki_pronunciations.json'

def get(params):
    req = urllib.request.Request(API + '?' + urllib.parse.urlencode(dict(params, format='json')), headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=60))

# IPA -> an English respelling (stress: the syllable after a primary-stress mark in capitals). Longest symbols first.
IPA = [('tʃ', 'ch'), ('dʒ', 'j'), ('aɪ', 'eye'), ('ɑɪ', 'eye'), ('eɪ', 'ay'), ('oʊ', 'oh'), ('aʊ', 'ow'), ('ɔɪ', 'oy'),
       ('ɪə', 'eer'), ('ɛə', 'air'), ('ʊə', 'oor'), ('ɑː', 'ah'), ('ɔː', 'aw'), ('iː', 'ee'), ('uː', 'oo'), ('ɜː', 'ur'),
       ('ɚ', 'er'), ('ɝ', 'ur'), ('æ', 'a'), ('ɑ', 'ah'), ('ɒ', 'o'), ('ɔ', 'aw'), ('ə', 'uh'), ('ʌ', 'uh'), ('ɛ', 'eh'),
       ('e', 'eh'), ('ɪ', 'ih'), ('i', 'ee'), ('ʊ', 'uu'), ('u', 'oo'), ('θ', 'th'), ('ð', 'th'), ('ʃ', 'sh'), ('ʒ', 'zh'),
       ('ŋ', 'ng'), ('ɹ', 'r'), ('ɾ', 't'), ('ʁ', 'r'), ('ɡ', 'g'), ('x', 'kh'), ('ʔ', ''), ('j', 'y'), ('ː', ''), ('ˌ', '-')]

def ipa_to_respell(ipa):
    s = ipa.strip().strip('/[]').replace('.', '-')
    words = []
    for w in s.split():
        stressed, out, i = False, [], 0
        syl = []
        while i < len(w):
            if w[i] == 'ˈ':
                if syl: out.append(''.join(syl)); syl = []
                stressed = True; out.append('|'); i += 1; continue
            if w[i] == '-':
                if syl: out.append(''.join(syl)); syl = []
                out.append('-'); i += 1; continue
            for a, b in IPA:
                if w.startswith(a, i): syl.append(b); i += len(a); break
            else: syl.append(w[i]); i += 1
        if syl: out.append(''.join(syl))
        # capitalise the syllable that follows a stress mark
        res, up = [], False
        for t in out:
            if t == '|': up = True; res.append('-'); continue
            if up and t not in ('-',): res.append(t.upper()); up = False
            else: res.append(t)
        words.append(re.sub(r'-+', '-', ''.join(res)).strip('-'))
    return ' '.join(words)

def harvest():
    titles = set()
    for tpl in ('Template:Respell', 'Template:IPA'):
        cont = {}
        while True:
            d = get(dict(action='query', list='embeddedin', eititle=tpl, eilimit=500, einamespace=0, **cont))
            titles |= {x['title'] for x in d['query']['embeddedin']}
            if 'continue' not in d: break
            cont = {'eicontinue': d['continue']['eicontinue']}
    titles = sorted(titles); out = {}
    for i in range(0, len(titles), 50):
        d = get(dict(action='query', prop='revisions', rvprop='content', rvslots='main', titles='|'.join(titles[i:i + 50])))
        for p in d['query']['pages'].values():
            txt = p.get('revisions', [{}])[0].get('slots', {}).get('main', {}).get('*', '')
            lead = re.split(r'\n==', txt, 1)[0]
            rs = re.findall(r'\{\{[Rr]espell\|([^}|]*)', lead)
            ip = re.findall(r'\{\{IPA\|([^}|]*)', lead)
            if not rs and not ip: continue
            bold = re.findall(r"'''([^']+(?:'[^']+)*)'''", lead)
            out[p['title']] = {'bold': bold[:3], 'respell': rs[:3], 'ipa': ip[:3],
                               'from_ipa': [ipa_to_respell(x) for x in ip[:3]] if not rs else []}
        time.sleep(1)
    json.dump(out, open(OUT, 'w'), indent=1, ensure_ascii=False)
    print(len(titles), 'articles;', len(out), 'with a pronunciation in the lead;',
          sum(1 for v in out.values() if v['respell']), 'respelled,', sum(1 for v in out.values() if v['from_ipa']), 'from IPA only')

def word_index():
    """the fantasy word (one word of an article title or its bold name) -> (respelling, title)"""
    idx = {}
    for title, v in json.load(open(OUT)).items():
        resp = (v['respell'] or v['from_ipa'] or [''])[0]
        names = [title.split(' (')[0]] + v['bold']
        rw = resp.split()
        for nm in names:
            ws = re.findall(r"[A-Za-z][A-Za-z']*[A-Za-z]", nm)
            # the whole name as one key too: "Ahn'Qiraj" is one word in the quest text, "AHN kee-RAHZH" in the wiki
            if rw: idx.setdefault(re.sub(r"[^a-z]", '', nm.lower()), (' '.join(rw), title))
            if len(ws) == len(rw) and rw:
                for w, r in zip(ws, rw): idx.setdefault(w.lower(), (r, title))
            elif len(rw) == 1 and ws:
                # one respelled word for a multi-word name: it belongs to the name's non-English word
                from wordfreq import zipf_frequency
                odd = [w for w in ws if zipf_frequency(w.lower(), 'en') < 1.5]
                if len(odd) == 1: idx.setdefault(odd[0].lower(), (rw[0], title))
    return idx

def gap():
    from wordfreq import zipf_frequency
    import direct
    keys = {(r['questId'], r['kind']) for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] != 'none'}
    lines = collections.defaultdict(set)
    for q, k in keys:
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]", direct.clean(direct.Q.get(q, {}).get(direct.KINDS[k]) or '')):
            for part in w.strip("'").split('-'):
                part = part[:-2] if part.endswith("'s") else part          # "Scourge's" is "Scourge", an English word
                if len(part) >= 3 and zipf_frequency(part.lower(), 'en') < 1.5: lines[part].add((q, k))
    def compound(w):        # Ironforge, Plaguelands, Stonetalon: two ordinary English words, read as written
        lw = w.lower().rstrip('s')
        return any(zipf_frequency(lw[:i], 'en') >= 3.0 and zipf_frequency(lw[i:], 'en') >= 3.0 for i in range(3, len(lw) - 2))
    idx = word_index()
    known = json.load(open('pronounce.json'))['words']
    groups = {'wiki': set(), 'ours': set(), 'compound': set(), 'gap': set()}
    for w in lines:
        lw = w.lower()
        flat = re.sub(r"[^a-z]", '', lw)
        base = flat[:-1] if flat.endswith('s') and flat[:-1] in idx else flat if flat in idx else lw[:-1] if lw.endswith('s') and lw[:-1] in idx else lw
        g = 'wiki' if base in idx else 'ours' if w in known else 'compound' if compound(w) else 'gap'
        groups[g].add(w)
    total = set().union(*lines.values())
    print(f'{len(lines)} fantasy words in {len(total)} of {len(keys)} lines')
    for g, ws in groups.items():
        cov = set().union(*(lines[w] for w in ws)) if ws else set()
        print(f'  {g:9} {len(ws):5} words, in {len(cov):5} lines')
    gap_words = sorted(groups['gap'], key=lambda w: -len(lines[w]))
    gap_lines = set().union(*(lines[w] for w in gap_words))
    others = groups['wiki'] | groups['ours'] | groups['compound']
    only_gap = {l for l in gap_lines if not any(l in lines[w] for w in others)}
    print(f'lines with at least one uncovered word: {len(gap_lines)}')
    for n in (25, 100, 300, 1000):
        print(f'  the {n:4} most frequent uncovered words reach {len(set().union(*(lines[w] for w in gap_words[:n])))} lines')
    print('most frequent uncovered:', ', '.join(f'{w}({len(lines[w])})' for w in gap_words[:70]))
    print('singletons (one line each):', sum(1 for w in gap_words if len(lines[w]) == 1))

if __name__ == '__main__':
    import os; os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'harvest': harvest, 'gap': gap}[sys.argv[1]]()
