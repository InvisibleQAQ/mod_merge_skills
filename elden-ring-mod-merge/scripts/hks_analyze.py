"""Heuristic review aids for HKS (Havok Script / Lua) changes. They point at places a human or agent must read;
they do not prove or disprove a conflict.

  functions   top-level functions changed by A, by B, by both (text-merge conflicts are not the only risk:
              both sides may change different lines of the same function)
  overrides   functions an extra script (e.g. an addon .hks loaded at runtime) redefines or wraps, that the
              other side changed in c0000.hks: at runtime one side's code wraps the other's
  inputs      ACTION_ARM_* buttons read by each side's new code: a button used by both = control conflict
  variables   behavior variables both sides' new code sets (SetVariable) - e.g. both drive MoveSpeedIndex
  hardcoded   numeric state / event / variable IDs in a side's new code (makes that side the behavior KEEP side)
  obfuscated  string.char(...) density: decode before reading
"""
import re
from pathlib import Path

from text_merge import read_text

FUNC = re.compile(r'^(?:local\s+)?function\s+([\w.:]+)\s*\(', re.M)
DEF_ANY = re.compile(r'(?:^|\s)function\s+([\w.:]+)\s*\(|^\s*([\w.]+)\s*=\s*function\b|_G\[\s*["\'](\w+)["\']\s*\]\s*=', re.M)
INPUT = re.compile(r'\bACTION_ARM_[A-Z0-9_]+\b')
SETVAR = re.compile(r'\bSetVariable\(\s*"(\w+)"')
HARD = [re.compile(p) for p in (
    r'(MasterActiveState|ActiveState\w*|StateId\w*)"?\)?\s*[~=<>]=\s*\d+',
    r'local\s+\w*(?:Master|State)\w*\s*=\s*\d{2,}',
    r'\b(?:ExecEvent\w*|hkbFireEvent|SetVariable|GetVariable|hkbGetVariable)\(\s*\d+')]


def functions(text):
    """name -> normalised body (whitespace-insensitive) for top-level functions."""
    out, starts = {}, [(m.start(), m.group(1)) for m in FUNC.finditer(text)]
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        out.setdefault(name, re.sub(r'\s+', ' ', text[pos:end]).strip())
    return out


def changed_code(base_funcs, side_funcs):
    names = {n for n in side_funcs if base_funcs.get(n) != side_funcs[n]}
    return names, ' '.join(side_funcs[n] for n in names)


def analyze(base, a, b, extra_a=(), extra_b=()):
    """base/a/b: paths of the same .hks in each tree ('-' if missing); extra_*: .hks files only that side ships."""
    t = {k: (read_text(p)[0] if p not in (None, '-') else '') for k, p in (('base', base), ('a', a), ('b', b))}
    f = {k: functions(v) for k, v in t.items()}
    ch, code = {}, {}
    for side in ('a', 'b'):
        ch[side], code[side] = changed_code(f['base'], f[side])
    extra = {'a': [read_text(p)[0] for p in extra_a], 'b': [read_text(p)[0] for p in extra_b]}
    res = {'changed_by_a': sorted(ch['a']), 'changed_by_b': sorted(ch['b']), 'changed_by_both': sorted(ch['a'] & ch['b'])}
    overrides = {}
    for side, other in (('a', 'b'), ('b', 'a')):
        defined = set()
        for x in extra[side]:
            for m in DEF_ANY.finditer(x):
                defined.add(next(g for g in m.groups() if g))
        overrides[side] = sorted(defined & ch[other])
    res['runtime_overrides'] = overrides  # side -> functions its extra scripts redefine that the other side changed
    new_code = {s: code[s] + ' ' + ' '.join(extra[s]) for s in ('a', 'b')}
    inputs = {s: sorted(set(INPUT.findall(new_code[s]))) for s in ('a', 'b')}
    res['inputs'] = {'a': inputs['a'], 'b': inputs['b'], 'both': sorted(set(inputs['a']) & set(inputs['b']))}
    sv = {s: set(SETVAR.findall(new_code[s])) for s in ('a', 'b')}
    res['variables_set_by_both'] = sorted(sv['a'] & sv['b'])
    res['hardcoded'] = {s: sorted({m.group(0)[:80] for rx in HARD for m in rx.finditer(new_code[s])}) for s in ('a', 'b')}
    res['obfuscated'] = {s: new_code[s].count('string.char(') for s in ('a', 'b')}
    return res


def to_markdown(rel, res, names):
    a, b = names['a'], names['b']
    L = [f'### {rel}', '',
         f'- functions changed: {a} {len(res["changed_by_a"])}, {b} {len(res["changed_by_b"])}, both {len(res["changed_by_both"])}']
    if res['changed_by_both']:
        L.append(f'  - both changed: `{"`, `".join(res["changed_by_both"])}` (read each: different lines can still clash in behaviour)')
    for s, o in (('a', 'b'), ('b', 'a')):
        if res['runtime_overrides'][s]:
            L.append(f"- **{names[s]}'s extra scripts redefine/wrap functions {names[o]} changed** "
                     f"(at runtime {names[s]} runs first and may bypass {names[o]}): `" + '`, `'.join(res['runtime_overrides'][s]) + '`')
    if res['inputs']['both']:
        L.append(f'- **buttons read by both sides\' new code: {", ".join(res["inputs"]["both"])}** (check for control conflicts)')
    L.append(f'- buttons: {a} {res["inputs"]["a"]}; {b} {res["inputs"]["b"]}')
    if res['variables_set_by_both']:
        L.append(f'- behavior variables set by both: `{"`, `".join(res["variables_set_by_both"])}`')
    for s in ('a', 'b'):
        if res['hardcoded'][s]:
            L.append(f'- hard-coded IDs in {names[s]}\'s new code (prefer {names[s]} as behavior KEEP side): ' + '; '.join(f'`{x}`' for x in res['hardcoded'][s][:8]))
        if res['obfuscated'][s] > 20:
            L.append(f'- {names[s]}\'s new code looks obfuscated ({res["obfuscated"][s]} string.char calls): decode names before reviewing')
    return '\n'.join(L) + '\n'
