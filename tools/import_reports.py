"""Lines players reported ("/lv bad <note>", the Living Voices add-on) onto the review page.

    python3 ../tools/import_reports.py            (from data/)   new reports -> review, with their notes
    python3 ../tools/import_reports.py --list     show every report, import nothing
    python3 ../tools/import_reports.py --queue    (the weekly run) a reported line is RETAKEN -- six fresh seeds --
                                                  instead of going to review; all six failing sends it there as usual

The realm keeps them in acore_characters.living_voices_report (server/sql/60_living_voices_report.sql, written by
server/lua/living_voices_report.lua). Read with the read-only login in config.local.json (db_reader_cnf; SELECT only), so what has been taken is kept
here, in data/reports_imported.json (the last report id), not marked on the realm. A reported line goes to 'review'
with fault 'reported in game' -- first on the page -- its takes from its latest night, and the reporter's note.

(2026-11-02) Players on other realms report through GitHub: the add-on hands them a link to the repository's "Bad
voice line" issue form, filled in (.github/ISSUE_TEMPLATE/bad-line.yml). Open issues labelled "bad line" in
config.local.json's github_repo are read with the gh CLI (logged in), taken like a realm report, and labelled
"imported" so they are not taken twice. No github_repo, or no database login: that source is skipped.
"""
import json, os, re, sqlite3, subprocess, sys
import lvconfig as LV

SEEN = 'reports_imported.json'
RACE = {1: 'human', 2: 'orc', 3: 'dwarf', 4: 'night elf', 5: 'undead', 6: 'tauren', 7: 'gnome', 8: 'troll', 10: 'blood elf', 11: 'draenei'}
CLASS = {1: 'warrior', 2: 'paladin', 3: 'hunter', 4: 'rogue', 5: 'priest', 6: 'death knight', 7: 'shaman', 8: 'mage', 9: 'warlock', 11: 'druid'}

def realm_reports(after=0):
    q = ("SELECT id, reported_at, char_name, race, class, gender, line, npc, title, zone, note, addon_version "
         f"FROM acore_characters.living_voices_report WHERE id > {int(after)} ORDER BY id")
    out = subprocess.run(['mariadb', f'--defaults-extra-file={LV.DB_CNF}', '-N', '-B',
                          '--raw', '-e', q], capture_output=True, text=True)
    if out.returncode:
        sys.exit('cannot read the reports: ' + out.stderr.strip() +
                 ('\n(the reader has no grant on the new table yet: the keeper runs `92-acore-mysql.sh reader`)'
                  if 'denied' in out.stderr else ''))
    cols = 'id at char race cls gender line npc title zone note v'.split()
    rows = [dict(zip(cols, l.split('\t'))) for l in out.stdout.splitlines() if l]
    for r in rows:
        r['who'] = f"{r['char']}, {RACE.get(int(r['race']), '?')} {CLASS.get(int(r['cls']), '?')}"; r['key'] = f"#{r['id']}"
    return rows

def _field(body, label):
    """one field of a GitHub issue form's body ('### Label' then its value; '_No response_' when left empty)"""
    m = re.search(rf'^###\s*{re.escape(label)}\s*\n(.*?)(?=^###\s|\Z)', body or '', re.M | re.S)
    v = (m.group(1).strip() if m else '')
    return '' if v == '_No response_' else v

def github_reports(done):
    """open 'bad line' issues not taken yet -> report rows (one per line named; 'More lines' rows too)"""
    repo = LV.CFG.get('github_repo')
    if not repo: return []
    out = subprocess.run(['gh', 'issue', 'list', '-R', repo, '--label', 'bad line', '--state', 'open', '--limit', '500',
                          '--json', 'number,body,author,createdAt,labels'], capture_output=True, text=True)
    if out.returncode: print('!! GitHub issues not read:', out.stderr.strip()[:300]); return []
    rows = []
    for i in json.loads(out.stdout):
        if i['number'] in done or any(l['name'] == 'imported' for l in i['labels']): continue
        b = i['body']; who = f"@{i['author']['login']} on GitHub"
        base = dict(at=i['createdAt'][:19].replace('T', ' '), who=who, zone=_field(b, 'Zone'), v=_field(b, 'Add-on version'),
                    issue=i['number'], key=f"GitHub #{i['number']}")
        rows.append(dict(base, line=_field(b, 'Line'), npc=_field(b, 'Speaker'), title=_field(b, 'Quest'), note=_field(b, "What's wrong")))
        for l in _field(b, 'More lines').splitlines():
            parts = [x.strip() for x in l.split('|')]
            if parts and parts[0]:
                rows.append(dict(base, line=parts[0], npc=parts[1] if len(parts) > 1 else '', title='',
                                 note=parts[2] if len(parts) > 2 else ''))
    return rows

def mark_imported(numbers):
    repo = LV.CFG.get('github_repo')
    subprocess.run(['gh', 'label', 'create', 'imported', '-R', repo, '--color', 'BFD4F2', '--description',
                    'taken into the voice-over queue'], capture_output=True)
    for n in sorted(set(numbers)):
        subprocess.run(['gh', 'issue', 'edit', str(n), '-R', repo, '--add-label', 'imported'], capture_output=True)

def queue(c, name):
    """six fresh seeds after every one already tried (a seed already heard is never tried again)"""
    c.execute("UPDATE lines SET status='todo', seed=(SELECT MAX(seed)+1 FROM takes t WHERE t.name=lines.name), "
              "last_seed=(SELECT MAX(seed)+6 FROM takes t WHERE t.name=lines.name) WHERE name=?", (name,))

def said(heard):
    """the transcript alone: earlier flags -- '(best of ...)', '(accepted 10-31)', '(missed stop: ...)' -- taken off"""
    return re.sub(r'^(?:\([^)]*\)\s*)+', '', heard or '')

if __name__ == '__main__':
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else {'last_id': 0}
    seen.setdefault('count', {})                   # line -> reports so far: a line reported again after its retake is
                                                   # no bad take but a casting or pronunciation fault, for a session
    seen.setdefault('github', [])                  # issue numbers taken
    realm = os.path.exists(LV.DB_CNF or '')
    if '--list' in sys.argv:
        for r in (realm_reports() if realm else []) + github_reports(set()):
            print(f"{r['key']} {r['at']} {r['line']:26s} {r['npc'][:24]:24s} {r['who']}: {r['note']}")
        sys.exit()
    new = (realm_reports(seen['last_id']) if realm else []) + github_reports(set(seen['github']))
    c = sqlite3.connect('overnight.sqlite')
    for r in new:
        row = c.execute("SELECT seed, heard, status FROM lines WHERE name=?", (r['line'],)).fetchone()
        if not row:
            print(f"{r['key']} {r['line']}: no such line (from {r['who']}: {r['note']!r}) -- skipped"); continue
        seed, heard, status = row
        note = f': "{r["note"]}"' if r['note'] else ''
        flag = f"(best of 1 takes: seed {seed}, reported in game) (reported {r['at']} by {r['who']} in {r['zone'] or '?'}{note}) "
        seen['count'][r['line']] = seen['count'].get(r['line'], 0) + 1
        again = f"  REPORTED {seen['count'][r['line']]} TIMES" if seen['count'][r['line']] > 1 else ''
        if '--queue' in sys.argv:
            c.execute("UPDATE lines SET heard=? WHERE name=?", (flag + said(heard), r['line'])); queue(c, r['line'])
            print(f"{r['key']} {r['line']} ({r['npc']}) -> retake{note}   [was {status}]{again}")
        else:
            c.execute("UPDATE lines SET status='review', heard=? WHERE name=?", (flag + said(heard), r['line']))
            print(f"{r['key']} {r['line']} ({r['npc']}) -> review{note}   [was {status}]{again}")
    if new:
        c.commit()
        ids = [int(r['id']) for r in new if 'id' in r]
        if ids: seen['last_id'] = max(ids)
        nums = [r['issue'] for r in new if 'issue' in r]
        if nums: seen['github'] = sorted(set(seen['github']) | set(nums)); mark_imported(nums)
        json.dump(seen, open(SEEN, 'w'))
    print(f'{len(new)} new report(s)')
