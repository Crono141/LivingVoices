"""Extract the client's own voice clips for every quest giver in npc_voices.json.

Run from data/:  ../.venv/bin/python ../tools/game_voices.py [listen_dir]
- data/game_voices/<Character>/<file>.wav  (one folder per character name: Thrall's entries share it)
- data/game_voices/index.json: character -> [{file, wav, dur, text, src, kind}] and npc ids
- listen_dir (optional): 3 sample clips per character with a transcript line in INDEX.txt
"""
import json, os, re, sys, wave, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
from mpqget import MPQ
D = f'{LV.WOW_DATA}/'
v = json.load(open('npc_voices.json'))
arch = {}
def mpq(m):
    if m not in arch: arch[m] = MPQ(D + m)
    return arch[m]
folder = lambda n: re.sub(r'[^A-Za-z0-9]+', '_', n).strip('_')

chars = collections.defaultdict(lambda: {'npcs': [], 'clips': {}})
for npc, o in v.items():
    c = chars[o['name']]; c['npcs'].append(npc)
    for kind, xs in (('line', o['lines']), ('greet', o['greet'])):
        for x in xs:
            if x['file'] not in c['clips'] or (x.get('text') and not c['clips'][x['file']].get('text')):
                c['clips'][x['file']] = dict(x, kind=kind)
out = {}
for name, c in chars.items():
    d = os.path.join('game_voices', folder(name)); os.makedirs(d, exist_ok=True)
    clips = []
    for f, x in c['clips'].items():
        dst = os.path.join(d, f.rsplit('\\', 1)[1].replace(' ', '_'))
        if not os.path.exists(dst):
            try: open(dst, 'wb').write(mpq(x['mpq']).read(f))
            except Exception as e: print('!!', name, f, e); continue
        try:
            with wave.open(dst) as w: dur = w.getnframes() / w.getframerate()
        except Exception: dur = None
        clips.append(dict(file=f, wav=dst, dur=dur, text=x.get('text'), src=x.get('src', 'npcsounds'), kind=x['kind']))
    out[name] = dict(npcs=c['npcs'], clips=clips)
json.dump(out, open('game_voices/index.json', 'w'), indent=1)
n = sum(len(c['clips']) for c in out.values())
print('characters', len(out), 'clips', n, 'seconds', round(sum(x['dur'] or 0 for c in out.values() for x in c['clips'])))

if len(sys.argv) > 1:
    L = sys.argv[1]; os.makedirs(L, exist_ok=True); idx = []
    for name in sorted(out, key=lambda k: -len(out[k]['clips'])):
        cl = out[name]['clips']
        # transcribed dialogue of 4-15 s first, then anything 2 s+
        good = sorted((x for x in cl if x['text'] and x['dur'] and 4 <= x['dur'] <= 15), key=lambda x: -x['dur'])
        rest = sorted((x for x in cl if x not in good and x['dur'] and x['dur'] >= 1.5), key=lambda x: -x['dur'])
        pick = (good + rest)[:3]
        if not pick: continue
        sub = os.path.join(L, folder(name)); os.makedirs(sub, exist_ok=True)
        idx.append(f"\n{name}  ({len(cl)} clips, npc {','.join(out[name]['npcs'])})")
        for i, x in enumerate(pick, 1):
            dst = os.path.join(sub, f"{i}_{os.path.basename(x['wav'])}")
            os.system(f"cp '{x['wav']}' '{dst}'")
            idx.append(f"  {i}. {x['dur']:.1f}s  {(x['text'] or '(no transcript: ' + x['kind'] + ')')[:160]}")
    open(os.path.join(L, 'INDEX.txt'), 'w').write('\n'.join(idx).strip() + '\n')
    print('listen set:', L)
