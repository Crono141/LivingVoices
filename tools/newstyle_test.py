"""New-style test (2026-10-12): intensity-driven strength, the five new styles, subtext in the direction.
Billy on voice B (boy 10, MossFormer2 + VoiceFixer) de-essed; everyone else on their plan voice. Card-1 ComfyUI."""
import csv, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, child_voice
R = render.ROOT; OUT = f'{R}/voice_test/newstyles'; os.makedirs(OUT + '/parts', exist_ok=True)
B = f'{R}/voice_test/child/round9/parts/boy10_25s_mossformer_voicefixer.wav'
deessed = f'{OUT}/parts/boy10_B_deessed.wav'
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', B, '-af', 'deesser=i=0.6:m=0.5:f=0.5:s=o', deessed], check=True)
billy_ref = child_voice.childify(deessed, f'{OUT}/parts/billy_ref.wav', -1, -0.5)
import requests, glob
requests.post(render.URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)
D = json.load(open('newstyle_test_directions.json'))
want = {('86', 'accept'), ('40', 'accept'), ('47', 'accept'), ('47', 'progress'), ('47', 'complete'),
        ('133', 'accept'), ('133', 'complete'), ('1048', 'accept'), ('1048', 'progress'), ('9035', 'accept')}
for r in csv.DictReader(open('plan_v3.csv')):
    if (r['questId'], r['kind']) not in want or r['variant'] == 'f': continue
    if glob.glob(f"{OUT}/*_{r['questId']}-{r['kind']}_*.mp3"): continue
    d = D[r['questId']][r['kind']]; texts = [render.scripted(t) for t in render.beat_texts(r['questId'], r['kind'], r['variant'], d['beats'])]
    if r['npc_name'] == 'Billy Maclure': spk = billy_ref
    elif r['action'] == 'reuse': spk = render.speaker_ref(dict(r, clone_ref=f"{r['source_pack']}:{r['file_in_pack']}"))
    else: spk = render.speaker_ref(r)
    sex = r['sex'] if r['sex'] in ('male', 'female') else 'male'
    parts = [render.render_beat(render.speakable(t), spk, render.style_clip(b['style'], sex, r['race']), f"ns_{r['questId']}_{r['kind']}_{i}",
                                alpha=render.alpha_for(b['intensity'])) for i, (t, b) in enumerate(zip(texts, d['beats']))]
    who = r['npc_name'].replace(' ', '_').replace('"', '')
    styles = '+'.join(f"{b['style']}@{b['intensity']}" for b in d['beats'])
    render.join(render.even_pace(parts, texts), f"{OUT}/{who}_{r['questId']}-{r['kind']}_{styles}.mp3"); print(who, r['questId'], r['kind'], styles, flush=True)
