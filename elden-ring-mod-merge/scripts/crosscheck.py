"""Cross-file consistency of the merged mod: references one file makes into another. Per-file verification cannot
see them - take, exclude, drop_entries, resolve or a hook can leave a reference dangling while every file on its
own is "correct".

usage: python crosscheck.py --workspace W        (build.py runs it after the hooks)

The merged mod is staging/ over the base mod (over the game files extracted to W/vanilla/). Every finding is
compared with each mod alone (the mod over the base) and with the base:
  names     names appended to action/*nameid.txt exist in the behavior graph, and names the graph gained exist
            in the tables (events, variables, states)
  hks       event / variable / node names the merged scripts pass to the engine (string.char(...) decoded first)
            that the base scripts do not use resolve in the graph and the nameid tables; every new decoded literal
            is some behavior name (obfuscated code passes names by value, e.g. to EvasionCommonFunction)
  speffect  SpEffect IDs TAE events reference exist in regulation.bin
  fxr       FFX IDs TAE events newly reference exist in an effect pack (shipped, base, or W/vanilla/sfx), and no
            FXR ID is in two packs with different content
  states    Master_SM state numbers the scripts hard-code name the same state in the merged graph
Levels: error = introduced by the merge (the same reference works in the mod alone): build.py stops;
        warn  = broken in a mod or the base alone already, or a provider that cannot be found;
        info  = worth knowing, e.g. references that now use the other mod's copy of an effect.
Writes reports/CROSSCHECK.md and reports/CROSSCHECK.json; exit code 1 on errors.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__
from hks_analyze import master_state_ids  # noqa: E402
from kit import Workspace, load_json, save_json, walk  # noqa: E402
from text_merge import read_nameid, read_text  # noqa: E402

TREES = ('base', 'a', 'b', 'x')  # x = the merged mod
KINDS = ('event', 'variable', 'state')
TAE_FILE = re.compile(r'(^|/)c\d{4}\.anibnd\.dcx$')
PACK = re.compile(r'^sfx/.+\.ffxbnd\.dcx$')
FXR_ENTRY = re.compile(r'f(\d{9})\.fxr$')
STRING_CHAR = re.compile(r'string\.char\(\s*([\d\s,]+)\)')
NAME_API = re.compile(r'\b(ExecEvent\w*|hkbFireEvent|(?:hkb)?[SG]etVariable|IsNodeActive)\s*\(\s*"([^"]+)"\s*(\.\.)?')
EXEC_EVENTS = re.compile(r'\bExecEvents\s*\(([^)]*)\)')
ANIM = re.compile(r'\{"kind":"anim","entry":"([^"]+)","taeId":-?\d+,"id":(-?\d+)')
TAE_SP = re.compile(r'"([^"]*SpEffect[^"]*)":"(-?\d+)"')
TAE_FX = re.compile(r'"(FFX ID[^"]*)":"(-?\d+)"')


class Tree:
    """Effective file set of the base, each mod alone, and the merged mod: lower-case rel -> path."""

    def __init__(self, ws, inv):
        van = walk(ws.p('vanilla'))[0] if ws.p('vanilla').exists() else {}
        base = {**{k: v[1] for k, v in van.items()},
                **({k: v[1] for k, v in walk(inv['roots']['base'])[0].items()} if 'base' in inv['roots'] else {})}
        own = {s: {k: v[1] for k, v in walk(inv['roots'][s])[0].items()} for s in ('a', 'b')}
        own['x'] = {k: v[1] for k, v in walk(ws.p('staging'))[0].items()}
        self.files = {'base': base, **{t: {**base, **own[t]} for t in ('a', 'b', 'x')}}
        self.own = own

    def path(self, tree, rel):
        return self.files[tree].get(rel.lower())

    def match(self, tree, rx):
        return {k: p for k, p in self.files[tree].items() if rx.search(k)}


class Report:
    def __init__(self):
        self.findings, self.numbers = [], []

    def add(self, level, check, text):
        self.findings.append({'level': level, 'check': check, 'text': text})

    def count(self, level):
        return sum(f['level'] == level for f in self.findings)


def behavior(ws, path):
    """Names and Master_SM states of a behavior binder (streamed from the cached dump)."""
    prefix = ws.dump('beh', path)
    t = json.loads(Path(str(prefix) + '.tables.json').read_text(encoding='utf-8'))
    nodes, states, info, master_refs = set(), set(), {}, []
    with open(str(prefix) + '.nodes.jsonl', encoding='utf-8') as fh:
        for line in fh:
            o = json.loads(line)
            f = o.get('fields') if isinstance(o.get('fields'), dict) else {}
            if isinstance(f.get('m_name'), str):
                nodes.add(f['m_name'])
            if o['type'] == 'hkbStateMachine.StateInfo':
                states.add(f.get('m_name'))
                info[o['key']] = (f.get('m_stateId'), f.get('m_name'))
            if o['key'] == 'hkbStateMachine:Master_SM':
                master_refs = f.get('m_states') or []
    return {'event': set(t.get('eventNames') or []), 'variable': set(t.get('variableNames') or []), 'state': states,
            'node': nodes, 'master': dict(info[r[1:]] for r in master_refs if r[1:] in info)}


def hks_refs(text):
    """(kind, name) of every literal behavior name the script passes to the engine ('name*' = prefix + variable),
    plus ('decoded', s) for every string.char(...) literal: obfuscated literals are names passed around by value."""
    decoded = set()

    def decode(m):
        s = ''.join(chr(int(x)) for x in m.group(1).split(',') if x.strip())
        decoded.add(('decoded', s))
        return '"' + s + '"'
    text = STRING_CHAR.sub(decode, text)
    out = set()
    for m in NAME_API.finditer(text):
        kind = 'variable' if 'Variable' in m.group(1) else 'node' if m.group(1) == 'IsNodeActive' else 'event'
        out.add((kind, m.group(2) + ('*' if m.group(3) else '')))
    for m in EXEC_EVENTS.finditer(text):
        out |= {('event', n) for n in re.findall(r'"([^"]+)"', m.group(1))}
    return out | decoded


def tae_refs(ws, path):
    """{'sp': {id: {(tae, anim)}}, 'fx': {...}} over every animation of a TAE container."""
    out = {'sp': defaultdict(set), 'fx': defaultdict(set)}
    with open(ws.dump('taet', path), encoding='utf-8') as fh:
        for line in fh:
            m = ANIM.match(line)
            if not m:
                continue
            loc = (m.group(1).lower(), int(m.group(2)))
            for key, rx in (('sp', TAE_SP), ('fx', TAE_FX)):
                for _, v in rx.findall(line):
                    if int(v) > 0:
                        out[key][int(v)].add(loc)
    return out


def check_names(R, G, N, names):
    for kind in KINDS:
        base_n, x_n = set(N['base'][kind]), N['x'][kind]
        added, x_set = [n for n in x_n if n not in base_n], set(x_n)
        grown = sorted(n for n in G['x'][kind] if n not in G['base'][kind])
        for n in added:
            if n not in G['x'][kind]:
                srcs = [s for s in 'ab' if n in N[s][kind] and n not in base_n]
                ok = [names[s] for s in srcs if n in G[s][kind]]
                R.add('error' if ok or not srcs else 'warn', 'names',
                      f'{kind} "{n}" added to the nameid table but missing in the merged behavior graph'
                      + (f' (present in {", ".join(ok)} alone)' if ok else f' ({", ".join(names[s] for s in srcs)} alone: missing too)' if srcs else ''))
        for n in grown:
            if n not in x_set:
                srcs = [s for s in 'ab' if n in G[s][kind]]
                ok = [names[s] for s in srcs if n in N[s][kind]]
                R.add('error' if ok or not srcs else 'warn', 'names',
                      f'{kind} "{n}" new in the merged behavior graph but missing in the nameid table'
                      + (f' (present in {", ".join(ok)} alone)' if ok else ''))
        R.numbers.append(f'names: {kind} +{len(added)} in the nameid table, +{len(grown)} in the behavior graph (against the base)')


def resolves(kind, name, g, n):
    if kind == 'node':
        return name in g['node']
    if kind == 'decoded':  # any behavior name will do; bone or file names show up as warnings to read
        return name in g['event'] or name in g['variable'] or name in g['node']
    return name in g[kind] and name in n[kind]


def check_hks(R, T, G, N, names):
    cache = {}

    def refs(tree):
        out = set()
        for p in T.match(tree, re.compile(r'\.hks$')).values():
            if p not in cache:
                cache[p] = hks_refs(read_text(p)[0])
            out |= cache[p]
        return out
    ref = {t: refs(t) for t in TREES}
    new = sorted(ref['x'] - ref['base'])
    prefixed = [r for r in new if r[1].endswith('*')]
    for kind, name in new:
        if name.endswith('*') or resolves(kind, name, G['x'], N['x']):
            continue
        srcs = [s for s in 'ab' if (kind, name) in ref[s]]
        ok = [names[s] for s in srcs if resolves(kind, name, G[s], N[s])]
        where = f'used by {", ".join(names[s] for s in srcs)}' if srcs else 'used only by the merged scripts (a hook?)'
        what = 'string.char literal' if kind == 'decoded' else kind
        R.add('warn' if srcs and not ok else 'error', 'hks',
              f'{what} "{name}" {where} is no {"behavior name" if kind == "decoded" else kind} in the merged mod'
              + (f' but does in {", ".join(ok)} alone' if ok else ' (nor in the mod alone)' if srcs else ''))
    api = [r for r in new if r[0] != 'decoded']
    R.numbers.append(f'hks: {len(ref["x"])} literal names in the merged scripts; not in the base scripts: {len(api)} passed to the '
                     f'engine ({len(prefixed)} built from a prefix, not checked), {len(new) - len(api)} decoded string.char literals')


def check_speffects(ws, R, T, names):
    rels = [k for k in T.own['x'] if TAE_FILE.search(k)]
    reg = {t: T.path(t, 'regulation.bin') for t in TREES}
    if not rels or not all(reg.values()):
        R.numbers.append('speffect: skipped (no merged TAE container or no regulation.bin)')
        return {}
    refs = {t: {'sp': defaultdict(set), 'fx': defaultdict(set)} for t in TREES}
    for rel in rels:
        for t in TREES:
            if T.path(t, rel):
                got = tae_refs(ws, T.path(t, rel))
                for k in ('sp', 'fx'):
                    for i, locs in got[k].items():
                        refs[t][k][i] |= {(rel,) + loc for loc in locs}
    have = {}
    for t in TREES:
        tsv = Path(ws.dump('param', reg[t])) / 'SpEffectParam.tsv'
        have[t] = {int(x.split('\t', 1)[0]) for x in tsv.read_text(encoding='utf-8').splitlines()[1:] if x}
    sp = {t: refs[t]['sp'] for t in TREES}
    miss = {t: {i for i in sp[t] if i not in have[t]} for t in TREES}
    for i in sorted(miss['x']):
        new = sp['x'][i] - sp['base'][i]
        srcs = [s for s in 'ab' if sp[s][i] & new]
        owners = [names[s] for s in 'ab' if sp[s][i] and i in have[s]]
        if owners:
            R.add('error', 'speffect', f'SpEffect {i}: referenced by TAE events, in the regulation of {", ".join(owners)}, '
                                       'but not in the merged regulation.bin')
        elif i not in miss['base']:
            R.add('warn', 'speffect', f'SpEffect {i}: the base has it, the merged regulation.bin and the mods do not')
        elif new:
            R.add('warn', 'speffect', f'SpEffect {i}: missing in every regulation.bin; {len(new)} new TAE reference(s) from '
                                      f'{", ".join(names[s] for s in srcs) or "?"} (the base has {len(sp["base"][i])})')
    R.numbers.append(f'speffect: {len(sp["x"])} SpEffect IDs referenced by TAE events, {len(miss["x"])} missing in the merged '
                     f'regulation.bin ({len(miss["x"] & miss["base"])} missing in the base too)')
    return {t: refs[t]['fx'] for t in TREES}


def check_fxr(ws, R, T, fx, names, has_vanilla):
    packs = {}
    for t in TREES:
        packs[t] = defaultdict(dict)
        for rel, p in T.match(t, PACK).items():
            rows = [r.split('\t') for r in ws.dump('bnd', p).read_text(encoding='utf-8').splitlines()[2:]]
            for r in rows:
                m = FXR_ENTRY.search(r[1].lower()) if len(r) >= 5 else None
                if m:
                    packs[t][int(m.group(1))][rel] = r[4]
    dup = {t: {i for i, where in packs[t].items() if len(set(where.values())) > 1} for t in TREES}
    for i in sorted(dup['x'] - dup['base']):
        alone = [names[s] for s in 'ab' if i in dup[s]]
        R.add('warn' if alone else 'error', 'fxr', f'FXR {i} is in {", ".join(sorted(packs["x"][i]))} with different content '
              '(which copy the game uses is unknown)' + (f'; {", ".join(alone)} alone: same' if alone else ''))
    if not fx:
        return
    new_ids = {i: fx['x'][i] - fx['base'][i] for i in fx['x']}
    new_ids = {i: locs for i, locs in new_ids.items() if locs}
    looked = 'shipped and base packs' + (' and W/vanilla/sfx' if has_vanilla else '')
    for i, locs in sorted(new_ids.items()):
        srcs = [s for s in 'ab' if fx[s][i] & locs]
        prov = packs['x'].get(i, {})
        if not prov:
            owners = [names[s] for s in srcs if packs[s].get(i)]
            R.add('error' if owners else 'warn', 'fxr',
                  f'FXR {i}: {len(locs)} new TAE reference(s) from {", ".join(names[s] for s in srcs) or "?"}; no pack of the merged '
                  f'mod has it' + (f', {", ".join(owners)} alone does' if owners else f' (looked in {looked})'
                                   + ('; the base TAE uses it too' if fx['base'].get(i) else '')))
            continue
        for s in srcs:
            own = packs[s].get(i, {})
            if own and set(own.values()) != set(prov.values()):
                R.add('info', 'fxr', f'FXR {i}: {names[s]}\'s {len(fx[s][i] & locs)} new TAE reference(s) now use the copy in '
                                     f'{", ".join(sorted(prov))}, not {names[s]}\'s own copy in {", ".join(sorted(own))}')
    R.numbers.append(f'fxr: {len(new_ids)} FFX IDs gain TAE references, {sum(1 for i in new_ids if not fx["base"].get(i))} of them '
                     f'unused by the base TAE; {sum(1 for i in new_ids if packs["x"].get(i))} found in a pack')


def check_states(R, T, G, names):
    seen = defaultdict(set)
    for t in ('base', 'a', 'b'):
        text = '\n'.join(read_text(p)[0] for p in T.match(t, re.compile(r'\.hks$')).values())
        for n, ev in master_state_ids(text).items():
            seen[(n, G[t]['master'].get(n), G['x']['master'].get(n), ev[0])].add(names[t])
    ok = {}
    for (n, own, merged, ev), who in sorted(seen.items(), key=lambda x: x[0][0]):
        if own is None:
            R.add('warn', 'states', f'{", ".join(sorted(who))} compare(s) Master_SM with {n} (`{ev}`), which is no Master_SM state in '
                                    'their own graph')
        elif merged != own:
            R.add('error', 'states', f'{", ".join(sorted(who))} hard-code(s) Master_SM state {n} = {own} (`{ev}`); in the merged '
                                     f'graph {n} is {merged}')
        else:
            ok[n] = own
    R.numbers.append('states: hard-coded Master_SM numbers that still name the same state: '
                     + (', '.join(f'{n} {s}' for n, s in sorted(ok.items())) or 'none'))


def run(ws):
    inv, plan = load_json(ws.p('inventory.json')), ws.plan
    names = {'base': 'the base', 'a': plan['a']['name'], 'b': plan['b']['name'], 'x': 'the merged mod'}
    T, R = Tree(ws, inv), Report()
    beh = {t: T.path(t, 'chr/c0000.behbnd.dcx') for t in TREES}
    if all(beh.values()):
        G = {t: behavior(ws, beh[t]) for t in TREES}
        N = {t: {k: (read_nameid(T.path(t, f'action/{k}nameid.txt')) if T.path(t, f'action/{k}nameid.txt') else [])
                 for k in KINDS} for t in TREES}
        check_names(R, G, N, names)
        check_hks(R, T, G, N, names)
        check_states(R, T, G, names)
    else:
        R.numbers.append('names / hks / states: skipped (no chr/c0000.behbnd.dcx in the base, a mod or the game extract)')
    fx = check_speffects(ws, R, T, names)
    check_fxr(ws, R, T, fx, names, ws.p('vanilla', 'sfx').exists())
    counts = {lv: R.count(lv) for lv in ('error', 'warn', 'info')}
    save_json(ws.p('reports', 'CROSSCHECK.json'), {**counts, 'findings': R.findings, 'numbers': R.numbers})
    L = ['# Cross-file checks', '', f'{counts["error"]} error(s) (introduced by the merge), {counts["warn"]} warning(s) '
         f'(broken in a mod or the base already, or unknown), {counts["info"]} info', '']
    L += ['| level | check | finding |', '|---|---|---|'] + [f'| {f["level"]} | {f["check"]} | {f["text"]} |' for f in
                                                           sorted(R.findings, key=lambda f: ('error', 'warn', 'info').index(f['level']))]
    L += ['', '## Numbers', ''] + [f'- {x}' for x in R.numbers]
    ws.p('reports', 'CROSSCHECK.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f'cross-file checks: {counts["error"]} error(s), {counts["warn"]} warning(s), {counts["info"]} info; see reports/CROSSCHECK.md')
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    sys.exit(1 if run(Workspace(ap.parse_args().workspace))['error'] else 0)


if __name__ == '__main__':
    main()
