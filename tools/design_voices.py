"""Designed voices: the model casts each NPC that has no usable voice of its own (human men, children, elders,
narrator for objects/items) from its chatter profile; Qwen3 Voice Design then performs one of the NPC's own lines
in that voice, and the clip becomes the NPC's clone reference.

Run from data/:
  ../.venv/bin/python ../tools/design_voices.py cast <quest list>       -> voice_cast.json (Gemma; merges, resumable)
  ../.venv/bin/python ../tools/design_voices.py cast-compare <list>     ... plus every reused line's speaker (pack vs ours)
  ~/ComfyUI/venv/bin/python ../tools/design_voices.py render [ids...]    -> designed_voices/<npc>.mp3 (card-1 ComfyUI 42422)
"""
import csv, json, os, re, sys, time, urllib.request, urllib.error, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV

CAST = 'voice_cast.json'; OUTDIR = 'designed_voices'
ROOT = f'{LV.COMFY_OUT}'; LISTEN = f'{ROOT}/voice_test/designed'
NARRATOR = 'narrator'

SYSTEM = """You are the casting director for an English-language voice-over of World of Warcraft quest givers. For \
one character, write the description a voice-design model will use to create their voice.

House style (the producer's notes): voices must sound lived-in and textured, never smooth, polished or like an \
announcer or audiobook narrator. Humans of the Eastern Kingdoms use British and Irish regional accents chosen to fit \
the person -- West Country or rural for farmers, Northern or Midlands for soldiers and labourers, London for rogues \
and traders, educated southern English for nobles, clergy and scholars. Never American, never a Texan drawl. Other \
races: dwarves Scottish, gnomes quick and nasal, night elves soft and unhurried, draenei an Eastern European lilt, \
blood elves refined and haughty, orcs deep and gravelly, trolls Caribbean, tauren deep and slow, undead hollow and \
rasping, goblins fast New York hustlers. A child must sound like a real child of the stated age (high, light, not an \
adult imitating one); an elder must sound genuinely old (thin, cracked or wavering as fits).

The profile's mood words ("weary from duty", "frustrated", "anxious") describe a mood that the director handles line \
by line; do not bake them into the voice itself. Describe the person's natural speaking voice -- tiredness belongs in \
the voice only when they are old, ill or worn by age.

Write 30-55 words covering: sex and age, accent, pitch and timbre, texture (rasp, breath, warmth), pace and \
manner. Describe only the voice -- no story, no names. Answer with JSON: {"description": "..."}"""

def llm(user):
    body = {'model': LV.LLM_MODEL, 'temperature': 0.5, 'max_tokens': 300,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'cast', 'schema': {
                'type': 'object', 'required': ['description'], 'properties': {'description': {'type': 'string'}}}}},
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]}
    r = urllib.request.Request(f'{LV.LLM_URL}/v1/chat/completions', data=json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json'})
    return json.loads(json.load(urllib.request.urlopen(r, timeout=300))['choices'][0]['message']['content'])['description']

def needs(quests, compare=False):
    """npc_id -> (name, race, sex, [(questId, kind)]) for designed lines in these quests; objects/items -> narrator.
    compare=True also takes every REUSED line's speaker, so the pilot can set pack against our own version."""
    out = {}
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['questId'] not in quests: continue
        if not ((r['action'] == 'generate' and r['clone_ref'].startswith('design:')) or (compare and r['action'] == 'reuse')):
            continue
        # an unknown race is the narrator, except a child: Illiyana and Anilia (dryads) are people (2026-10-12)
        key = NARRATOR if r['npc_id'].startswith(('go:', 'item:')) or (r['race'] == 'unknown' and not r['clone_ref'].endswith('_child')) else r['npc_id']
        e = out.setdefault(key, [r['npc_name'] if key != NARRATOR else 'Narrator', r['race'], r['sex'], []])
        e[3].append((r['questId'], r['kind']))
    return out

def ref_text(lines):
    """a 25-60 word passage from the NPC's own lines (accept text preferred) for Voice Design to perform"""
    import direct
    best = ''
    for q, kind in sorted(lines, key=lambda x: x[1] != 'accept'):
        ss = direct.sentences(direct.clean(direct.Q[q][direct.KINDS[kind]] or ''))
        t = ''
        for s in ss:
            if len((t + ' ' + s).split()) > 60 and len(t.split()) >= 25: break
            t = (t + ' ' + s).strip()
        if len(t.split()) > len(best.split()): best = t
        if len(best.split()) >= 25: break
    if len(best.split()) < 20:     # too short to clone from: a neutral line in their voice brings it to ~10 s
        best = (best + " I've been at this a good while now, so listen closely, and I'll tell you plainly what you need to know.").strip()
    return best

def profiles():
    out = {}
    for r in csv.DictReader(open('npc_profiles.tsv'), delimiter='\t'):
        if r['spawn_guid'] not in ('', 'NULL'): continue
        try: out[r['entry']] = json.loads(r['persona'].replace('\\n', ' '))
        except ValueError: pass
    fixes = json.load(open('profile_fixes.json')) if os.path.exists('profile_fixes.json') else {}
    for e, f in fixes.items():
        if e in out: out[e].update({k: v for k, v in f.items() if k != 'why'})
    return out

def mentions(name, n=3):
    """up to n snippets from other quest texts that name this NPC (first + last name or the whole name)"""
    import direct
    key = name.split(' <')[0].strip('"'); out = []
    if len(key) < 5: return out
    for q in direct.Q.values():
        for col in ('desc', 'off'):
            t = direct.clean(q.get(col) or '')
            i = t.find(key)
            if i >= 0 and len(out) < n:
                a = max(0, t.rfind('.', 0, max(0, i - 120)) + 1); out.append(t[a:a + 240].strip())
    return out

def cast(quests, compare=False):
    import direct
    prof = profiles()
    have = json.load(open(CAST)) if os.path.exists(CAST) else {}
    for npc, (name, race, sex, lines) in needs(quests, compare).items():
        if npc in have: continue
        if npc == NARRATOR:
            user = ('Character: the narrator who reads aloud the text of wanted posters, letters, notes and other written '
                    'objects found in the world. A mature storyteller, warm and characterful but unobtrusive.')
        else:
            sub = direct.CT.get(npc, {}).get('subname') or ''
            p = prof.get(npc, {})
            age = {'child': 'a child', 'elder': 'elderly', 'adult': 'an adult'}.get(p.get('age'), 'unknown age')
            user = (f"Character: {name}{f' <{sub}>' if sub else ''}, {sex} {race}, {age} ({p.get('who', '')}).\n"
                    f"Who they are: {direct.PERSONA.get(npc, 'unknown')}\n"
                    f"Their own words: \"{ref_text(lines)}\"\n"
                    + ''.join(f'What others say of them: "{m}"\n' for m in mentions(name))
                    + "The profile's age is usually right; only if the words plainly contradict it (a 'child' "
                    "who is courting, an 'adult' who mentions their mum telling them off) cast the age the words show.")
            zone = direct.QT.get(lines[0][0], {}).get('QuestSortID')
            if zone and zone.isdigit() and int(zone) > 0: user += f"\nWhere they live: {direct.area.get(int(zone), '')}"
        have[npc] = {'name': name, 'race': race, 'sex': sex, 'description': llm(user), 'reference_text': ref_text(lines),
                     'lines': len(lines)}
        print(f"{name}: {have[npc]['description']}", flush=True)
        json.dump(have, open(CAST, 'w'), indent=1)

URL = LV.RENDERERS["1"]
def run(wf):
    r = urllib.request.Request(URL + '/prompt', data=json.dumps({'prompt': wf}).encode(), headers={'Content-Type': 'application/json'})
    try: pid = json.load(urllib.request.urlopen(r, timeout=60))['prompt_id']
    except urllib.error.HTTPError as e: raise RuntimeError(e.read()[:800])
    while True:
        h = json.load(urllib.request.urlopen(f'{URL}/history/{pid}', timeout=30))
        if pid in h: break
        time.sleep(1)
    st = h[pid]['status']
    if st.get('status_str') != 'success': raise RuntimeError(json.dumps(st.get('messages'))[-800:])
    f = [a for o in h[pid]['outputs'].values() for a in o.get('audio', [])][0]
    return f"{ROOT}/{f['subfolder']}/{f['filename']}"

def render(only):
    have = json.load(open(CAST)); os.makedirs(OUTDIR, exist_ok=True); os.makedirs(LISTEN, exist_ok=True)
    idx = []
    for npc, c in have.items():
        if only and npc not in only: continue
        if not only and os.path.exists(f'{OUTDIR}/{npc}.mp3'): continue      # already designed; name it to redo
        safe = re.sub(r'[^A-Za-z0-9]+', '_', c['name']).strip('_')
        wf = {'1': {'class_type': 'Qwen3TTSEngineNode', 'inputs': {'model_size': '1.7B', 'device': 'cuda',
                  'voice_preset': 'None (Zero-shot / Custom)', 'language': 'English', 'instruct': '', 'top_k': 50,
                  'top_p': 1.0, 'temperature': 0.9, 'repetition_penalty': 1.05, 'max_new_tokens': 4096}},
              '2': {'class_type': 'Qwen3TTSVoiceDesignerNode', 'inputs': {'TTS_engine': ['1', 0],
                  'voice_description': c['description'], 'reference_text': c['reference_text'], 'language': 'English',
                  'character_name': f'wow_npc_{npc}', 'overwrite_character': True}},
              '3': {'class_type': 'SaveAudioMP3', 'inputs': {'audio': ['2', 1], 'filename_prefix': f'voice_test/designed/parts/{npc}', 'quality': 'V0'}}}
        t0 = time.time(); p = run(wf)
        shutil.copy(p, f'{OUTDIR}/{npc}.mp3'); shutil.copy(p, f'{LISTEN}/{safe}.mp3')
        print(f"{c['name']}: {time.time() - t0:.0f}s", flush=True)
        idx.append(f"{safe}.mp3  ({c['sex']} {c['race']}, {c['lines']} lines)\n   cast: {c['description']}\n   says: {c['reference_text']}")
    idx = []
    for npc, c in have.items():
        if os.path.exists(f'{OUTDIR}/{npc}.mp3'):
            safe = re.sub(r'[^A-Za-z0-9]+', '_', c['name']).strip('_')
            idx.append(f"{safe}.mp3  ({c['sex']} {c['race']}, {c['lines']} lines)\n   cast: {c['description']}\n   says: {c['reference_text']}")
    open(f'{LISTEN}/INDEX.txt', 'w').write('\n\n'.join(sorted(idx)) + '\n')

if __name__ == '__main__':
    if sys.argv[1] in ('cast', 'cast-compare'): cast(set(open(sys.argv[2]).read().split()), sys.argv[1] == 'cast-compare')
    else: render(set(sys.argv[2:]))
