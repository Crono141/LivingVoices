"""Billy Maclure child-voice test: his current voice vs a designed young girl's voice shifted into a child's range,
three strengths, each cloned on the same line. Needs the card-1 ComfyUI (42422). Run from data/."""
import json, os, shutil, sys, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, design_voices, child_voice
OUT = f'{render.ROOT}/voice_test/child'; os.makedirs(OUT, exist_ok=True)
cast = json.load(open('voice_cast.json'))
bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure'); b = cast[bid]
base_desc = ("A girl of about ten with a London lilt. Light, high, bright young voice, a little breathless and quick, "
             "slightly defensive and cheeky, trailing off with 'er's. Lived-in and natural, not polished.")
wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
          'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
          'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
      '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0], 'voice_description': base_desc,
          'reference_text': b['reference_text'], 'language': 'English', 'character_name': 'wow_child_test_billy', 'overwrite_character': True}},
      '3': {'class_type': 'SaveAudioMP3', 'inputs': {'audio': ['2', 1], 'filename_prefix': 'voice_test/child/parts/base', 'quality': 'V0'}}}
base = render.comfy(wf); shutil.copy(base, f'{OUT}/0_base_girl_voice.mp3')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
D = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}
d = D[row['questId']]['accept']; texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
def line(ref, name):
    parts = [render.render_beat(render.speakable(render.scripted(t)), ref, render.style_clip(bb['style'], 'male', 'human'), f'child_{name}_{i}')
             for i, (t, bb) in enumerate(zip(texts, d['beats']))]
    render.join(render.even_pace(parts, texts), f'{OUT}/{name}.mp3')
line(render.speaker_ref(dict(row, _ours=True)), '1_current_billy')
for i, (p, f) in enumerate([(4, 2), (5, 2.5), (6, 3)], 2):
    ref = f'{OUT}/parts/ref_p{p}_f{f}.wav'; os.makedirs(f'{OUT}/parts', exist_ok=True)
    child_voice.childify(base, ref, p, f)
    shutil.copy(ref, f'{OUT}/{i}_reference_pitch+{p}_formant+{f}.wav')
    line(ref, f'{i}_billy_pitch+{p}_formant+{f}')
print('done ->', OUT, '| line:', ' '.join(texts)[:120])
