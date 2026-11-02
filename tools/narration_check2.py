"""Second, stricter look at the lines the narration check called narration (2026-10-16: of a sample of 30, only one or
two were -- self-naming speakers like "Brogg thanks you" and lore told by the giver were taken for narration).
  ../.venv/bin/python ../tools/narration_check2.py   -> narration_check2.jsonl (resumable)"""
import concurrent.futures as cf, csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import direct, render, bakeoff

SYSTEM = """You prepare World of Warcraft quest text for a voice-over. Almost every line is the quest giver speaking \
aloud to the hero. You will see one line that a first reader suspected was not speech. Most such suspicions are wrong. \
These are all SPEECH, said aloud by the quest giver:
- telling the hero history, lore or news, even with no "I" or "you" in it ("The spirits of the mountains are angered");
- talking about themselves in the third person, as some ogres, trolls and odd creatures do ("Grok thanks you. Grok \
is pleased.");
- quoting someone else, giving orders, describing a place or an enemy, or a short exclamation;
- a line with a stage direction in angle brackets: ignore the bracketed part completely and judge the rest.
It is NARRATION only when no character could be saying it: it describes what the hero does, sees or feels as it \
happens ("You are knocked off your feet as the box explodes"), or describes the quest giver from outside while they \
are not the one speaking ("The old woman stares at you blankly, tears in her eyes"). If in doubt, it is speech. \
Answer JSON: {"why": "<one short sentence>", "voice": "npc" or "narrator"}"""
SCHEMA = {'type': 'object', 'required': ['why', 'voice'], 'properties': {
    'why': {'type': 'string'}, 'voice': {'type': 'string', 'enum': ['npc', 'narrator']}}}
OUT = 'narration_check2.jsonl'

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    sp = {}
    for r in csv.DictReader(open('plan_v3.csv')): sp.setdefault((r['questId'], r['kind']), r)
    done = {(j['questId'], j['kind']) for j in map(json.loads, open(OUT))} if os.path.exists(OUT) else set()
    work = [j for j in map(json.loads, open('narration_check.jsonl')) if j['voice'] == 'narrator' and (j['questId'], j['kind']) not in done]
    print(len(work), 'to check again', flush=True)
    def one(j):
        r = sp[(j['questId'], j['kind'])]
        who = direct.who((r['npc_id'], r['npc_name'], r['race'], r['sex'])).split('\n')[0]
        text = render.variant_clean(direct.Q[j['questId']][direct.KINDS[j['kind']]] or '', '')
        try: a = bakeoff.llm(SYSTEM, f'Quest giver: {who}\nThe line:\n{text}', SCHEMA)
        except Exception as e: a = {'voice': 'error', 'why': str(e)[:80]}
        return dict(questId=j['questId'], kind=j['kind'], npc=j['npc'], **a)
    with open(OUT, 'a') as f, cf.ThreadPoolExecutor(4) as ex:
        for i, j in enumerate(ex.map(one, work), 1):
            f.write(json.dumps(j) + '\n'); f.flush()
