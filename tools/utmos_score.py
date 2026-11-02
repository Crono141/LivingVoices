"""Delivery score (2026-10-15, the producer): UTMOS (SpeechMOS utmos22_strong), the 1-5 rating a listening panel would
give, for the whole take and for each sentence. A stilted take usually goes wrong a sentence at a time (Maybell's
seed 4 was fine until she started yelling directions in its last four seconds), so the worst sentence counts.
Sentences come from the take's own pauses: silent runs >= 0.3 s under -35 dB; a piece under 2 s joins the next, one
over 8 s is halved. Voices differ by nature (a goblin's nasal tone scores ~1.5, a clean human ~3.5+), so a take is
judged against its own voice's range, never one cutoff for all.

  ../.venv/bin/python ../tools/utmos_score.py baseline     -> utmos_baseline.csv + per-voice summary
"""
import concurrent.futures as cf, csv, json, os, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SR = 16000
_model = None
def model():
    global _model
    if _model is None:
        import torch
        _model = torch.hub.load('tarepan/SpeechMOS:v1.2.0', 'utmos22_strong', trust_repo=True, verbose=False).cuda().eval()
    return _model

def decode(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)

def sentences(x, gap=0.3, thresh=-35, lo=2.0, hi=8.0):
    """[(start, end)] in samples: speech between pauses, short pieces merged forward, long ones halved"""
    f = SR // 100
    db = 20 * np.log10(np.sqrt(np.mean(x[:len(x) // f * f].reshape(-1, f) ** 2, axis=1)) + 1e-9)
    loud = db > thresh
    if not loud.any(): return []
    first, last = np.argmax(loud), len(loud) - np.argmax(loud[::-1])
    cuts, run = [], 0
    for i in range(first, last):
        run = run + 1 if not loud[i] else 0
        if run == int(gap * 100): cuts.append(i - run // 2)
    edges = [first] + cuts + [last]
    segs = [[a * f, b * f] for a, b in zip(edges, edges[1:])]
    out = []
    for s in segs:                                           # merge pieces under lo seconds into the next
        if out and (out[-1][1] - out[-1][0]) < lo * SR: out[-1][1] = s[1]
        else: out.append(s)
    if len(out) > 1 and (out[-1][1] - out[-1][0]) < lo * SR:
        tail = out.pop(); out[-1][1] = tail[1]
    res = []
    for a, b in out:
        n = int(np.ceil((b - a) / (hi * SR)))
        step = (b - a) / n
        res += [(int(a + k * step), int(a + (k + 1) * step)) for k in range(n)]
    return res

def score(x):
    import torch
    with torch.no_grad():
        return float(model()(torch.from_numpy(np.ascontiguousarray(x)).unsqueeze(0).cuda(), SR))

def take(path):
    """(whole-take score, [sentence scores])"""
    x = decode(path)
    segs = sentences(x)
    return score(x), [score(x[a:b]) for a, b in segs] if len(segs) > 1 else []

def voice_of(r, rc, D):
    """which voice a line is read in, for per-voice ranges"""
    d = D.get(r['questId'], {}).get(r['kind'], {})
    if isinstance(d, dict) and d.get('voice') == 'narrator': return 'narrator'
    e = rc.get(r['npc_id'])
    if e: return e['src']
    # a 'generate' line can still clone from a pack recording (as_generated: the speaker's pack voice), so the
    # reference decides, not the plan's action (the gnome women were labelled designed, 2026-10-16)
    import overnight as ov
    g = ov.as_generated(r) if r['action'] != 'generate' else r
    if (g or r).get('clone_ref', '').startswith('design:'): return f"designed {r['race']} {r['sex']}".replace('unknown unknown', 'unknown')
    return f"pack clone {r['race']} {r['sex']}".replace('unknown unknown', 'unknown')

def baseline():
    import overnight as ov
    rc = json.load(open('race_cast.json')); D = ov.load_directions([ov.DIRECTIONS])
    plan = {ov.name_of(r): r for r in csv.DictReader(open('plan_v3.csv'))}
    files = sorted(f for f in os.listdir('render') if f.endswith('.mp3') and not f.endswith('.check.mp3'))
    rows = []
    with cf.ThreadPoolExecutor(6) as ex:                     # ffmpeg decodes in parallel; the GPU scores in turn
        futs = {ex.submit(decode, f'render/{f}'): f for f in files}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            f = futs[fu]; nm = f[:-4]; r = plan.get(nm)
            if not r: continue
            try:
                x = fu.result(); segs = sentences(x)
                whole = score(x); sent = [score(x[a:b]) for a, b in segs] if len(segs) > 1 else []
            except Exception as e:
                print('!!', nm, str(e)[:80], flush=True); continue
            rows.append(dict(name=nm, voice=voice_of(r, rc, D), npc=r['npc_name'], secs=round(len(x) / SR, 1),
                             whole=round(whole, 2), worst=round(min(sent), 2) if sent else round(whole, 2), n=len(sent) or 1))
            if i % 500 == 0: print(i, 'scored', flush=True)
    with open('utmos_baseline.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(sorted(rows, key=lambda r: r['name']))
    by = {}
    for r in rows: by.setdefault(r['voice'], []).append(r)
    print(f"\n{'voice':34} {'takes':>5}  whole: p20  median  p80   worst sentence: p20  median")
    for v, rs in sorted(by.items(), key=lambda kv: -np.median([r['whole'] for r in kv[1]])):
        a = np.array([r['whole'] for r in rs]); b = np.array([r['worst'] for r in rs])
        print(f'{v:34} {len(rs):5}        {np.percentile(a, 20):.2f}  {np.median(a):.2f}   {np.percentile(a, 80):.2f}'
              f'                {np.percentile(b, 20):.2f}  {np.median(b):.2f}')

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    {'baseline': baseline}[sys.argv[1]]()
