"""The producer's note for a character, read from its OWN dialogue only (2026-10-12): every quest line it speaks goes
to the pinned Gemma, which answers with the brief an actor would get -- temperament, how strongly the character
feels things, how it talks -- inferring nothing the words do not show. No hand-written notes: with thousands of
speakers it has to be automatic. Written to data/actor_notes.json under the npc id (marked "auto"), where
direct.py reads it as "The producer on this character".
Run from data/:  ../.venv/bin/python ../tools/actor_read.py <npc id> [...]
"""
import csv, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvconfig as LV
import direct

SYSTEM = """You are a voice director preparing a brief for an actor. You will be given every line one character in \
World of Warcraft speaks in its quests, and what other characters say about it. From THESE WORDS ONLY -- infer nothing they do not show -- write 1-2 \
sentences on how this character should be played: temperament, how strongly they feel what they say (from restrained \
to melodramatic), and their manner of speaking. Name what the lines themselves show, e.g. curtness, rambling, \
flattery, formality. Do not invent backstory, age or appearance. Answer with JSON: {"note": "..."}"""

def lines_of(npc):
    out = []
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['npc_id'] == npc and r['variant'] != 'f':
            t = direct.clean(direct.Q[r['questId']][direct.KINDS[r['kind']]] or '')
            if t and t not in out:
                out.append(t)
    return out

def said_about(npc, name, own, n=6):
    """other characters' quest lines that name this one (first + last name or the whole name) -- dialogue too"""
    key = name.split(' <')[0].strip('"'); first = key.split()[0] if ' ' in key else None
    # a first name alone only within the character's own zones: "It could also be Billy" was an ogre, elsewhere
    zones = {direct.QT.get(r['questId'], {}).get('QuestSortID') for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == npc}
    out = []
    for r in csv.DictReader(open('plan_v3.csv')):
        if r['npc_id'] == npc or r['variant'] == 'f':
            continue
        t = direct.clean(direct.Q[r['questId']][direct.KINDS[r['kind']]] or '')
        if t in own or t in out:
            continue
        local = direct.QT.get(r['questId'], {}).get('QuestSortID') in zones
        if key in t or (local and first and len(first) > 3 and re.search(rf'\b{re.escape(first)}\b', t)):
            out.append(t)
        if len(out) >= n:
            break
    return out

def read(npc):
    lines = lines_of(npc)
    if not lines:
        return None
    name = next((r['npc_name'] for r in csv.DictReader(open('plan_v3.csv')) if r['npc_id'] == npc), '')
    about = said_about(npc, name, lines)
    user = (f'The character: {name}\n\nWhat {name} says:\n' + '\n\n'.join(f'Line {i + 1}: {t}' for i, t in enumerate(lines))
            + (f'\n\nWhat others say that mentions {name}:\n' + '\n\n'.join(f'- {t}' for t in about) if about else ''))
    body = {'model': LV.LLM_MODEL, 'temperature': 0.3, 'max_tokens': 300,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'note', 'schema': {
                'type': 'object', 'required': ['note'], 'properties': {'note': {'type': 'string'}}}}},
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]}
    r = urllib.request.Request(f'{LV.LLM_URL}/v1/chat/completions', data=json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json'})
    return json.loads(json.load(urllib.request.urlopen(r, timeout=300))['choices'][0]['message']['content'])['note'], len(lines)

def ensure(npcs):
    """notes for the speakers among `npcs` that have none yet (objects and items excluded); writes actor_notes.json
    and returns the new ones, so the caller can hand them to a running director (direct.ACTOR_NOTES)"""
    notes = json.load(open('actor_notes.json')) if os.path.exists('actor_notes.json') else {}
    auto = notes.setdefault('_auto', []); new = {}
    for npc in sorted(npcs):
        if npc in notes or npc.startswith(('go:', 'item:')) or npc == 'none':
            continue
        try:
            res = read(npc)
        except Exception as e:
            print(f'!! note for {npc}: {str(e)[:200]}', flush=True); continue
        if res:
            notes[npc] = new[npc] = res[0]
            auto.append(npc)
    if new:
        json.dump(notes, open('actor_notes.json', 'w'), indent=1, ensure_ascii=False)
    return new

if __name__ == '__main__':
    notes = json.load(open('actor_notes.json')) if os.path.exists('actor_notes.json') else {}
    auto = notes.setdefault('_auto', [])
    for npc in sys.argv[1:]:
        res = read(npc)
        if not res:
            print(npc, 'has no lines'); continue
        note, n = res
        notes[npc] = note
        if npc not in auto:
            auto.append(npc)
        print(f'{npc} ({n} lines): {note}')
    json.dump(notes, open('actor_notes.json', 'w'), indent=1, ensure_ascii=False)
