"""Three-way accent test (2026-10-11): A = pilot render (designed voice), B = an SLR83 dialect speaker as the voice
reference (accent) + the same direction, C = B converted to the designed voice (ChatterBox VC) -- accent and
direction from B, timbre from our designed persona.
Run from data/ with the ComfyUI venv; card-1 ComfyUI on 42422.
"""
import csv, json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import render
from direct import style_clip
OUT = f'{render.ROOT}/voice_test/accent_test'; os.makedirs(OUT, exist_ok=True)
SLR = f'{LV.CORPORA}/slr83/refs'
TESTS = [('62', 'complete', 'nom_09697', 'Northern English man'),
         ('109', 'accept', 'mim_04310', 'Midlands man'),
         ('88', 'accept', 'mif_03397', 'Midlands woman')]
D = {json.loads(l)['questId']: json.loads(l) for l in open('pilot_directions.jsonl')}
plan = {(r['questId'], r['kind'], r['variant']): r for r in csv.DictReader(open('plan_v3.csv'))}

def vc(src, target, tag):
    wf = {'1': {'class_type': 'ChatterBoxEngineNode', 'inputs': {'language': 'English', 'device': 'cuda', 'exaggeration': 0.5,
              'temperature': 0.8, 'cfg_weight': 0.5, 'crash_protection_template': ''}},
          '2': {'class_type': 'LoadAudio', 'inputs': {'audio': render.upload(src)}},
          '3': {'class_type': 'LoadAudio', 'inputs': {'audio': render.upload(target)}},
          '4': {'class_type': 'UnifiedVoiceChangerNode', 'inputs': {'TTS_engine': ['1', 0], 'source_audio': ['2', 0],
              'narrator_target': ['3', 0], 'refinement_passes': 1, 'max_chunk_duration': 30, 'chunk_method': 'smart'}},
          '5': {'class_type': 'SaveAudio', 'inputs': {'audio': ['4', 0], 'filename_prefix': f'render_parts/{tag}'}}}
    return render.comfy(wf)

lines = []
for qid, kind, spk, desc in TESTS:
    row = plan[(qid, kind, '')]; d = D[qid][kind]
    if row['action'] == 'reuse': row = dict(row, _ours=True)
    who = row['npc_name'].replace(' ', '_')
    texts = render.beat_texts(qid, kind, '', d['beats']); sex = row['sex']
    designed = render.speaker_ref(dict(row, _ours=True))
    a_src = f"render/{qid}-{kind}.mp3" if os.path.exists(f"render/{qid}-{kind}.mp3") else f"render_compare/{qid}-{kind}.mp3"
    shutil.copy(a_src, f'{OUT}/{who}_{qid}_{kind}_A_designed.mp3')
    parts = [render.render_beat(render.speakable(t), f'{SLR}/{spk}.wav', style_clip(b['style'], sex), f'acc_{qid}_{i}')
             for i, (t, b) in enumerate(zip(texts, d['beats']))]
    b_out = f'{OUT}/{who}_{qid}_{kind}_B_accent.mp3'; render.join(render.even_pace(parts, texts), b_out)
    c_raw = vc(b_out, designed, f'acc_vc_{qid}')
    c_out = f'{OUT}/{who}_{qid}_{kind}_C_accent_then_designed.mp3'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', c_raw, '-af', 'loudnorm=I=-18:TP=-1.5', '-ar', '24000', '-b:a', '128k', c_out], check=True)
    shutil.copy(f'{SLR}/{spk}.wav', f'{OUT}/{who}_accent_source_{spk}.wav')
    lines.append(f"{who} quest {qid} {kind} -- accent source: SLR83 {spk} ({desc})\n   styles: {' / '.join(b['style'] for b in d['beats'])}\n   text: {' '.join(texts)}")
    print(who, 'done', flush=True)
open(f'{OUT}/LISTEN.txt', 'w').write(
    'A = pilot render: designed voice (Qwen3 Voice Design) cloned + direction\n'
    'B = the dialect speaker as the voice + the same direction (accent and their own timbre)\n'
    'C = B voice-converted to the designed voice (ChatterBox VC): accent/direction from B, timbre from A\n'
    'accent_source_*.wav = the volunteer recordings used (OpenSLR 83, CC BY-SA 4.0)\n\n' + '\n\n'.join(lines) + '\n')
