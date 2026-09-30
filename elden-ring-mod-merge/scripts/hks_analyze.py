"""Heuristic review aids for HKS (Havok Script = Lua 5.1) changes. They point at code a human or agent must read;
they do not prove or disprove a conflict.

Changes are measured line by line against the base. Each changed line belongs to the top-level function around
it (extents found with a small Lua lexer) or to a pseudo-function for top-level code: <preamble> before the first
function, <after NAME> between functions, <eof> after the last one. A second definition of a name in one file is
reported as "NAME (redefined)" - usually a wrapper installed over the original.
"New code" of a side = its changed lines in the shared script + every extra script only that side ships.

  functions   top-level functions changed by A, by B, by both
  overrides   functions an extra script (e.g. an addon .hks loaded at runtime) defines that the other side changed:
              at runtime one side's code wraps or replaces the other's
  inputs      ACTION_ARM_* buttons each side's new code reads, with the functions that read them
  variables   behavior variables both sides' new code sets (SetVariable)
  hardcoded   Master_SM state numbers: compared with MasterActiveState directly or through a local copy, or stored
              in a *Master* local; other numeric behavior IDs as evidence text
  obfuscated  string.char(...) count: decode before reading
"""
import bisect
import re
from collections import defaultdict
from pathlib import Path

from text_merge import line_opcodes, read_text

# Comments and strings (skipped), then names; block keywords decide function extents.
TOKEN = re.compile(r'--\[(=*)\[.*?\]\1\]|--[^\n]*|\[(=*)\[.*?\]\2\]|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|[A-Za-z_]\w*', re.S)
OPEN, CLOSE = {'function', 'if', 'do', 'repeat'}, {'end', 'until'}
NAMED = re.compile(r'\s*(?:local\s+)?function\s+([\w.:]+)|\s*(?:local\s+)?([\w.:]+)\s*=\s*function\b')
FUNC = re.compile(r'^(?:local\s+)?function\s+([\w.:]+)\s*\(', re.M)
DEF_ANY = re.compile(r'(?:^|\s)function\s+([\w.:]+)\s*\(|^\s*([\w.]+)\s*=\s*function\b|_G\[\s*["\'](\w+)["\']\s*\]\s*=', re.M)
INPUT = re.compile(r'\bACTION_ARM_[A-Z0-9_]+\b')
SETVAR = re.compile(r'\bSetVariable\(\s*"(\w+)"')
MASTER_DIRECT = re.compile(r'MasterActiveState"?\s*\)?\s*[~=<>]=\s*(\d+)|\b(\d+)\s*[~=<>]=\s*(?:hkb)?GetVariable\(\s*"MasterActiveState"')
MASTER_ALIAS = re.compile(r'\blocal\s+(\w+)\s*=\s*(?:hkb)?GetVariable\(\s*"MasterActiveState"\s*\)')
MASTER_LOCAL = re.compile(r'\blocal\s+(\w*Master\w*)\s*=\s*(\d+)\b')
OTHER_HARD = [re.compile(p) for p in (
    r'\b(?!MasterActiveState)\w*(?:ActiveState|StateId)\w*"?\)?\s*[~=<>]=\s*\d+',
    r'\b(?:ExecEvent\w*|hkbFireEvent|SetVariable|GetVariable|hkbGetVariable)\(\s*\d+')]


def text_of(path):
    return read_text(path)[0] if path not in (None, '-') else ''


def lines_of(text):
    return text[:-1].split('\n') if text.endswith('\n') else (text.split('\n') if text else [])


def spans(text):
    """Top-level chunks [(name, first line, last line)] (1-based, inclusive) covering every line of a script."""
    lines = lines_of(text)
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    funcs, depth, cur = [], 0, None
    for m in TOKEN.finditer(text):
        w = m.group(0)
        if w[0] in '-"\'[':
            continue
        if w in OPEN:
            if depth == 0 and w == 'function':
                ln = bisect.bisect_right(starts, m.start())
                nm = NAMED.match(lines[ln - 1])
                cur = (nm.group(1) or nm.group(2)) if nm else None, ln
            depth += 1
        elif w in CLOSE:
            depth -= 1
            if depth < 0:
                return _fallback(text, lines)
            if depth == 0 and cur is not None:
                if cur[0]:
                    funcs.append((cur[0], cur[1], bisect.bisect_right(starts, m.start())))
                cur = None
    return _cover(funcs, len(lines)) if depth == 0 else _fallback(text, lines)


def _fallback(text, lines):
    """Unbalanced block structure (unknown syntax): a function then runs until the next one starts."""
    st = [(m.group(1), text.count('\n', 0, m.start()) + 1) for m in FUNC.finditer(text)]
    return _cover([(n, s, (st[i + 1][1] - 1) if i + 1 < len(st) else len(lines)) for i, (n, s) in enumerate(st)], len(lines))


def _cover(funcs, n):
    out, seen, prev_end, prev = [], defaultdict(int), 0, None
    for name, first, last in funcs:
        if first > prev_end + 1:
            out.append(('<preamble>' if prev is None else f'<after {prev}>', prev_end + 1, first - 1))
        seen[name] += 1
        label = name if seen[name] == 1 else f'{name} (redefined)' if seen[name] == 2 else f'{name} (redefined #{seen[name] - 1})'
        out.append((label, first, last))
        prev_end, prev = last, label
    if prev_end < n:
        out.append(('<eof>' if prev else '<preamble>', prev_end + 1, n))
    return out


def span_at(sp, line):
    return sp[max(0, bisect.bisect_right([s[1] for s in sp], line) - 1)][0] if sp else '<preamble>'


def changes(base_text, side_text):
    """(names of changed chunks, [(chunk, line)] of added or modified lines) of a side against the base."""
    bl, sl = lines_of(base_text), lines_of(side_text)
    bsp, ssp = spans(base_text), spans(side_text)
    names, new = set(), []
    for _, i1, i2, j1, j2 in line_opcodes(bl, sl):
        if j2 == j1:
            names.add(span_at(bsp, i1 + 1))
        for j in range(j1, j2):
            names.add(span_at(ssp, j + 1))
            new.append((span_at(ssp, j + 1), sl[j]))
    return names, new


def whole(path):
    """[(file:chunk, line)] for every line of a script only one side ships."""
    t = text_of(path)
    sp, name = spans(t), Path(path).name
    return [(f'{name}:{span_at(sp, i + 1)}', line) for i, line in enumerate(lines_of(t))]


def new_code(base, side):
    """Text of a side's new lines in one script (the whole file when the base has none)."""
    if base in (None, '-'):
        return text_of(side)
    return '\n'.join(line for _, line in changes(text_of(base), text_of(side))[1])


def master_state_ids(text):
    """Master_SM state numbers hard-coded in a script: {number: [evidence]}."""
    out = defaultdict(list)

    def add(n, ev):
        if ev.strip()[:80] not in out[int(n)]:
            out[int(n)].append(ev.strip()[:80])
    for m in MASTER_DIRECT.finditer(text):
        add(m.group(1) or m.group(2), m.group(0))
    for alias in set(MASTER_ALIAS.findall(text)):
        for m in re.finditer(rf'\b{alias}\s*[~=<>]=\s*(\d+)|\b(\d+)\s*[~=<>]=\s*{alias}\b', text):
            add(m.group(1) or m.group(2), m.group(0))
    for m in MASTER_LOCAL.finditer(text):
        add(m.group(2), m.group(0))
    return dict(out)


def bare(name):
    return re.sub(r' \(redefined.*\)$', '', name)


def analyze(base, a, b, extra_a=(), extra_b=()):
    """base/a/b: paths of the same .hks in each tree ('-' if missing); extra_*: .hks files only that side ships."""
    t = {k: text_of(p) for k, p in (('base', base), ('a', a), ('b', b))}
    ch, code, defined = {}, {}, {}
    for side, extras in (('a', extra_a), ('b', extra_b)):
        ch[side], code[side] = changes(t['base'], t[side])
        defined[side] = set()
        for p in extras:
            code[side] += whole(p)
            defined[side] |= {bare(next(g for g in m.groups() if g)) for m in DEF_ANY.finditer(text_of(p))}
    res = {'changed_by_a': sorted(ch['a']), 'changed_by_b': sorted(ch['b']), 'changed_by_both': sorted(ch['a'] & ch['b'])}
    res['runtime_overrides'] = {s: sorted(defined[s] & {bare(n) for n in ch[o]}) for s, o in (('a', 'b'), ('b', 'a'))}
    for key, rx in (('inputs', INPUT), ('variables', SETVAR)):
        found = {}
        for s in ('a', 'b'):
            found[s] = defaultdict(set)
            for where, line in code[s]:
                for x in rx.findall(line):
                    found[s][x].add(where)
        res[key] = {s: {x: sorted(w) for x, w in sorted(found[s].items())} for s in ('a', 'b')}
        res[key]['both'] = sorted(set(found['a']) & set(found['b']))
    joined = {s: '\n'.join(line for _, line in code[s]) for s in ('a', 'b')}
    res['master_states'] = {s: master_state_ids(joined[s]) for s in ('a', 'b')}
    res['hardcoded_other'] = {s: sorted({m.group(0)[:80] for rx in OTHER_HARD for m in rx.finditer(joined[s])}) for s in ('a', 'b')}
    res['obfuscated'] = {s: joined[s].count('string.char(') for s in ('a', 'b')}
    return res


def _where(locs, n=4):
    return ', '.join(locs[:n]) + (f' +{len(locs) - n}' if len(locs) > n else '')


def to_markdown(rel, res, names):
    a, b = names['a'], names['b']
    L = [f'### {rel}', '',
         f'- chunks changed (line diff against the base): {a} {len(res["changed_by_a"])}, {b} {len(res["changed_by_b"])}, '
         f'both {len(res["changed_by_both"])}']
    for s in ('a', 'b'):
        if 0 < len(res[f'changed_by_{s}']) <= 12:
            L.append(f'  - {names[s]}: `' + '`, `'.join(res[f'changed_by_{s}']) + '`')
    if res['changed_by_both']:
        L.append(f'  - both changed: `{"`, `".join(res["changed_by_both"])}` (read each: different lines can still clash in behaviour)')
    for s, o in (('a', 'b'), ('b', 'a')):
        if res['runtime_overrides'][s]:
            L.append(f"- **{names[s]}'s extra scripts redefine/wrap functions {names[o]} changed** "
                     f"(at runtime {names[s]} runs first and may bypass {names[o]}): `" + '`, `'.join(res['runtime_overrides'][s]) + '`')
    for key, title in (('inputs', 'buttons read by both sides\' new code (check who reacts in which situation)'),
                       ('variables', 'behavior variables set by both sides\' new code (last writer each frame wins)')):
        if res[key]['both']:
            L.append(f'- **{title}:**')
            L += [f'  - `{x}`: {a} in {_where(res[key]["a"][x])}; {b} in {_where(res[key]["b"][x])}' for x in res[key]['both']]
    L.append(f'- buttons: {a} {sorted(res["inputs"]["a"])}; {b} {sorted(res["inputs"]["b"])}')
    for s in ('a', 'b'):
        ms = res['master_states'][s]
        if ms:
            L.append(f'- **hard-coded Master_SM states in {names[s]}\'s new code: {", ".join(map(str, sorted(ms)))}** '
                     f'({names[s]} must be the behavior KEEP side): ' + '; '.join(f'`{ev[0]}`' for _, ev in sorted(ms.items())))
        if res['hardcoded_other'][s]:
            L.append(f'- other numeric behavior IDs in {names[s]}\'s new code: ' + '; '.join(f'`{x}`' for x in res['hardcoded_other'][s][:8]))
        if res['obfuscated'][s] > 20:
            L.append(f'- {names[s]}\'s new code looks obfuscated ({res["obfuscated"][s]} string.char calls): decode names before reviewing')
    return '\n'.join(L) + '\n'
