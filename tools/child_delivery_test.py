"""Billy: our shifted designed timbre + a real boy's storytelling as the DELIVERY (emotion) reference -- the delivery,
not the voice, made the earlier tries sound girlish. Children's speech: Kennedy et al., Plymouth University (Zenodo
200495, CC BY 4.0). No child is cloned: the speaker reference stays our own designed voice. Card-1 ComfyUI."""
import csv, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import render
R = render.ROOT; OUT = f'{R}/voice_test/child/round3'; os.makedirs(OUT + '/parts', exist_ok=True)
SRC = f'{LV.CORPORA}/plymouth_children/english_children/english_free_speech/files_cut_by_sentences'
def delivery(boy, names, dst):
    files = [f'{SRC}/{boy}/{n}.wav' for n in names]; n = len(files)
    trim = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
    flt = ''.join(f'[{i}:a]{trim},aresample=24000,aformat=channel_layouts=mono[a{i}];' for i in range(n))
    flt += ''.join(f'anullsrc=r=24000:cl=mono,atrim=0:0.3[s{i}];' for i in range(n - 1))
    flt += ''.join(f'[a{i}]' + (f'[s{i}]' if i < n - 1 else '') for i in range(n)) + f'concat=n={2 * n - 1}:v=0:a=1,loudnorm=I=-20:TP=-2[o]'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *sum((['-i', f] for f in files), []), '-filter_complex', flt, '-map', '[o]', dst], check=True)
    return dst
D06 = delivery('06_M_native', ["then he's hanging from the tree and he's got stuck ", "then the bees are buzzing out going backway "], f'{OUT}/parts/delivery_boy06.wav')
D11 = delivery('11_M_native', ["the boy was walking and the owl was following him ", "when they get dressed they look for the frog "], f'{OUT}/parts/delivery_boy11.wav')
T1 = f'{R}/voice_test/child/4_reference_pitch+6_formant+3.wav'
T2 = f'{R}/voice_test/child/round2/parts/girl_p6_f2.wav'
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
d = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}[row['questId']]['accept']
texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
for i, (T, tn, Dl, dn, alpha) in enumerate([(T1, 'r1no4', D06, 'boy06', .55), (T1, 'r1no4', D11, 'boy11', .55),
                                             (T2, 'r2no1', D06, 'boy06', .55), (T2, 'r2no1', D11, 'boy11', .55),
                                             (T2, 'r2no1', D11, 'boy11', .8)], 1):
    render.ALPHA = alpha
    parts = [render.render_beat(render.speakable(render.scripted(t)), T, Dl, f'r3_{i}_{k}') for k, t in enumerate(texts)]
    render.join(render.even_pace(parts, texts), f'{OUT}/{i}_voice-{tn}_delivery-{dn}_strength-{alpha}.mp3')
    print(i, 'done', flush=True)
for f in (D06, D11): subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', f, '-b:a', '128k', f"{OUT}/0_{os.path.basename(f)[:-4]}.mp3"], check=True)
open(f'{OUT}/CREDITS.txt', 'w').write('Delivery references: children speech recording, Kennedy, Lemaignan, Montassier, Lavalade, Irfan, '
    'Papadopoulos, Senft, Belpaeme (Plymouth University), Zenodo record 200495, CC BY 4.0.\n')
