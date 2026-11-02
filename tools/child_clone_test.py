"""Billy round 4: the voice reference is a boy's own storytelling (Plymouth children's speech, Zenodo 200495, CC BY
4.0), shifted DOWN a little -- older-sounding (the boys are ~5, Billy ~8-10) and not any real child's voice. Delivery
is the normal style direction. Card-1 ComfyUI."""
import csv, json, os, subprocess, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import render, child_voice
R = render.ROOT; OUT = f'{R}/voice_test/child/round4'; os.makedirs(OUT + '/parts', exist_ok=True)
SRC = f'{LV.CORPORA}/plymouth_children/english_children/english_free_speech/files_cut_by_sentences'
TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
def boy_ref(boy, dst, target=12.0):
    fs = sorted(glob.glob(f'{SRC}/{boy}/*.wav'), key=lambda f: -float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
               'format=duration', '-of', 'csv=p=0', f], capture_output=True, text=True).stdout or 0))
    pick, tot = [], 0.0
    for f in fs:
        d = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], capture_output=True, text=True).stdout)
        if tot >= target: break
        pick.append(f); tot += d
    n = len(pick)
    flt = ''.join(f'[{i}:a]{TRIM},aresample=24000,aformat=channel_layouts=mono[a{i}];' for i in range(n))
    flt += ''.join(f'anullsrc=r=24000:cl=mono,atrim=0:0.25[s{i}];' for i in range(n - 1))
    flt += ''.join(f'[a{i}]' + (f'[s{i}]' if i < n - 1 else '') for i in range(n)) + f'concat=n={2 * n - 1}:v=0:a=1,loudnorm=I=-20:TP=-2[o]'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *sum((['-i', f] for f in pick), []), '-filter_complex', flt, '-map', '[o]', dst], check=True)
    return dst
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
d = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}[row['questId']]['accept']
texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
for boy in ('06_M_native', '11_M_native'):
    raw = boy_ref(boy, f'{OUT}/parts/{boy}_raw.wav')
    for p, f in ((-1, -0.5), (-2, -1)):
        ref = child_voice.childify(raw, f'{OUT}/parts/{boy}_p{p}_f{f}.wav', p, f)
        name = f"{('1','2') if boy.startswith('06') else ('3','4')}"[0 if p == -1 else 1] if False else None
        i = (1 if boy.startswith('06') else 3) + (0 if p == -1 else 1)
        parts = [render.render_beat(render.speakable(render.scripted(t)), ref, render.style_clip(b['style'], 'male', 'human'), f'r4_{i}_{k}')
                 for k, (t, b) in enumerate(zip(texts, d['beats']))]
        render.join(render.even_pace(parts, texts), f'{OUT}/{i}_boy{boy[:2]}_pitch{p}_formant{f}.mp3')
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', ref, '-b:a', '128k', f'{OUT}/{i}_reference.mp3'], check=True)
        print(i, 'done', flush=True)
open(f'{OUT}/CREDITS.txt', 'w').write('Voice references derived from: children speech recording, Kennedy, Lemaignan, Montassier, Lavalade, '
    'Irfan, Papadopoulos, Senft, Belpaeme (Plymouth University), Zenodo record 200495, CC BY 4.0.\n')
