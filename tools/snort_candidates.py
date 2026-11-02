"""Mangletooth's snort, again (2026-10-26, the producer): the 0.97 s QuillBoarPreAggro reads as a piggish grumble, and
his voice filter (beast_growl) pitches it down and lays an octave under it. "A half to a quarter the length, and more
like a snort." This cuts one short burst (0.12-0.45 s) from every boar, quilboar, pig, horse and kodo sound in the 3.3.5
client and Warcraft III, and for each builds his 878-progress line with it spliced in (the speech morphed, the snort
not), plus the line at three depths of his voice. The review page's Snort tab plays them and records the pick in
data/sfx/snort_pick.json.

Run from data/:  ~/ComfyUI/venv/bin/python ../tools/snort_candidates.py"""
import glob, json, os, re, shutil, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
from mpqget import MPQ
import morph_presets

CLIENT = f'{LV.WOW_DATA}'
WC3 = f'{LV.WAR3_ARCHIVE}'
WC3_PIGS = (r'Units\Critters\Pig\PigWhat1.wav', r'Units\Critters\Pig\PigWhat2.wav', r'Units\Critters\Pig\PigDeath.wav',
            r'buildings\Other\PigFarm\PigFarmWhat1.wav')
WANT = re.compile(r'(?i)\\(QuillBoar|Boar|FelBoar)\\(?!.*(Death|Attack))|Petstore_Pig|PolyMorphPig|mHorseStand|'
                  r'HorseUndeadStand|KodoBeastStand|Elekk_Pre_Aggro')
OUT = 'sfx/snort_cands'
SR = 24000
# the context line: 878-progress, seed 10's three spoken parts (render_parts), "<snort>" between each
PARTS = f'{LV.COMFY_OUT}/render_parts/878-progress_0_{{}}_00010_paced.flac'
DEPTHS = {'current': (-3.0, -1.5), 'deeper': (-4.0, -2.0), 'deepest': (-5.0, -2.5)}   # beast_growl pitch, formant

def pcm(f):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', f, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                       capture_output=True, check=True).stdout
    return np.frombuffer(r, np.float32)

def flatness(seg):
    """spectral flatness, 0 tonal .. 1 noise: a snort is breath through the nose, noisy; a grunt or squeal is tonal"""
    w = np.hanning(512); fr = [seg[i:i + 512] * w for i in range(0, len(seg) - 512, 256)]
    if not fr: return 0.0
    S = np.abs(np.fft.rfft(fr, axis=1)) + 1e-9
    return float(np.mean(np.exp(np.mean(np.log(S), 1)) / np.mean(S, 1)))

def burst(x):
    """(start, end) s of the noisiest sound event (10 ms frames above peak - 24 dB, gaps under 40 ms bridged), cut to
    0.45 s; None if every event is under 0.12 s"""
    h = 240; n = len(x) // h
    db = 20 * np.log10(np.array([np.sqrt(np.mean(x[i * h:(i + 1) * h] ** 2)) for i in range(n)]) + 1e-9)
    on = db > db.max() - 24; ev, i = [], 0
    while i < n:
        if not on[i]: i += 1; continue
        j = i
        while j < n and (on[j] or on[j:j + 4].any()): j += 1
        ev.append((i * h / SR, j * h / SR)); i = j
    ev = [(a, min(b, a + 0.45)) for a, b in ev if b - a >= 0.12]
    if not ev: return None
    return max(ev, key=lambda e: flatness(x[int(e[0] * SR):int(e[1] * SR)]))

def sources():
    got = {}
    for p in sorted(glob.glob(CLIENT + '/*.MPQ') + glob.glob(CLIENT + '/*/*.MPQ')):
        try: m = MPQ(p); L = m.read('(listfile)').decode('latin1').split('\r\n')
        except Exception: continue
        for f in L:
            if f.lower().endswith('.wav') and WANT.search(f) and f.lower() not in got:
                try: got[f.lower()] = ('WoW ' + f.split('\\', 2)[-1], m.read(f))
                except Exception: pass
        m.close()
    m = MPQ(WC3)
    for f in WC3_PIGS: got[f.lower()] = ('WC3 ' + f, m.read(f))
    m.close()
    return got.values()

def deep_morph(src, dst, pitch, formant):
    keep = morph_presets.PRESETS['beast_growl']
    morph_presets.PRESETS['_d'] = (pitch, formant, keep[2], keep[3])
    morph_presets.morph(src, dst, '_d')

def join(parts, dst):
    import render
    render.join(parts, dst)

if __name__ == '__main__':
    if os.path.isdir(OUT): shutil.rmtree(OUT)
    os.makedirs(OUT + '/ctx'); t = tempfile.mkdtemp()
    cands = []
    for label, raw in sources():
        cid = re.sub(r'[^A-Za-z0-9]+', '_', label.split('\\')[-1].rsplit('.', 1)[0]).strip('_')
        if label.startswith('WC3'): cid = 'WC3_' + cid
        src = f'{t}/{cid}.raw'; open(src, 'wb').write(raw)
        # loudness over the whole sound first, then the cut (a 0.2 s burst is too short to measure; build_sfx.py's clucks)
        norm = f'{t}/{cid}.wav'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-af', 'loudnorm=I=-22:TP=-3', '-ac', '1', '-ar', str(SR), norm], check=True)
        b = burst(pcm(norm))
        if not b: continue
        a, e = max(0.0, b[0] - 0.01), b[1]
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', norm, '-af', f'atrim={a}:{e},asetpts=N/SR/TB,afade=t=in:d=0.01,'
                        'areverse,afade=t=in:d=0.05,areverse', f'{OUT}/{cid}.wav'], check=True)
        cands.append(dict(id=cid, source=label, secs=round(e - a, 2), noise=round(flatness(pcm(f'{OUT}/{cid}.wav')), 3)))
    # the snort in use now, for comparison (whole, and its first 0.45 s)
    shutil.copy('sfx/snort.wav', f'{OUT}/current.wav')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', 'sfx/snort.wav', '-af', 'atrim=0.08:0.53,asetpts=N/SR/TB,'
                    'areverse,afade=t=in:d=0.05,areverse', f'{OUT}/current_short.wav'], check=True)
    cands += [dict(id='current', source='in use now: WoW QuillBoar\\QuillBoarPreAggro.wav (whole)', secs=0.97, noise=round(flatness(pcm(f'{OUT}/current.wav')), 3)),
              dict(id='current_short', source='in use now, its first 0.45 s', secs=0.45, noise=round(flatness(pcm(f'{OUT}/current_short.wav')), 3))]
    # his speech, morphed at each depth (the snort spliced in afterwards, unmorphed)
    speech = {}
    for dn, (p, f) in DEPTHS.items():
        speech[dn] = []
        for k in ('00', '02', '04'):
            dst = f'{t}/say_{k}_{dn}.wav'; deep_morph(PARTS.format(k), dst, p, f); speech[dn].append(dst)
    for c in cands:
        s = f'{OUT}/{c["id"]}.wav'; a, b, d = speech['current']
        join([a, s, b, s, d], f'{OUT}/ctx/{c["id"]}.mp3')
    ref = f'{OUT}/current_short.wav'
    for dn in DEPTHS:
        a, b, d = speech[dn]; join([a, ref, b, ref, d], f'{OUT}/ctx/depth_{dn}.mp3')
    cands.sort(key=lambda c: (c['id'] not in ('current', 'current_short'), -c['noise']))
    json.dump(dict(line='878-progress', text="More information *snort* for the Horde when you've killed the Bristleback's wise ones, traveler. *snort* Not a moment earlier! Mangletooth is no fool.",
                   depths={k: dict(pitch=p, formant=f) for k, (p, f) in DEPTHS.items()}, cands=cands),
              open(f'{OUT}/index.json', 'w'), indent=1)
    shutil.rmtree(t)
    print(len(cands), 'snorts in', OUT)
