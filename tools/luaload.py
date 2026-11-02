import re
TOK = re.compile(r'\s*(?:(\{)|(\})|(=)|(,)|\["((?:[^"\\]|\\.)*)"\]|\[(-?\d+)\]|"((?:[^"\\]|\\.)*)"|(-?[\d.]+(?:e-?\d+)?)|(true|false|nil))', re.S)
ESC = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\', "'": "'"}

def unesc(s):
    return re.sub(r'\\(.)', lambda m: ESC.get(m.group(1), m.group(1)), s)

def load_table(path):
    """Parse the first `X.Y = { ... }` Lua table in a VoiceOver generated file."""
    src = open(path, encoding='utf-8').read()
    i = src.index('= {') + 2
    toks = []
    pos = i
    while pos < len(src):
        m = TOK.match(src, pos)
        if not m:
            if src[pos:].strip() == '':
                break
            raise ValueError(src[pos:pos + 80])
        pos = m.end()
        toks.append(m)
    it = iter(toks)
    return _parse(it, next(it))

def _depth_zero(toks, _c=[0]):
    m = toks[-1]
    if m.group(1): _c[0] += 1
    elif m.group(2): _c[0] -= 1
    if _c[0] == 0:
        _c[0] = 0
        return True
    return False

def _val(m, it):
    if m.group(1): return _parse(it, m)
    if m.group(7) is not None: return unesc(m.group(7))
    if m.group(8) is not None:
        v = m.group(8); return float(v) if ('.' in v or 'e' in v) else int(v)
    return {'true': True, 'false': False, 'nil': None}[m.group(9)]

def _parse(it, open_m):
    d = {}; n = 1
    for m in it:
        if m.group(2): return d
        if m.group(4): continue
        if m.group(5) is not None or m.group(6) is not None:
            k = unesc(m.group(5)) if m.group(5) is not None else int(m.group(6))
            eq = next(it); assert eq.group(3), eq.group(0)
            d[k] = _val(next(it), it)
        else:
            d[n] = _val(m, it); n += 1
    return d
