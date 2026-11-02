"""Billy child round 2 + reference-artifact test (2026-10-11). Card-1 ComfyUI. Run from data/."""
import csv, json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, child_voice
R = render.ROOT

# ---- Billy, round 2
OUT = f'{R}/voice_test/child/round2'; os.makedirs(OUT + '/parts', exist_ok=True)
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
girl = f'{R}/voice_test/child/0_base_girl_voice.mp3'
wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
          'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
          'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
      '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0], 'voice_description':
          "A tomboyish girl of about eleven with a London lilt. Husky, low for her age, a little rough and scratchy from "
          "shouting outdoors, quick and cheeky, slightly defensive, trailing off with 'er's. Natural, not polished.",
          'reference_text': cast[bid]['reference_text'], 'language': 'English', 'character_name': 'wow_child_test_tomboy', 'overwrite_character': True}},
      '3': {'class_type': 'SaveAudioMP3', 'inputs': {'audio': ['2', 1], 'filename_prefix': 'voice_test/child/round2/parts/tomboy', 'quality': 'V0'}}}
tomboy = render.comfy(wf); shutil.copy(tomboy, f'{OUT}/0_base_husky.mp3')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
D = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}
d = D[row['questId']]['accept']; texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
def line(ref, name, race='human', sex='male'):
    parts = [render.render_beat(render.speakable(render.scripted(t)), ref, render.style_clip(b['style'], sex, race), f'r2_{name}_{i}')
             for i, (t, b) in enumerate(zip(texts, d['beats']))]
    render.join(render.even_pace(parts, texts), f'{OUT}/{name}.mp3')
for i, (base, bn, p, f) in enumerate([(girl, 'girl', 6, 2), (girl, 'girl', 6, 1.5), (girl, 'girl', 5.5, 1.5), (tomboy, 'husky', 6, 2)], 1):
    ref = f'{OUT}/parts/{bn}_p{p}_f{f}.wav'; child_voice.childify(base, ref, p, f)
    line(ref, f'{i}_billy_{bn}_pitch+{p}_formant+{f}')
print('billy done')

# ---- reference-artifact test on three race-sample lines (pack-cloned NPCs)
OUT2 = f'{R}/voice_test/artifacts'; os.makedirs(OUT2, exist_ok=True)
CLEAN = 'highpass=f=60,adeclick,afftdn=nf=-28,aresample=24000:resampler=soxr'
def clean(src, tag):
    dst = f'refs_cache/clean_{tag}.wav'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-af', CLEAN, '-ac', '1', dst], check=True); return dst
SD = {json.loads(l)['questId']: json.loads(l) for l in open('race_sample_directions.jsonl')}
rows = [r for r in csv.DictReader(open('plan_v3.csv')) if r['questId'] in SD and r['action'] == 'generate' and r['kind'] == 'accept'
        and r['clone_ref'].split(':')[0].startswith(('speakstone', 'spoken'))][:3]
for r in rows:
    d = SD[r['questId']][r['kind']]; ts = render.beat_texts(r['questId'], r['kind'], r['variant'], d['beats'])
    spk = render.speaker_ref(r); sx = r['sex'] if r['sex'] in ('male', 'female') else 'male'
    who = r['npc_name'].replace(' ', '_').replace("'", '')
    for mode in ('as_now', 'clean_refs'):
        parts = []
        for i, (t, b) in enumerate(zip(ts, d['beats'])):
            emo = render.style_clip(b['style'], sx, r['race'])
            s_, e_ = (spk, emo) if mode == 'as_now' else (clean(spk, f'{who}_spk'), clean(emo, f"{b['style']}_{who}"))
            parts.append(render.render_beat(render.speakable(render.scripted(t)), s_, e_, f'art_{who}_{mode}_{i}'))
        dst = f"{OUT2}/{who}_{r['questId']}_{mode}.mp3"; render.join(render.even_pace(parts, ts), dst)
        if mode == 'as_now':
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', dst, '-af', 'adeclick,adeclip', '-b:a', '128k',
                            f"{OUT2}/{who}_{r['questId']}_clean_output.mp3"], check=True)
    print('artifact test:', who)
