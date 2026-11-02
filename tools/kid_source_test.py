"""Billy from game child voices (2026-10-12): Warcraft III's Timmy (H01VillagerC23/35/36, 44.1 kHz) and WoW's young
Anduin (3 greetings, 22 kHz). Same direction and output de-ess as the chosen Billy take. Card-1 ComfyUI."""
import csv, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, child_voice, requests
K = f'{render.ROOT}/voice_test/kid_sources'; OUT = f'{K}/billy'; os.makedirs(OUT + '/parts', exist_ok=True)
def cat(files, dst):
    ins = sum([['-i', f] for f in files], [])
    n = len(files); flt = ''.join(f'[{i}:a]aresample=24000,aformat=channel_layouts=mono,apad=pad_dur=0.35[a{i}];' for i in range(n))
    flt += ''.join(f'[a{i}]' for i in range(n)) + f'concat=n={n}:v=0:a=1,loudnorm=I=-20:TP=-2'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *ins, '-filter_complex', flt, '-ar', '24000', dst], check=True); return dst
timmy = cat([f'{K}/wc3/H01VillagerC{n}.mp3' for n in (23, 36, 35)], f'{OUT}/parts/timmy_ref.wav')
anduin = cat([f'{K}/KingAnduinWrynnGreeting0{n}.wav' for n in (1, 2, 3)], f'{OUT}/parts/anduin_ref.wav')
refs = {'timmy': timmy, 'timmy_older': child_voice.childify(timmy, f'{OUT}/parts/timmy_older.wav', -1, -0.5),
        'anduin': anduin}
requests.post(render.URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)
D = json.load(open('newstyle_test_directions.json'))['86']['accept']
r = [r for r in csv.DictReader(open('plan_v3.csv')) if (r['questId'], r['kind']) == ('86', 'accept') and r['variant'] != 'f'][0]
texts = [render.scripted(t) for t in render.beat_texts('86', 'accept', r['variant'], D['beats'])]
for k, spk in refs.items():
    parts = [render.render_beat(render.calm(render.speakable(t), b['intensity']), spk, render.style_clip(b['style'], 'male', 'human'),
                                f'ks_{k}_{i}', alpha=render.alpha_for(b['intensity'])) for i, (t, b) in enumerate(zip(texts, D['beats']))]
    raw = f'{OUT}/parts/Billy_{k}_raw.mp3'; render.join(render.even_pace(parts, texts), raw)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', raw, '-af', 'deesser=i=0.5:m=0.5:f=0.5:s=o', '-b:a', '128k', f'{OUT}/Billy_{k}.mp3'], check=True)
    print(k, flush=True)
for k in ('timmy', 'anduin'):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', refs[k], '-b:a', '128k', f'{OUT}/source_{k}.mp3'], check=True)
