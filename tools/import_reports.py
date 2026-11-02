"""Lines players reported in game ("/lv bad <note>", the Living Voices add-on) onto the review page.

    python3 ../tools/import_reports.py            (from data/)   new reports -> review, with their notes
    python3 ../tools/import_reports.py --list     show every report, import nothing
    python3 ../tools/import_reports.py --queue    (the weekly run) a reported line is RETAKEN -- six fresh seeds --
                                                  instead of going to review; all six failing sends it there as usual

The realm keeps them in acore_characters.living_voices_report (server/sql/60_living_voices_report.sql, written by
server/lua/living_voices_report.lua). Read with the read-only login in config.local.json (db_reader_cnf; SELECT only), so what has been taken is kept
here, in data/reports_imported.json (the last report id), not marked on the realm. A reported line goes to 'review'
with fault 'reported in game' -- first on the page -- its takes from its latest night, and the reporter's note.
"""
import json, os, re, sqlite3, subprocess, sys
import lvconfig as LV

SEEN = 'reports_imported.json'
RACE = {1: 'human', 2: 'orc', 3: 'dwarf', 4: 'night elf', 5: 'undead', 6: 'tauren', 7: 'gnome', 8: 'troll', 10: 'blood elf', 11: 'draenei'}
CLASS = {1: 'warrior', 2: 'paladin', 3: 'hunter', 4: 'rogue', 5: 'priest', 6: 'death knight', 7: 'shaman', 8: 'mage', 9: 'warlock', 11: 'druid'}

def reports(after=0):
    q = ("SELECT id, reported_at, char_name, race, class, gender, line, npc, title, zone, note, addon_version "
         f"FROM acore_characters.living_voices_report WHERE id > {int(after)} ORDER BY id")
    out = subprocess.run(['mariadb', f'--defaults-extra-file={LV.DB_CNF}', '-N', '-B',
                          '--raw', '-e', q], capture_output=True, text=True)
    if out.returncode:
        sys.exit('cannot read the reports: ' + out.stderr.strip() +
                 ('\n(the reader has no grant on the new table yet: the keeper runs `92-acore-mysql.sh reader`)'
                  if 'denied' in out.stderr else ''))
    cols = 'id at char race cls gender line npc title zone note v'.split()
    return [dict(zip(cols, l.split('\t'))) for l in out.stdout.splitlines() if l]

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
    if '--list' in sys.argv:
        for r in reports():
            print(f"#{r['id']} {r['at']} {r['line']:26s} {r['npc'][:24]:24s} {r['char']} ({RACE.get(int(r['race']), '?')} "
                  f"{CLASS.get(int(r['cls']), '?')}): {r['note']}")
        sys.exit()
    new = reports(seen['last_id'])
    c = sqlite3.connect('overnight.sqlite')
    for r in new:
        row = c.execute("SELECT seed, heard, status FROM lines WHERE name=?", (r['line'],)).fetchone()
        who = f"{r['char']}, {RACE.get(int(r['race']), '?')} {CLASS.get(int(r['cls']), '?')}"
        if not row:
            print(f"#{r['id']} {r['line']}: no such line (from {who}: {r['note']!r}) -- skipped"); continue
        seed, heard, status = row
        note = f': "{r["note"]}"' if r['note'] else ''
        flag = f"(best of 1 takes: seed {seed}, reported in game) (reported {r['at']} by {who} in {r['zone'] or '?'}{note}) "
        seen['count'][r['line']] = seen['count'].get(r['line'], 0) + 1
        again = f"  REPORTED {seen['count'][r['line']]} TIMES" if seen['count'][r['line']] > 1 else ''
        if '--queue' in sys.argv:
            c.execute("UPDATE lines SET heard=? WHERE name=?", (flag + said(heard), r['line'])); queue(c, r['line'])
            print(f"#{r['id']} {r['line']} ({r['npc']}) -> retake{note}   [was {status}]{again}")
        else:
            c.execute("UPDATE lines SET status='review', heard=? WHERE name=?", (flag + said(heard), r['line']))
            print(f"#{r['id']} {r['line']} ({r['npc']}) -> review{note}   [was {status}]{again}")
    if new:
        c.commit(); seen['last_id'] = max(int(r['id']) for r in new); json.dump(seen, open(SEEN, 'w'))
    print(f'{len(new)} new report(s)')
