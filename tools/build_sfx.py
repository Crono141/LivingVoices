"""Sound effects written into quest text (2026-10-12): *Whir* *Click* *Zzzap*, *sniff*, *hic*... are not words.
This extracts the game sounds that stand in for them from the 3.3.5 client into data/sfx/ (trimmed to <= 1.5 s,
loudness matched to speech) and writes data/sfx.json, which render.py reads:
  "<marker>": "sfx/<file>.wav"   splice that sound in        "emote:cry"  the speaker's race/sex emote
  "say:<text>"  the voice says it ("Hic!")                    "drop"       nothing ("*grin*" is an action)
  "word"        read the word itself ("*my*" is emphasis)    "cycle:a,b,c"  the next of these each time in a line
Run from data/:  python3 ../tools/build_sfx.py"""
import glob, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
from mpqget import MPQ
CLIENT = f'{LV.WOW_DATA}'
PICK = {   # marker -> client sound (chosen 2026-10-12; edit and re-run to change)
    'whir': r'Sound\Doodad\GnomeMachine03StandVar1.wav',
    'click': r'Sound\Interface\iUiInterfaceButtonA.wav',
    'zzzap': r'Sound\Doodad\ID_Forge_Zap01.wav',
    'bzzzz': r'Sound\Doodad\GnomeRoboArmStandFidget01Sparks.wav',
    'thud': r'Sound\Effects\DeathImpacts\mDeathImpactMediumWoodA.wav',
}
# sigh and yawn: the client's own /sigh and /yawn emotes, per race and sex like the cry (the producer, 2026-10-13)
OTHER = {'click-click': 'twice:click', 'sniff': 'emote:cry', 'sigh': 'emote:sigh', 'yawn': 'emote:yawn',
         'hic': 'say:Hic!', 'cough': 'drop', 'gasp': 'drop',
         'grin': 'say:Heh heh heh.', 'my': 'word'}
RACES = ['Human', 'Dwarf', 'NightElf', 'Gnome', 'Draenei', 'Orc', 'Scourge', 'Tauren', 'Troll', 'BloodElf', 'Goblin']

archives = {}
for p in sorted(glob.glob(CLIENT + '/*.MPQ') + glob.glob(CLIENT + '/*/*.MPQ')):
    try:
        m = MPQ(p)
        for f in m.read('(listfile)').decode('latin1').split('\r\n'):
            if f.lower().endswith('.wav'):
                archives[f.lower()] = (p, f)
        m.close()
    except Exception:
        pass

def extract(path, dst):
    p, f = archives[path.lower()]
    m = MPQ(p); raw = m.read(f); m.close()
    tmp = dst + '.raw'
    open(tmp, 'wb').write(raw)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-t', '1.5', '-af',
                    'afade=t=out:st=1.3:d=0.2,loudnorm=I=-22:TP=-3', '-ac', '1', '-ar', '24000', dst], check=True)
    os.remove(tmp)

os.makedirs('sfx', exist_ok=True)
out = {}
for marker, path in PICK.items():
    extract(path, f'sfx/{marker}.wav'); out[marker] = f'sfx/{marker}.wav'
for emote in ('cry', 'sigh', 'yawn'):    # the emotes, per race and sex (the path layout varies by race)
    for race in RACES:
        for sex in ('Male', 'Female'):
            hit = next((k for k in archives if re.search(rf'\\{race.lower()}{sex.lower()}{emote}0?1\.wav$', k)), None)
            if hit:
                extract(archives[hit][1], f'sfx/{emote}_{race.lower()}_{sex.lower()}.wav')
# the chicken (2026-10-16, the producer): no plain cluck in the client, but the chicken mount's call opens with three
# clean ones (0.04-0.23, 0.26-0.42, 0.44-0.60 s), cut apart for variety; a pure bacaw is the mount's wound cry
def cut(path, dst, a, b):
    p, f = archives[path.lower()]; m = MPQ(p); raw = m.read(f); m.close()
    tmp = dst + '.raw'; open(tmp, 'wb').write(raw)
    # loudness over the whole call first (a 0.16 s cluck is too short to measure), then the cut -- in one pass the
    # loudness filter's delay shifted the cut (cluck 2 came out half its length)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-af', 'loudnorm=I=-22:TP=-3', '-ac', '1', '-ar', '24000', tmp + '.wav'], check=True)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp + '.wav', '-af', f'atrim={a}:{b},asetpts=N/SR/TB,'
                    'afade=t=in:d=0.01,areverse,afade=t=in:d=0.03,areverse', dst], check=True)
    os.remove(tmp); os.remove(tmp + '.wav')
for i, (a, b) in enumerate(((0.04, 0.23), (0.26, 0.42), (0.44, 0.60)), 1):
    cut(r'Sound\Creature\ChickenMount\ChickenMountSpecialMount.wav', f'sfx/cluck{i}.wav', a, b)
for i in (1, 2):
    extract(rf'Sound\Creature\ChickenMount\ChickenMountWound{i}.wav', f'sfx/bacaw{i}.wav')
# every <snort> in the game is Mangletooth's, a captive quilboar. (2026-10-26, the producer, from the 41 cuts of
# snort_candidates.py) the wild boar's second, breathy burst, 0.25 s: QuillBoarPreAggro (his pick of 2026-10-13) was
# 0.97 s and read as a piggish grumble -- "a half to a quarter the length, and more like a snort"
cut(r'Sound\Creature\Boar\mWildBoarWound1.wav', 'sfx/snort.wav', 0.99, 1.245)
out['snort'] = 'sfx/snort.wav'
out.update({'cluck': 'cycle:sfx/cluck1.wav,sfx/cluck2.wav,sfx/cluck3.wav', 'bacaw': 'cycle:sfx/bacaw1.wav,sfx/bacaw2.wav'})
out.update(OTHER)
json.dump(out, open('sfx.json', 'w'), indent=1)
print(len(out), 'markers;', {e: len(glob.glob(f'sfx/{e}_*.wav')) for e in ('cry', 'sigh', 'yawn')}, 'emotes')
