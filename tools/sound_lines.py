"""Lines with no words to say (2026-10-30, the producer, on the Winterfin murlocs' chat text: "This is supposed to be a
gutteral vocalization. Comes through as 'argl gee ellrr g el gee'"; "It sounds like someone saying letters. There are
murloc sounds in the game already"). Their text is murloc speech -- "Mmrrglglglg? Glbmr brmmrggl glmrrbmrgl." -- so the
line is built from the client's own murloc sounds (Sound\\Creature\\Murloc), one per sentence, instead of being spoken.
data/sound_lines.json: {"<line>": ["<client sound>", ...]}. Builds render/<line>.mp3 and marks the line done, on CPU.

Run from data/:  ../.venv/bin/python ../tools/sound_lines.py
"""
import json, os, sqlite3, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
from mpqget import MPQ
CLIENT = f'{LV.WOW_DATA}/common.MPQ'
GAP = 0.3

if __name__ == '__main__':
    lines = json.load(open('sound_lines.json')); os.makedirs('sfx/client', exist_ok=True)
    m = MPQ(CLIENT); c = sqlite3.connect('overnight.sqlite')
    for nm, sounds in lines.items():
        if nm.startswith('_'): continue
        files = []
        for s in sounds:
            dst = f"sfx/client/{s.rsplit(chr(92), 1)[1]}"
            if not os.path.exists(dst): open(dst, 'wb').write(m.read(s))
            files.append(dst)
        inp = sum((['-i', f] for f in files), [])
        flt = ''.join(f'[{i}:a]aresample=24000,aformat=channel_layouts=mono,apad=pad_dur={GAP}[a{i}];' for i in range(len(files)))
        flt += ''.join(f'[a{i}]' for i in range(len(files))) + f'concat=n={len(files)}:v=0:a=1,loudnorm=I=-18:TP=-1.5[o]'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', *inp, '-filter_complex', flt, '-map', '[o]', '-b:a', '128k', f'render/{nm}.mp3'], check=True)
        c.execute("UPDATE lines SET status='done', score=1.0, heard=?, updated=datetime('now','localtime') WHERE name=?",
                  ('(murloc sounds, no words: sound_lines.json)', nm))
        print(nm, len(files), 'sounds')
    c.commit(); m.close()
