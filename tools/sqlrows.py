import re, sys
def rows(path, null='NULL'):
    """Yield tuples from INSERT INTO ... VALUES (...),(...); in an AzerothCore base dump.
    An unquoted SQL NULL yields `null` (default: the string 'NULL', for old callers; pass null='' or None)."""
    data = open(path, encoding='utf-8', errors='replace').read()
    for m in re.finditer(r'INSERT INTO `\w+`(?: \([^)]*\))? VALUES\s*', data):
        i = m.end()
        while i < len(data) and data[i] == '(':
            i += 1; row = []; cur = []; inq = False; quoted = False
            while True:
                c = data[i]
                if inq:
                    if c == '\\': cur.append({'n':'\n','r':'\r','t':'\t','0':'\0'}.get(data[i+1], data[i+1])); i += 2; continue
                    if c == "'":
                        if data[i+1] == "'": cur.append("'"); i += 2; continue
                        inq = False; i += 1; continue
                    cur.append(c); i += 1; continue
                if c == "'": inq = True; quoted = True; i += 1; continue
                if c in ',)':
                    v = ''.join(cur)
                    if not quoted and v.strip() == 'NULL': v = null
                    row.append(v); cur = []; quoted = False; i += 1
                    if c == ')': break
                    continue
                cur.append(c); i += 1
            yield [x.strip() if isinstance(x, str) and not x.startswith(' ') else x for x in row]
            while i < len(data) and data[i] in ',\n\r ': i += 1

# (2026-10-31) rows from the LIVE realm database for what the base SQL does not have: the realm's own quests and the
# event-only holiday givers (extract_live.py -> data/live_world.json). Every sqltable() yields them after the base rows,
# as dicts by column name with NULL as '' -- the same shape the base readers give.
import json as _json, os as _os
_LIVE = None
def live_rows(name):
    global _LIVE
    if _LIVE is None:
        _LIVE = _json.load(open('live_world.json')) if _os.path.exists('live_world.json') else {}
    return _LIVE.get(name, [])
