"""Billy round 9, step 1 (voice-over venv, card 1): boy 10's longer reference (~25 s: storytelling + studio sentences),
high-passed, then ClearerVoice MossFormer2_SE_48K -- the step the research recommends before cloning."""
import glob, os, subprocess, sys
import lvconfig as LV
OUT = f'{LV.COMFY_OUT}/voice_test/child/round9/parts'
B = f'{LV.CORPORA}/plymouth_children/english_children'
fs = sorted(glob.glob(f'{B}/english_free_speech/files_cut_by_sentences/10_M_nonNative/*.wav')) + \
     sorted(glob.glob(f'{B}/english_words_sentences/10_M_nonNative/studio_mic/sentences/*.wav'))
dur = lambda f: float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], capture_output=True, text=True).stdout)
fs = sorted(fs, key=lambda f: -dur(f)); pick, tot = [], 0.0
for f in fs:
    if tot >= 25: break
    if dur(f) >= 1.2: pick.append(f); tot += dur(f)
TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
n = len(pick); raw = f'{OUT}/boy10_25s_raw.wav'
flt = ''.join(f'[{i}:a]{TRIM},highpass=f=80,aresample=48000,aformat=channel_layouts=mono[a{i}];' for i in range(n))
flt += ''.join(f'anullsrc=r=48000:cl=mono,atrim=0:0.3[s{i}];' for i in range(n - 1))
flt += ''.join(f'[a{i}]' + (f'[s{i}]' if i < n - 1 else '') for i in range(n)) + f'concat=n={2 * n - 1}:v=0:a=1[o]'
subprocess.run(['ffmpeg', '-y', '-v', 'error', *sum((['-i', f] for f in pick), []), '-filter_complex', flt, '-map', '[o]', '-ar', '48000', raw], check=True)
print('raw', n, 'clips', round(tot, 1), 's')
os.chdir(f'{LV.MODELS}/TTS'); os.makedirs('clearvoice', exist_ok=True); os.chdir('clearvoice')   # weights land here
from clearvoice import ClearVoice
cv = ClearVoice(task='speech_enhancement', model_names=['MossFormer2_SE_48K'])
out = cv(input_path=raw, online_write=False)
cv.write(out, output_path=f'{OUT}/boy10_25s_mossformer.wav')
print('mossformer done')
