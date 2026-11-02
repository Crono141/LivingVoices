"""The producer's pronunciation sheet (2026-10-13): names with no official pronunciation, my guesses, his corrections.
  ../.venv/bin/python ../tools/pronounce_review.py import [sheet.xlsx]     (run from data/)
For each row: his correction if he wrote one, else my guess -- unless the row says it reads fine as written (column E
"yes") or the spelling to use is the name itself. The result goes into pronounce.json (both capitalisations), marked
under _review; lines already rendered that contain a changed name go back to 'todo'.
"""
import json, os, re, sqlite3, sys
import lvconfig as LV
SHEET = f'{LV.COMFY_OUT}/pronunciation_review.xlsx'

# my sheet turned "ih" into a lone "i" syllable, which the model reads as "eye" ("mag-i-strix" -> mag-EYE-strix; tested
# 2026-10-13): a short i must sit in a syllable that ends in a consonant ("ma-jiss-trix", "il-lid-ar-ee"). These replace
# my guess when the producer left the row blank.
FIXED = {'Illidari': 'il-lid-ar-ee', 'Eranikus': 'eh-ran-ik-us', 'Obnoticus': 'ob-not-ik-us', 'Capacitorium': 'kah-pass-it-or-ee-um',
         'Claximus': 'klax-im-us', 'Sapphiron': 'saf-ir-on', 'Itharius': 'ith-ar-ee-us', 'Nazzivus': 'naz-iv-us',
         'Latronicus': 'lah-tron-ik-us', 'Ithania': 'ith-ay-nee-ah', 'gizmonitor': 'giz-mon-it-or'}
LONE_I = re.compile(r'(^|-)i(-|$)')

def load(path):
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True)['Names']; out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name, _, guess, _, fine, corr, _, note = (list(row) + [None] * 8)[:8]
        if not name: continue
        if (note or '').startswith('typo'): continue      # database typos: text_fixes.json, not pronunciations
        corr = (corr or '').strip()
        if corr and LONE_I.search(corr): print(f'!! {name}: "{corr}" has a lone "i" syllable -- read as "eye"')
        use = corr or ('' if (fine or '').strip().lower() == 'yes' else FIXED.get(name, (guess or '').strip()))
        if use and use.lower() != name.lower(): out[name] = use
    return out

def apply(path=SHEET):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import direct, overnight as ov
    new = load(path); P = json.load(open('pronounce.json')); rv = P.setdefault('_review', {}); changed = set()
    for name, use in new.items():
        for form in {name, name[:1].upper() + name[1:], name.lower()}:
            val = use if form[:1].islower() else use[:1].upper() + use[1:]
            if P['words'].get(form) != val: P['words'][form] = val; rv[form] = 'pronunciation_review.xlsx'; changed.add(form)
    json.dump(P, open('pronounce.json', 'w'), indent=1, ensure_ascii=False)
    pat = re.compile(r'\b(' + '|'.join(re.escape(w) for w in sorted(changed, key=len, reverse=True)) + r')\b') if changed else None
    db = sqlite3.connect(ov.DB); n = 0
    if pat:
        for nm, q, k in db.execute("SELECT name, questId, kind FROM lines WHERE status IN ('done','rendered','review')").fetchall():
            if pat.search(direct.Q.get(q, {}).get(direct.KINDS[k]) or ''):
                if os.path.exists(f'render/{nm}.mp3'): os.remove(f'render/{nm}.mp3')
                db.execute("UPDATE lines SET status='todo', seed=1, tries=0, score=NULL WHERE name=?", (nm,)); n += 1
        db.commit()
    print(f'{len(new)} names respelled ({len(changed)} entries changed); {n} rendered lines re-queued')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    apply(*(sys.argv[2:3] or [SHEET])) if sys.argv[1] == 'import' else print(__doc__)
