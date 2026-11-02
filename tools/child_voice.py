"""Child voices (2026-10-11): Qwen3 Voice Design cannot make a convincing child, so a child's reference is a designed
young voice shifted into a child's range -- pitch AND formants (a child's smaller vocal tract), by different amounts:
rubberband R3 twice: +f semitones without formant preservation (pitch and formants rise together), then +(p-f) with
formant preservation (pitch alone). The shifted clip is the NPC's clone reference; every line is then cloned from it.

  python3 child_voice.py <in.wav|mp3> <out.wav> <pitch_semitones> <formant_semitones>
"""
import subprocess, sys, tempfile, os

def childify(src, dst, pitch, formant):
    with tempfile.TemporaryDirectory() as t:
        a, b = os.path.join(t, 'a.wav'), os.path.join(t, 'b.wav')
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-ac', '1', '-ar', '44100', a], check=True)
        subprocess.run(['rubberband-r3', '-q', '-p', str(formant), a, b], check=True)                 # pitch + formants
        subprocess.run(['rubberband-r3', '-q', '-F', '-p', str(pitch - formant), b, dst], check=True)  # pitch only
    return dst

if __name__ == '__main__':
    childify(sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))
