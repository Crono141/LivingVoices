"""Billy round 8: three candidate cheerful emotion clips, round 6 #3's voice (boy 10, MelBand, -1/-0.5)."""
import csv, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
R = render.ROOT; OUT = f'{R}/voice_test/child/round8'; os.makedirs(OUT + '/parts', exist_ok=True)
ref = f'{R}/voice_test/child/round6/parts/ref_melband_p-1_f-0.5.wav'
wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
          'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
          'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
      '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0], 'voice_description':
          "A friendly, relaxed man in a good mood, chatting warmly with a neighbour. Easy, light, smiling delivery, "
          "conversational pace, sentences that settle down at the end; never loud, never proclaiming.",
          'reference_text': "Well, good morning to you! Lovely day for it, isn't it. I've got just the thing you were after, "
                            "come and have a look. There we are. You take care now, and mind the puddles on the way home.",
          'language': 'English', 'character_name': 'wow_style_cheerful_male', 'overwrite_character': True}},
      '3': {'class_type': 'SaveAudio', 'inputs': {'audio': ['2', 1], 'filename_prefix': 'voice_test/child/round8/parts/designed_cheerful'}}}
designed = render.comfy(wf); shutil.copy(designed, f'{OUT}/b_emotion_clip_designed.flac')
cast = json.load(open('voice_cast.json')); bid = next(k for k, v in cast.items() if v['name'] == 'Billy Maclure')
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == bid and r['kind'] == 'accept')
d = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}[row['questId']]['accept']
texts = render.beat_texts(row['questId'], 'accept', row['variant'], d['beats'])
for tag, emo, alpha in (('a_rhonin_strength-0.4', 'game_voices/Rhonin/UR_Rhonin_Event03.wav', 0.4),
                        ('b_designed_cheerful_strength-0.55', designed, 0.55),
                        ('c_thassarian_warm_strength-0.55', 'game_voices/Thassarian/BT_Thassarian_BoreanEvent07.wav', 0.55)):
    render.ALPHA = alpha
    parts = [render.render_beat(render.speakable(render.scripted(t)), ref, emo, f'r8_{tag}_{k}') for k, t in enumerate(texts)]
    render.join(render.even_pace(parts, texts), f'{OUT}/{tag}.mp3'); print(tag, flush=True)
shutil.copy(f'{R}/voice_test/child/round6/3_billy_melband_pitch-1_formant-0.5.mp3', f'{OUT}/0_round6_no3_for_comparison.mp3')
