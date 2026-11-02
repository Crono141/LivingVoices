"""Listening samples for the child cast (2026-10-12): every child speaks one of its OWN quest lines through the
real renderer (IndexTTS-2 from its designed_voices reference, a neutral steady style at intensity 4, the child
de-ess) -- what the game will play, not the reference clip. -> voice_test/child_cast/samples/<name>_<npc>.mp3
Run from data/ with the ComfyUI venv; card-1 ComfyUI (tools/comfy2.sh start)."""
import csv, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render, child_cast, requests
OUT = f'{child_cast.LISTEN}/samples'; os.makedirs(OUT, exist_ok=True)
requests.post(render.URL + '/free', json={'unload_models': True, 'free_memory': True}, timeout=60)
best = {}
for r in csv.DictReader(open('plan_v3.csv')):
    if not r['clone_ref'].endswith('_child') or r['variant'] == 'f':
        continue
    w = int(r['words'] or 0)
    if 12 <= w <= 45 and (r['npc_id'] not in best or abs(w - 25) < abs(int(best[r['npc_id']]['words']) - 25)):
        best[r['npc_id']] = r
only = set(sys.argv[1:])
for npc, r in best.items():
    if only and npc not in only:
        continue
    name = re.sub(r'[^A-Za-z0-9]+', '_', r['npc_name']).strip('_')
    dst = f'{OUT}/{name}_{npc}.mp3'
    text = render.scripted(render.variant_clean(render.direct.Q[r['questId']][render.direct.KINDS[r['kind']]] or '', r['variant']))
    sex = r['sex'] if r['sex'] in ('male', 'female') else 'male'
    part = render.render_beat(render.calm(render.speakable(text), 4), render.speaker_ref(r),
                              render.style_clip('steady_explaining', sex, r['race']), f'childsample_{npc}', alpha=render.alpha_for(4))
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', part, '-af', 'deesser=i=0.5:m=0.5:f=0.5:s=o', '-ac', '1', '-b:a', '128k', dst], check=True)
    print(f"{r['npc_name']} ({npc}, {r['race']} {r['sex']}): {text[:70]}", flush=True)
