"""wry_male, take 2 (the producer: take 1 was nasal and not wry): two variants, lower and chest-voiced."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
TEXT = ("Well. That went about as well as I expected, which is to say, not at all. Still, somebody has to clean up after "
        "the heroes. Lucky me. Don't look so surprised. It's practically a family tradition.")
TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
V = {'a': "A man in his late forties with a relaxed, low, warm chest voice -- a baritone, not nasal at all. He speaks "
          "dryly and deadpan, unhurried, with a quiet smile behind the words, like a seasoned barkeep enjoying a private joke.",
     'b': "A man in his fifties, gravel-edged and easy-going, a low resonant voice from the chest, never nasal. Bone-dry "
          "and sardonic, understated, every line with a raised eyebrow and a knowing pause, amused rather than bitter."}
for k, desc in V.items():
    wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
              'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
              'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
          '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0], 'voice_description': desc,
              'reference_text': TEXT, 'language': 'English', 'character_name': f'wow_style_wry_male_{k}', 'overwrite_character': True}},
          '3': {'class_type': 'SaveAudio', 'inputs': {'audio': ['2', 1], 'filename_prefix': f'voice_test/styles_new/parts/wry_male_{k}'}}}
    src = render.comfy(wf); dst = f'style_sets/designed/wry_male_{k}.wav'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-af', f'{TRIM},loudnorm=I=-20:TP=-2', '-ac', '1', '-ar', '24000', dst], check=True)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', dst, '-b:a', '128k', f'{render.ROOT}/voice_test/styles_new/wry_male_take2_{k}.mp3'], check=True)
    print('wry_male', k, flush=True)
