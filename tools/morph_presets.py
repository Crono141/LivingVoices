"""Novelty voice morphs (2026-10-13; the producer: "weird or wild morphs and presets we could try out"), for the
voices with nothing recorded -- beasts, giants, golems, robots, elementals, demons. Offline, CPU only: rubberband for
big pitch/formant moves and ffmpeg filters for the rest. Lyrebird's useful presets (pitch, downsample, volume) are
included under their own names; it is archived (2023) and its presets are only those three SoX settings.

  ~/ComfyUI/venv/bin/python ../tools/morph_presets.py <line.mp3> <out_dir>     (run from data/)
"""
import os, subprocess, sys, tempfile

ROBOT = "afftfilt=real='hypot(re,im)*sin(0)':imag='hypot(re,im)*cos(0)':win_size=512:overlap=0.75"
WHISPER = "afftfilt=real='hypot(re,im)*cos((random(0)*2-1)*2*3.14)':imag='hypot(re,im)*sin((random(1)*2-1)*2*3.14)':win_size=128:overlap=0.8"
# name -> (rubberband pitch, rubberband formant or None, ffmpeg filter chain or None, layer: octave-down copy mixed in)
PRESETS = {
    'lyrebird_darth_vader':  (-6.0, None, None, False),
    'lyrebird_chipmunk':     (10.0, None, None, False),
    'lyrebird_radio':        (None, None, 'aresample=4000,aresample=24000,highpass=f=300,lowpass=f=3000,volume=2', False),
    'lyrebird_bad_mic':      (None, None, 'aresample=3000,aresample=24000,volume=1.5', False),
    'giant':                 (-4.0, -4.0, 'aecho=0.8:0.7:60:0.25,lowpass=f=3500', False),
    'giant_stone':           (-5.0, -5.0, 'aecho=0.8:0.88:40|90:0.3|0.2,acrusher=bits=10:mix=0.2', False),
    'golem_flesh':           (-3.0, -2.0, 'chorus=0.6:0.9:50|60:0.4|0.32:0.25|0.4:2|2.3,acrusher=bits=8:mix=0.15', False),
    'demon':                 (-2.0, -2.0, 'acrusher=bits=12:mix=0.1,aecho=0.8:0.6:30:0.3', True),
    'robot':                 (None, None, ROBOT + ',acrusher=bits=8:mix=0.4', False),
    'robot_small':           (3.0, 3.0, ROBOT, False),
    'elemental_air':         (2.0, 1.0, 'flanger=delay=3:depth=6:speed=0.4,aecho=0.8:0.85:120|240:0.4|0.25,highpass=f=200', False),
    'elemental_water':       (-1.0, -1.0, 'aphaser=type=t:speed=0.5:decay=0.6,aecho=0.8:0.8:80:0.35', False),
    'elemental_fire':        (-2.0, -1.0, 'acrusher=bits=6:mix=0.2,tremolo=f=9:d=0.15', False),
    # (2026-10-18, the producer: "a tad too strong") echo, flanger and thinning at half: his pick of 100/70/50%
    'ghost':                 (1.0, 0.0, 'aecho=0.8:0.9:300|600:0.23|0.15,flanger=delay=2:depth=1.5,highpass=f=125', False),
    # (2026-10-18, the producer: "a tad too strong") 60% whisper over 40% of the speaker's own voice, a lighter echo
    'whisperer':             (None, None, 'asplit[d][w];[w]' + WHISPER + ',volume=0.6[ww];[d]volume=0.4[dd];[dd][ww]amix=inputs=2:normalize=0,aecho=0.8:0.8:100:0.2', False),
    # (2026-10-18, the producer's picks from three each) murlocs small and wet; tuskarr (walrus people) deep with a
    # chest -- the extra layers tried on top of it were inaudible; orc women a light grit and a faint octave below
    'murloc':                (2.0, 2.0, 'vibrato=f=11:d=0.25,equalizer=f=1200:t=q:w=1:g=6,highpass=f=180', False),
    'tuskarr':               (-2.0, -2.0, 'lowshelf=g=4:f=150,aecho=0.6:0.4:25:0.3', False),
    'orc_female_grit':       (None, None, 'lowshelf=g=2:f=180,volume=4dB,asoftclip=type=tanh:threshold=0.7,asplit[a][b];'
                              '[b]rubberband=pitch=0.5,lowpass=f=1500,volume=0.12[l];[a][l]amix=inputs=2:normalize=0', False),
    'insect':                (2.0, 3.0, 'tremolo=f=40:d=0.5,chorus=0.5:0.9:20:0.5:0.6:2', False),
    'beast_growl':           (-3.0, -1.5, 'vibrato=f=6:d=0.15,acrusher=bits=9:mix=0.25', True),
    # (2026-10-26, the producer: "a touch deeper") Mangletooth, picked deepest of three
    'quilboar_deep':         (-5.0, -2.5, 'vibrato=f=6:d=0.15,acrusher=bits=9:mix=0.25', True),
    # (2026-10-28, the producer) the red dragonflight's ethereal touch (Alexstrasza, Xerestrasza, Keristrasza's records
    # have a light echo): Aurastrasza; 'a little more than light' (light 0.12|0.08 at 35|70 ms; medium, too heavy, 0.2|0.14|0.08)
    'dragon_echo':           (None, None, 'aecho=0.8:0.65:38|75:0.15|0.1', False),
    # (2026-10-28, the producer) dragons in their dragon form: more echo, the 'strong' of the three samples
    'dragon_echo_strong':    (None, None, 'aecho=0.8:0.75:50|100|160:0.28|0.2|0.12', False),
    'tiny_critter':          (6.0, 5.0, 'vibrato=f=8:d=0.2', False),
}

def morph(src, dst, name):
    pitch, formant, chain, layer = PRESETS[name]
    with tempfile.TemporaryDirectory() as t:
        a = os.path.join(t, 'a.wav'); subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-ac', '1', '-ar', '24000', a], check=True)
        cur = a
        if pitch is not None:
            b = os.path.join(t, 'b.wav')
            if formant is None or formant == pitch:              # one pass: pitch and formants together
                subprocess.run(['rubberband-r3', '-q', '-p', str(pitch), cur, b], check=True)
            else:                                                 # formants by `formant`, the rest pitch only
                m = os.path.join(t, 'm.wav')
                subprocess.run(['rubberband-r3', '-q', '-p', str(formant), cur, m], check=True)
                subprocess.run(['rubberband-r3', '-q', '-F', '-p', str(pitch - formant), m, b], check=True)
            cur = b
        if layer:                                                 # an octave-down copy under it: size and menace
            o = os.path.join(t, 'o.wav'); subprocess.run(['rubberband-r3', '-q', '-p', '-12', cur, o], check=True)
            mx = os.path.join(t, 'mx.wav')
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', cur, '-i', o, '-filter_complex',
                            '[1:a]volume=0.45[l];[0:a][l]amix=inputs=2:normalize=0', mx], check=True); cur = mx
        af = (chain + ',' if chain else '') + 'loudnorm=I=-18:TP=-1.5'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', cur, '-af', af, '-ar', '24000', '-b:a', '128k', dst], check=True)
    return dst

if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True)
    subprocess.run(['cp', src, os.path.join(out, '00_original.mp3')])
    for n in PRESETS:
        try: morph(src, os.path.join(out, f'{n}.mp3'), n); print('ok', n)
        except subprocess.CalledProcessError as e: print('!!', n, e)
