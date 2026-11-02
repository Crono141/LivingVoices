"""The nightly run (wow-voiceover.timer, 01:00 every night). It began as the weekly patch run (2026-10-31, the producer:
"run the patches in batches and have a fresh update available on the web share after each run"); the same evening the
race/class work brought the nightly rendering back ("its only the bug reports from the reporter that need to run
weekly"), so this is the nightly job and the reports are its Sunday step:

  1. SUNDAYS (or --reports): the week's in-game reports ("/lv bad", import_reports.py --queue): each reported line is
     retaken, six fresh seeds
  2. the producer's marks on the review page since the line's latest takes: accept -> that take is the line's file,
     retry -> six fresh seeds; "look closer" and notes wait for a session with Claude (listed in the summary)
  3. if anything is queued: the overnight runner until 09:00 on both cards (its own director, speech check, retake
     rounds, and review for whatever fails every seed)
  3b. splice prep for the race/class sentences (splices.py, card 1): takes aligned, clips trimmed/paced/padded into
     render64/
  4. every line re-rendered since its 64 kbps copy re-encoded (render64/), the release built (build_release.py: the
     cumulative LivingVoices.patch.MPQ and the update zip), and both zips put on the client share as LivingVoices.zip
     and LivingVoices-update.zip -- names that never change, which the portal serves from there (per-file aliases in
     the portal's lighttpd-tls.conf), so a new update is live with no sudo and no page edit
  5. a summary in overnight_reports/nightly-<date>.md

    ~/ComfyUI/venv/bin/python ../tools/nightly.py [--dry-run] [--reports]       (from data/)
"""
import datetime as dt, glob, json, os, re, shutil, sqlite3, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import overnight

VO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT, SHARE = f'{VO}/client', LV.SHARE
DRY = '--dry-run' in sys.argv
out = []
def note(s=''): print(s, flush=True); out.append(s)

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def reports():
    r = run(['python3', f'{VO}/tools/import_reports.py'] + ([] if DRY else ['--queue']))
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if r.returncode: note(f'**Reports could not be read:** {r.stderr.strip()[:300]}'); return
    note('## In-game reports'); note()
    for l in lines: note(f'- {l}')
    again = [l for l in lines if 'REPORTED' in l]
    if again: note(); note(f'**{len(again)} line(s) reported again after a retake** -- not a bad take: a casting or '
                           'pronunciation fault, for a session with Claude.')
    note()

def decisions(c):
    """the review page's marks newer than the line's latest take (the page's own rule)"""
    applied, waiting = [], []
    for nm, dec, seed, txt, upd in c.execute(
            "SELECT d.name, d.decision, d.seed, d.note, d.updated FROM review_decisions d JOIN lines l USING(name) "
            "WHERE l.status='review'").fetchall():
        latest = c.execute("SELECT MAX(created) FROM takes WHERE name=?", (nm,)).fetchone()[0] or ''
        if (upd or '') < latest: continue
        if dec == 'accept' and seed is not None:
            t = c.execute("SELECT raw, heard, path FROM takes WHERE name=? AND seed=?", (nm, seed)).fetchone()
            if not t or not t[2] or not os.path.exists(t[2]): waiting.append((nm, f'accept seed {seed}: take not found')); continue
            if not DRY:
                shutil.copy2(t[2], f'render/{nm}.mp3')
                c.execute("UPDATE lines SET status='done', seed=?, score=?, heard=?, updated=? WHERE name=?",
                          (seed, t[0], f'(accepted {dt.date.today():%m-%d}) ' + (t[1] or ''), overnight.now(), nm))
            applied.append((nm, f'accepted seed {seed}'))
        elif dec == 'retry':
            if not DRY:
                c.execute("UPDATE lines SET status='todo', seed=(SELECT MAX(seed)+1 FROM takes t WHERE t.name=lines.name), "
                          "last_seed=(SELECT MAX(seed)+6 FROM takes t WHERE t.name=lines.name) WHERE name=?", (nm,))
            applied.append((nm, 'retry: six fresh seeds'))
        else:
            waiting.append((nm, f'{dec or "note"}: {txt or ""}'.strip()))
    if not DRY: c.commit()
    note('## Review marks'); note()
    for nm, what in applied: note(f'- {nm}: {what}')
    if waiting:
        note(); note('**Waiting for a session with Claude:**')
        for nm, what in waiting: note(f'- {nm}: {what}')
    if not applied and not waiting: note('- none')
    note()

def render_queue(c):
    # 'new' too: a line not directed yet (a quest added from the live realm, extract_live.py) -- the runner's own
    # director thread directs it, then the cards render it
    n = c.execute("SELECT COUNT(*) FROM lines WHERE status IN ('todo', 'new', 'rendered')").fetchone()[0]
    note('## Retakes'); note()
    if not n: note('- nothing queued'); note(); return
    note(f'- {n} line(s) queued; the overnight runner until 09:00')
    if DRY: note(); return
    with open('overnight_reports/run.log', 'a') as log:
        subprocess.run([f'{os.path.expanduser("~")}/ComfyUI/venv/bin/python', '-W', 'ignore', f'{VO}/tools/overnight.py', 'run',
                        '--until', '09:00', '--force'], stdout=log, stderr=log)
    st = dict(c.execute("SELECT status, COUNT(*) FROM lines GROUP BY status").fetchall())
    rev = [r[0] for r in c.execute("SELECT name FROM lines WHERE status='review'")]
    note(f'- after the run: {st}')
    if rev: note(f'- **on the review page:** {", ".join(rev)}')
    note()

def splices():
    """the race/class clips ready for the build (splices.py, in the speech check's venv, on card 1)"""
    note('## Race and class'); note()
    if DRY: note('- (dry run)'); note(); return 0
    # the venv's own CUDA libraries, as the speech check runs (overnight.check): Whisper hears the narrated/morphed splices
    libs = ':'.join(sorted(glob.glob(f'{VO}/.venv/lib/python3*/site-packages/nvidia/*/lib')))
    r = run([f'{VO}/.venv/bin/python', '-W', 'ignore', f'{VO}/tools/splices.py'],
            env=dict(os.environ, CUDA_VISIBLE_DEVICES='1', LD_LIBRARY_PATH=libs))
    last = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith('splices:')]
    note(f'- {last[-1] if last else "splices.py failed: " + (r.stderr or r.stdout).strip()[-300:]}'); note()
    m = re.search(r'(\d+) clips prepared', last[-1]) if last else None
    return int(m.group(1)) if m else 0

def reencode():
    # a race/class clip ("<line>_s<i>_<word>") is NOT re-encoded here: splices.py writes its render64/ copy, trimmed and
    # padded to fit the take
    stale = [p for p in glob.glob('render/*.mp3') if '_' not in os.path.basename(p)
             if not os.path.exists('render64/' + os.path.basename(p)) or os.path.getmtime('render64/' + os.path.basename(p)) < os.path.getmtime(p)]
    for p in stale:
        if DRY: continue
        dst = 'render64/' + os.path.basename(p)
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', p, '-map_metadata', '-1', '-c:a', 'libmp3lame', '-b:a', '64k',
                        dst + '.tmp.mp3'], check=True)
        os.replace(dst + '.tmp.mp3', dst)
    return stale

def build_and_share():
    note('## Release'); note()
    if DRY: note('- (dry run: no build)'); return
    # --partial: a line that could not be directed or rendered stays silent rather than holding back every fix
    r = run(['python3', f'{CLIENT}/build_release.py', '--partial'])
    if r.returncode: note(f'**The build failed; nothing was shared or published:** {(r.stderr or r.stdout).strip()[-600:]}'); return
    for l in r.stdout.splitlines():
        if l.startswith(('patch:', 'update')) or ' GB)' in l or 'review page shipped' in l or l.startswith('  missing'): note(f'- {l.strip()}')
    share_zips()
    note()

def share_zips():
    """the release zips onto the share under their lasting names, each copied whole under a temporary name, checked
    byte for byte and renamed into place: a player downloading during the copy gets the old file, never half a new one"""
    if not SHARE: note('- no share_dir in config.local.json: the zips stay in client/release/'); return
    ver = re.search(r'ADDON_VERSION = "([^"]+)"', open(f'{CLIENT}/addon/LivingVoices/LivingVoices.lua').read()).group(1)
    # (2026-10-31) the portal serves the share's two zips to every player: an engine (LivingVoices.dll) the producer has
    # not run on Windows goes to the share as a TEST update only, until its version is in client/ENGINE_TESTED
    eng = re.search(r'lua_pushstring\(L, "([\d.]+)"\);\s+lua_setfield\(L, -2, "Version"\)', open(f'{CLIENT}/LivingVoices.cpp').read()).group(1)
    tested = open(f'{CLIENT}/ENGINE_TESTED').read().split() if os.path.exists(f'{CLIENT}/ENGINE_TESTED') else []
    if eng not in tested:
        src, name = f'{CLIENT}/release/LivingVoices-{ver}-update.zip', f'LivingVoices-{eng}-test.zip'
        part = f'{SHARE}/.{name}.part'; shutil.copyfile(src, part); os.chmod(part, 0o644); os.replace(part, f'{SHARE}/{name}')
        note(f'- **engine {eng} is not tested on Windows yet**: the update went to the share as {name} only (not public). '
             f'Once it plays in game, add "{eng}" to client/ENGINE_TESTED and the next run publishes.')
        return
    for src, name in ((f'{CLIENT}/release/LivingVoices-{ver}.zip', 'LivingVoices.zip'),
                      (f'{CLIENT}/release/LivingVoices-{ver}-update.zip', 'LivingVoices-update.zip')):
        part = f'{SHARE}/.{name}.part'
        shutil.copyfile(src, part)
        if run(['cmp', src, part]).returncode: note(f'**{name}: the copy to the share differs; the old one stays**'); os.remove(part); continue
        os.chmod(part, 0o644); os.replace(part, f'{SHARE}/{name}'); note(f'- on the share and the portal: {name} ({ver})')

if __name__ == '__main__':
    os.chdir(f'{VO}/data')
    day = dt.date.today().isoformat()
    note(f'# Living Voices nightly run, {day}' + (' (dry run)' if DRY else '')); note()
    c = sqlite3.connect('overnight.sqlite')
    if '--reports' in sys.argv or dt.date.today().weekday() == 6: reports()
    decisions(c)
    # race/class sentences of every directed line, queued (new ones only): the lines directed last night get theirs now
    if not DRY:
        r = run(['python3', f'{VO}/tools/variants.py', 'plan', '--enqueue'])
        note('## Race and class sentences planned'); note()
        for l in (r.stdout or r.stderr).strip().splitlines()[-2:]: note(f'- {l}')
        note()
    render_queue(c)
    clips = splices()
    stale = reencode()
    note('## Re-encoded'); note(); note(f'- {len(stale)} line(s) to 64 kbps' + (f': {", ".join(os.path.basename(p)[:-4] for p in stale[:20])}' if stale else '')); note()
    if stale or clips or not os.path.exists(f'{CLIENT}/release/.last_weekly_build'):
        build_and_share()
        if not DRY: open(f'{CLIENT}/release/.last_weekly_build', 'w').write(day)
    else:
        note('## Release'); note(); note('- no line changed this week: no new build'); note()
    if not DRY: open(f'overnight_reports/nightly-{day}.md', 'w').write('\n'.join(out) + '\n')
