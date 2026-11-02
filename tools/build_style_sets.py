"""Assemble the reviewed race/sex style clips (data/style_sets/selection_<group>.json) into
data/style_sets/<group>/<style>.wav: several short clips are joined with a 0.3 s pause; each result is silence-trimmed
and loudness-matched. Run from data/:  python3 ../tools/build_style_sets.py [listen_dir]
With listen_dir: a listening sample per group (steady_explaining, exasperated, rallying_cry) + INDEX.txt."""
import glob, json, os, subprocess, sys
TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
summary, listen = [], (sys.argv[1] if len(sys.argv) > 1 else None)
for sel in sorted(glob.glob('style_sets/selection_*.json')):
    s = json.load(open(sel)); g = s['group']; os.makedirs(f'style_sets/{g}', exist_ok=True)
    for style, p in s['picks'].items():
        files = [f for f in p.get('files') or [] if os.path.exists(f)]
        if not files: continue
        n = len(files); dst = f'style_sets/{g}/{style}.wav'
        flt = ''.join(f'[{i}:a]{TRIM},aresample=24000,aformat=channel_layouts=mono[a{i}];' for i in range(n))
        flt += ''.join(f'anullsrc=r=24000:cl=mono,atrim=0:0.3[s{i}];' for i in range(n - 1))
        flt += ''.join(f'[a{i}]' + (f'[s{i}]' if i < n - 1 else '') for i in range(n)) + f'concat=n={2 * n - 1}:v=0:a=1,loudnorm=I=-20:TP=-2[o]'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', *sum((['-i', f] for f in files), []), '-filter_complex', flt,
                        '-map', '[o]', '-ar', '24000', dst], check=True)
    q = [p.get('quality') for p in s['picks'].values()]
    fb = {k: p['fallback'] for k, p in s['picks'].items() if not p.get('files') and p.get('fallback')}
    summary.append(f"{g:18} good {q.count('good'):2}  weak {q.count('weak'):2}  fallback {len(fb)} {fb if fb else ''}")
print('\n'.join(summary))
if listen:
    os.makedirs(listen, exist_ok=True); idx = []
    for sel in sorted(glob.glob('style_sets/selection_*.json')):
        s = json.load(open(sel)); g = s['group']
        for style in ('steady_explaining', 'exasperated', 'rallying_cry'):
            src = f'style_sets/{g}/{style}.wav'
            if os.path.exists(src):
                subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-b:a', '128k', f'{listen}/{g}__{style}.mp3'], check=True)
                p = s['picks'][style]; idx.append(f"{g}__{style}.mp3  [{p.get('quality')}] {p.get('why', '')}")
    open(f'{listen}/INDEX.txt', 'w').write('\n'.join(idx) + '\n')
