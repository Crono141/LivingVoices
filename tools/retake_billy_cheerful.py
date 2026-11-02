"""Billy 86 accept again: plain voice-B reference, sly beat as before, cheerful beat on the DESIGNED cheerful clip;
the output de-essed (the take the producer chose 2026-10-12)."""
import csv, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
OUT = f'{render.ROOT}/voice_test/newstyles/retake'
spk = f'{OUT}/parts/billy_plain.wav'
D = json.load(open('newstyle_test_directions.json'))['86']['accept']
r = [r for r in csv.DictReader(open('plan_v3.csv')) if (r['questId'], r['kind']) == ('86', 'accept') and r['variant'] != 'f'][0]
texts = [render.scripted(t) for t in render.beat_texts('86', 'accept', r['variant'], D['beats'])]
clips = ['style_sets/designed/sly_male.wav', 'style_sets/designed/cheerful_male.wav']
parts = [render.render_beat(render.calm(render.speakable(t), b['intensity']), spk, c, f'rt_billy_dc_{i}', alpha=render.alpha_for(b['intensity']))
         for i, (t, b, c) in enumerate(zip(texts, D['beats'], clips))]
raw = f'{OUT}/parts/Billy_designed_cheerful_raw.mp3'; render.join(render.even_pace(parts, texts), raw)
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', raw, '-af', 'deesser=i=0.5:m=0.5:f=0.5:s=o', '-b:a', '128k',
                f'{OUT}/Billy_designed_cheerful.mp3'], check=True)
print('done')
