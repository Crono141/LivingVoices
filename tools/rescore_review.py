"""Score the review page's takes again after the speech check changed (2026-11-02: a race/class clip judged slow against
its own take's pace, "Torrin" heard as tauren). No rendering: every take of the latest night still on file
(render/takes/<line>.s<seed>.mp3) is checked again, a race/class clip's first sped up to its take's pace as tonight's
renders will be (render.take_rate, pace_up). A take that now passes becomes the line's file and the line is done; a line
none of whose takes pass goes back on the review page with its best.

    ~/ComfyUI/venv/bin/python ../tools/rescore_review.py [names...]      (from data/; card 1, Gemma by day: 6 slots)

A morphed clip's check listens to the pre-morph copy (render/<line>.check.mp3), which is only kept for its last seed:
only that seed is scored again. The takes as they were go to render/takes/.before_rescore/.
"""
import os, shutil, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overnight as o, render

def main(names):
    c = o.db()
    names = names or [r[0] for r in c.execute("SELECT name FROM lines WHERE status='review'")]
    V = json.load(open('variants.json')) if os.path.exists('variants.json') else {}
    os.makedirs('render/takes/.before_rescore', exist_ok=True)
    plan, rate = {}, {}                                   # name -> [(seed, path)]
    for nm in names:
        last = c.execute("SELECT seed FROM lines WHERE name=?", (nm,)).fetchone()[0]
        takes = c.execute("SELECT seed, path FROM takes WHERE name=?1 AND night=(SELECT MAX(night) FROM takes WHERE name=?1) "
                          "AND path IS NOT NULL ORDER BY seed", (nm,)).fetchall()
        morphed = os.path.exists(f'render/{nm}.check.mp3')
        plan[nm] = [(s, p) for s, p in takes if os.path.exists(p) and (not morphed or s == last)]
        if nm in V: rate[nm] = render.take_rate(V[nm]['base'])
    for nm in names:                                      # the takes as they were, and the clips sped up to their take
        for s, p in plan[nm]:
            bak = f'render/takes/.before_rescore/{os.path.basename(p)}'
            if not os.path.exists(bak): shutil.copy2(p, bak)
            if rate.get(nm):
                f = render.pace_up(p, V[nm]['text'], rate[nm])
                chk = f'render/{nm}.check.mp3'
                if f != 1.0 and os.path.exists(chk):
                    if not os.path.exists(f'render/takes/.before_rescore/{nm}.check.mp3'): shutil.copy2(chk, f'render/takes/.before_rescore/{nm}.check.mp3')
                    render.pace_up(chk, V[nm]['text'], rate[nm])
    passed = {}
    for k in range(max((len(v) for v in plan.values()), default=0)):
        batch = {nm: v[k] for nm, v in plan.items() if len(v) > k}
        if not batch: continue
        for nm, (s, p) in batch.items(): shutil.copy2(p, f'render/{nm}.mp3')
        res, odd = o.score(list(batch))
        for nm, r in res.items():
            s, p = batch[nm]
            score, heard, raw, fault, faults = o.verdict(r, odd.get(nm))
            c.execute("UPDATE takes SET raw=?, fault=?, faults=?, heard=?, created=? WHERE name=? AND seed=?",
                      (round(raw, 3), fault, faults, heard, o.now(), nm, s))
            # every take is heard; the line keeps its best passing one (the first to pass was a 0.86 with words repeated
            # where a 1.0 was on file, g1569 2026-11-02)
            if score >= o.GOOD and score > passed.get(nm, (0, 0, 0))[2]: passed[nm] = (s, p, score, heard)
        c.commit()
    for nm in names:
        if nm in passed:
            s, p, score, heard = passed[nm]
            shutil.copy2(p, f'render/{nm}.mp3')
            c.execute("UPDATE lines SET status='done', seed=?, score=?, heard=?, updated=? WHERE name=?", (s, score, heard, o.now(), nm))
        else:
            o.to_review(c, nm)
    c.commit()
    left = [r for r in c.execute("SELECT name, heard FROM lines WHERE status='review' AND name IN (%s) ORDER BY name"
                                 % ','.join('?' * len(names)), names)]
    print(f'{len(passed)} of {len(names)} passed; {len(left)} still on the review page:')
    for nm, h in left: print(f'  {nm} | {(h or "")[:170]}')

if __name__ == '__main__':
    os.chdir(os.path.join(o.VO, 'data'))
    main(sys.argv[1:])
