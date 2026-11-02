"""Pronunciation test for '-shire' place names: one voice, the same line, several spellings. Card-1 ComfyUI."""
import csv, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
OUT = f'{render.ROOT}/voice_test/shire'; os.makedirs(OUT, exist_ok=True)
row = next(r for r in csv.DictReader(open('plan_v3.csv')) if r['npc_name'] == 'Marshal Dughan')
spk = render.speaker_ref(dict(row, _ours=True)); emo = render.style_clip('steady_explaining', 'male', 'human')
for i, suf in enumerate(['shire', '-shire', 'shyre', 'shyr', 'shyer', 'shier']):
    t = f"Report to the guards at North{suf}, then return to Gold{suf}."
    p = render.render_beat(t, spk, emo, f'shire_{i}')
    shutil.copy(p, f"{OUT}/{i}_North{suf.replace('-', '_')}.flac"); print(i, t)
