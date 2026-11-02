"""The producer's sample (2026-10-16): five lines of every race and sex from the queue, rendered and checked exactly as a
night renders them (director's notes, speech check, re-takes on the next seed), then scored by UTMOS -- whole take and
worst sentence -- against the voice's own source recording (the game clip it was cloned from: 'Blizzard quality').
The producer rates by ear first (LISTEN.csv), then opens SCORES_dont_peek.csv; where the ear and UTMOS agree sets
the per-voice floors and the take limit.
  ../.venv/bin/python ../tools/sample_voices.py        (from data/; card 0 renders, card 1 checks)
Lines that pass are done lines like any night's; the sample is not rendered twice.
  ../.venv/bin/python ../tools/sample_voices.py again <earlier sample folder> <new folder>
      the same lines again, as they render now (2026-10-17: after the lever tests' fixes); a line now played from its
      pack recording (KEEP_PACK) is that recording"""
import csv, json, os, random, shutil, sqlite3, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import overnight as ov, render, utmos_score as u, race_cast as rc

O = f'{LV.COMFY_OUT}/voice_test/sample_2026-10-16'
PER, SEED = 5, 20261016
PLAYABLE = {'Human', 'Dwarf', 'Gnome', 'Night Elf', 'Draenei', 'Orc', 'Undead', 'Tauren', 'Troll', 'Blood Elf', 'Goblin'}

def group(r, d):
    if d.get('voice') == 'narrator': return 'narrator'
    return f"{r['race']} {r['sex']}" if r['race'] in PLAYABLE and r['sex'] in ('male', 'female') else 'other (no playable race)'

def main(again=None):
    global O
    if again: O = again[1]
    os.makedirs(O, exist_ok=True); render.use_server(ov.CARDS['0']); c = ov.db()
    rows = {ov.name_of(r): g for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] != 'none' and (g := ov.as_generated(r))}
    D = ov.load_directions([ov.DIRECTIONS])
    # (the producer) five of every race and sex, not forty at random: a plain draw left out gnomes and nearly every
    # woman. The narrator is a group of its own; speakers of no playable race one more. Lines of the first draw that
    # fit a group are kept (already rendered and checked).
    plan = {ov.name_of(r): r for r in csv.DictReader(open('plan_v3.csv'))}
    if again:
        pick = json.load(open(f'{again[0]}/.pick_races.json')); json.dump(pick, open(f'{O}/.pick_races.json', 'w'))
        packed = [n for n in pick if n not in rows]; pick = [n for n in pick if n in rows]
        print(len(pick), 'lines again;', len(packed), 'now the pack recording', flush=True)
        return render_and_score(c, rows, D, pick, packed, plan)
    first = json.load(open(f'{O}/.pick.json')) if os.path.exists(f'{O}/.pick.json') else []
    ok = lambda n: n in rows and isinstance(D.get(rows[n]['questId'], {}).get(rows[n]['kind']), dict)
    todo = [n for n, in c.execute("SELECT name FROM lines WHERE status='todo' ORDER BY name") if ok(n) and ov.voice_ready(ov.voice_key(rows[n]))]
    groups = {}
    for n in sorted(set(todo) | {n for n in first if ok(n)}):
        groups.setdefault(group(rows[n], D[rows[n]['questId']][rows[n]['kind']]), []).append(n)
    rng = random.Random(SEED); pick = []
    for g in sorted(groups):
        mine = [n for n in first if n in groups[g]][:PER]
        rest = [n for n in groups[g] if n not in mine]
        pick += mine + rng.sample(rest, min(PER - len(mine), len(rest)))
    pick = sorted(pick, key=lambda n: (group(rows[n], D[rows[n]['questId']][rows[n]['kind']]), n))
    json.dump(pick, open(f'{O}/.pick_races.json', 'w'))
    print(len(pick), 'picked in', len(groups), 'groups:', {g: len(v) for g, v in sorted(groups.items())}, flush=True)
    render_and_score(c, rows, D, pick, [], plan)

def render_and_score(c, rows, D, pick, packed, plan):
    for rnd in range(ov.SEEDS + 1):
        left = [n for n in pick if c.execute("SELECT status FROM lines WHERE name=?", (n,)).fetchone()[0] == 'todo']
        if not left: break
        for nm in left:
            seed = c.execute("SELECT seed FROM lines WHERE name=?", (nm,)).fetchone()[0]
            r = rows[nm]; d = D[r['questId']][r['kind']]; dst = f'render/{nm}.mp3'
            if os.path.exists(dst): os.remove(dst)
            s0 = time.time()
            try: render.render_line(r, d, dst, seed=ov.take_seed(nm, seed))
            except Exception as e:
                c.execute("UPDATE lines SET status='failed', err=?, updated=? WHERE name=?", (str(e)[:500], ov.now(), nm))
                print('!!', nm, str(e)[:150], flush=True); continue
            dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', dst],
                                       capture_output=True, text=True).stdout or 0)
            c.execute("UPDATE lines SET status='rendered', secs=?, audio_s=?, err=NULL, updated=? WHERE name=?",
                      (round(time.time() - s0, 1), round(dur, 1), ov.now(), nm))
            print(f'round {rnd + 1}: {nm} take {seed} {time.time() - s0:.0f}s', flush=True)
        ov.check()
    # score: the take, its worst sentence, and the voice's source recording (the yardstick)
    rcast = json.load(open('race_cast.json')); src_score = {}
    listen, scores = [], []
    order = sorted(pick + packed, key=lambda n: (group(rows.get(n) or plan[n], D[plan[n]['questId']][plan[n]['kind']]), n))
    for i, nm in enumerate(order, 1):
        if nm in packed:                      # what ships for this line: the pack's own recording
            r = plan[nm]; tag = f'{i:02d}_{nm}'
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', render.pack_clip(f"{r['source_pack']}:{r['file_in_pack']}", f'refs_cache/packline_{nm}.ogg'),
                            f'{O}/{tag}.mp3'], check=True)
            listen.append(dict(n=i, file=f'{tag}.mp3', group=group(r, D[r['questId']][r['kind']]), speaker=r['npc_name'], your_rating_1to5='', notes=''))
            scores.append(dict(n=i, line=nm, group=group(r, D[r['questId']][r['kind']]), speaker=r['npc_name'], voice='pack recording', status='pack'))
            continue
        st, seed, sc = c.execute("SELECT status, seed, score FROM lines WHERE name=?", (nm,)).fetchone()
        f = f'render/{nm}.mp3'
        if not os.path.exists(f): scores.append(dict(n=i, line=nm, status=st)); continue
        r = rows[nm]; dv = D[r['questId']][r['kind']]; voice = u.voice_of(r, rcast, D)
        whole, sent = u.take(f)
        if voice in rc.SOURCES and voice not in src_score:
            src_score[voice] = round(u.take(rc.SOURCES[voice][0])[0], 2)
        tag = f'{i:02d}_{nm}'
        shutil.copy(f, f'{O}/{tag}.mp3')
        listen.append(dict(n=i, file=f'{tag}.mp3', group=group(r, dv), speaker=r['npc_name'], your_rating_1to5='', notes=''))
        scores.append(dict(n=i, line=nm, group=group(r, dv), speaker=r['npc_name'], voice=voice, status=st, takes=seed,
                           speech_check=sc, utmos=round(whole, 2), worst_sentence=round(min(sent), 2) if sent else round(whole, 2),
                           source_utmos=src_score.get(voice, ''), narrator=dv.get('voice') == 'narrator'))
    for name, rows_ in (('LISTEN.csv', listen), ('SCORES_dont_peek.csv', scores)):
        keys = list(dict.fromkeys(k for x in rows_ for k in x))
        with open(f'{O}/{name}', 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows_)
    print('SAMPLE DONE', {s: sum(1 for x in scores if x.get('status') == s) for s in ('done', 'review', 'failed', 'todo')}, flush=True)

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    main(sys.argv[2:4] if sys.argv[1:2] == ['again'] else None)
