"""Designed emotion clips for the five survey styles (2026-10-12), plus cheerful (Rhonin's game clip carried its
mastering and room into Billy's render): one continuous, clean take per style and sex,
performed by Qwen3 Voice Design in an unremarkable adult voice (little timbre to leak). Card-1 ComfyUI (42422).
-> data/style_sets/designed/<style>_<sex>.wav (24 kHz mono, trimmed, loudness-matched)"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
OUT = 'style_sets/designed'; os.makedirs(OUT, exist_ok=True)
VOICE = {'male': 'A man in his forties with a natural, unremarkable English voice, mid pitch',
         'female': 'A woman in her thirties with a natural, unremarkable English voice, mid pitch'}
STYLE = {
 'pleading': ("pleading for help, frightened and earnest, voice tight with worry, at conversational volume -- not screaming",
   "Please, you have to help me. They took my brother, and I don't know where they've gone. I can't do this alone. "
   "I'm begging you, just help me find him, before it's too late."),
 'relieved_grateful': ("relieved and grateful, the tension leaving the voice, warm and a little breathless, conversational",
   "Oh, thank goodness, you're back. I was starting to fear the worst. You did it, you really did it. "
   "I can't thank you enough. Here, please, take this. You've earned it."),
 'wry': ("dry, wry and ironic, deadpan with a hint of a smile, unhurried, low-key",
   "Well. That went about as well as I expected, which is to say, not at all. Still, somebody has to clean up after "
   "the heroes. Lucky me. Don't look so surprised. It's practically a family tradition."),
 'sly': ("sly and conspiratorial, lowered voice, a knowing half-smile, smooth and persuasive, quiet",
   "Now, between you and me, there's a little something I could use a hand with. Nothing anyone needs to hear about, "
   "mind you. Do this for me, quietly, and I'll make it well worth your while. We understand each other, don't we?"),
 'cheerful': ("cheerful and friendly, bright and smiling, easy and relaxed, at conversational volume -- not shouting or announcing",
   "Oh, good morning to you! Lovely day for it, isn't it? The sun's out, the bread's fresh, and the fields have never "
   "looked better. Come in, come in, sit yourself down. It's always nice to see a friendly face around here."),
 'smug': ("smug, sarcastic and mocking, a smirk you can hear in every word, drawling and pleased with yourself, "
          "talking down to someone you think you have outsmarted",
   "Oh, you lost something? That's terrible. Really, I'm heartbroken for you. Funny thing, though -- I might know "
   "where it went. But my memory's not so good when I'm hungry. Shame, isn't it?"),
 'hushed': ("whispering, hushed and breathy, barely voiced, leaning in close so no one else can hear -- a real whisper, "
            "not a soft speaking voice",
   "Hey. Over here. Keep your voice down, will you? I've got something for you, but nobody else needs to know about "
   "it. Come closer. Quietly now."),
 'mystical': ("serene and otherworldly, slow and soft, as if listening to something far away, calm and measured",
   "The spirits are restless tonight. I hear them whispering on the wind across the plains. They speak of a "
   "darkness stirring beneath the earth. Listen closely, and you will hear them too. All things are connected."),
}
TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
ONLY = set(sys.argv[1:])     # name styles to (re)design just those
for style, (manner, text) in STYLE.items():
    if ONLY and style not in ONLY: continue
    for sex, voice in VOICE.items():
        wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
                  'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
                  'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
              '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0],
                  'voice_description': f'{voice}, speaking {manner}.', 'reference_text': text, 'language': 'English',
                  'character_name': f'wow_style_{style}_{sex}', 'overwrite_character': True}},
              '3': {'class_type': 'SaveAudio', 'inputs': {'audio': ['2', 1], 'filename_prefix': f'voice_test/styles_new/parts/{style}_{sex}'}}}
        src = render.comfy(wf); dst = f'{OUT}/{style}_{sex}.wav'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-af', f'{TRIM},loudnorm=I=-20:TP=-2', '-ac', '1', '-ar', '24000', dst], check=True)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', dst, '-b:a', '128k', f'{render.ROOT}/voice_test/styles_new/{style}_{sex}.mp3'], check=True)
        print(style, sex, flush=True)
