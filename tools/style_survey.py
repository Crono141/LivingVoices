"""Style survey (2026-10-12): which delivery tones do quest lines need that our twelve styles lack? Gemma describes,
in its own words, how a sample of lines should be performed. Run from data/:
  ../.venv/bin/python ../tools/style_survey.py [n=400]   -> style_survey.jsonl (resumable)"""
import csv, json, os, random, sys, urllib.request, concurrent.futures as cf, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import direct

SYSTEM = """You are a voice director for World of Warcraft quest dialogue. Read the whole quest and the speaker, then \
describe how ONE of its spoken lines should be performed by an actor. Describe it in your own words -- do not force \
it into a category. Consider what the speaker really wants, whether they are hiding something or deceiving the hero, \
their mood, their relationship to the hero, and how high the stakes are.

Answer with JSON:
{"tone": "<3-8 words: the delivery, e.g. 'sly, coaxing, angling for a bargain'>",
 "intensity": <1-10, how much energy and volume: 2 = murmured, 5 = normal conversation, 9 = shouting>,
 "subtext": "<what the speaker hides or really wants, or empty>",
 "closest_style": "<the closest of: STYLES, or 'none'>",
 "fits": <true if that style would really capture the delivery, false if it would miss something important>}"""

def ask(qid, kind):
    prompt, spoken = direct.context(qid)
    sysmsg = SYSTEM.replace('STYLES', ', '.join(direct.STYLES))
    body = {'model': direct.MODEL, 'temperature': 0.3, 'max_tokens': 400,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'survey', 'schema': {
                'type': 'object', 'required': ['tone', 'intensity', 'subtext', 'closest_style', 'fits'], 'properties': {
                    'tone': {'type': 'string'}, 'intensity': {'type': 'integer'}, 'subtext': {'type': 'string'},
                    'closest_style': {'type': 'string', 'enum': list(direct.STYLES) + ['none']}, 'fits': {'type': 'boolean'}}}}},
            'messages': [{'role': 'system', 'content': sysmsg},
                         {'role': 'user', 'content': prompt + f'\n\nDescribe the delivery of the [{kind}] line.'}]}
    r = urllib.request.Request(direct.LLM, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    return json.loads(json.load(urllib.request.urlopen(r, timeout=300))['choices'][0]['message']['content'])

if __name__ == '__main__':
    rows = [r for r in csv.DictReader(open('plan_v3.csv')) if not r['variant'] and r['npc_id'].isdigit()]
    if len(sys.argv) > 2 and sys.argv[1] == '--npcs':        # targeted pass: every line of the named NPCs
        want = sys.argv[2].split('|'); n = 10 ** 6
        sample = [r for r in rows if any(w.lower() in r['npc_name'].lower() for w in want)]
        by = {'targeted': sample}
    else:
        n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    if n < 10 ** 6:
        by = collections.defaultdict(list)
        for r in rows: by[(direct.style_group(r['race'], r['sex']) or 'other', r['kind'])].append(r)
        random.seed(20261012); sample = []
        per = max(1, n // len(by))
        for k in sorted(by): sample += random.sample(by[k], min(per, len(by[k])))
        random.shuffle(sample); sample = sample[:n]
    path = 'style_survey.jsonl'
    done = {(json.loads(l)['questId'], json.loads(l)['kind']) for l in open(path)} if os.path.exists(path) else set()
    todo = [r for r in sample if (r['questId'], r['kind']) not in done]
    print(len(sample), 'sampled across', len(by), 'race/sex x kind groups;', len(todo), 'to ask', flush=True)
    with open(path, 'a') as f, cf.ThreadPoolExecutor(3) as ex:
        futs = {ex.submit(ask, r['questId'], r['kind']): r for r in todo}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            r = futs[fu]
            try: a = fu.result()
            except Exception as e: a = {'error': str(e)[:200]}
            f.write(json.dumps({'questId': r['questId'], 'kind': r['kind'], 'npc': r['npc_name'], 'race': r['race'], 'sex': r['sex'],
                                'title': direct.Q[r['questId']]['title'], **a}) + '\n'); f.flush()
            if i % 50 == 0: print(i, '/', len(todo), flush=True)
    print('done')
