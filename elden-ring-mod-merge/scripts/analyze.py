"""Dry-runs every planned merge and collects review leads. Writes analysis/SUMMARY.md plus per-file reports.

usage: python analyze.py --workspace W

Nothing is written outside the workspace. Run after inventory.py (and again after editing plan.json).
Sections of SUMMARY.md:
  merge dry-runs   per file: would the merge succeed with the current plan, which items conflict
  review leads     HKS heuristics, effect-ID collisions across packs, DLLs/natives, installer files to read
  write-back       roundtrip checks proving the libraries can rewrite each file type involved
"""
import argparse
import re
from collections import defaultdict
from pathlib import Path

import hks_analyze
from kit import Workspace, base_path, load_json, save_json
from text_merge import merge3, read_nameid


def safe(rel):
    return re.sub(r'[\\/:]', '__', rel)


def ensure_vanilla(ws, plan, inv):
    """Extracts vanilla copies for plan entries whose base_source is 'vanilla' (and all ffxbnd for the FX check)."""
    kit = ws.kit
    want = [rel for rel, spec in plan['files'].items() if spec.get('base_source') == 'vanilla'
            and not ws.p('vanilla', *rel.lower().split('/')).exists()]
    if want:
        ws.ermerge('vanilla-extract', kit['game'], ws.p('vanilla'), *['/' + r.lower() for r in want])


def dry_run(ws, rel, spec, e, names):
    kit, strat = ws.kit, spec['strategy']
    base = base_path(ws, rel, spec, e)
    rep = ws.p('analysis', safe(rel) + '.json')
    res_file = ws.p('analysis', safe(rel) + '.resolve.json')
    save_json(res_file, spec.get('resolve', {}))
    dummy = ws.p('analysis', 'dry.out')
    common = ['--report', rep, '--resolve', res_file, '--dry-run']
    if strat == 'regulation':
        args = ['reg-merge', base, e['a'], e['b'], kit['defs'], dummy, '--primary', spec.get('primary', 'a'),
                '--label-a', spec.get('label_a', names['a']), '--label-b', spec.get('label_b', names['b'])]
    elif strat in ('tae', 'bnd'):
        args = [f'{strat}-merge', base, e['a'], e['b'], dummy, '--primary', spec.get('primary', 'a')]
    elif strat == 'behavior':
        lines = []
        for keep in ('a', 'b'):
            move = 'b' if keep == 'a' else 'a'
            r = ws.p('analysis', f'{safe(rel)}.keep_{keep}.json')
            code, out = ws.ermerge('beh-merge', base, e[keep], e[move], dummy, '--report', r, '--dry-run', check=False, quiet=True)
            j = load_json(r, {})
            st = j.get('stats', {}).get('behavior', {})
            lines.append(f'  - KEEP {names[keep]} / MOVE {names[move]}: {"OK" if code == 0 else "CONFLICTS"}; '
                         f'{len(j.get("conflicts", []))} conflicts, MOVE adds {st.get("moveNewObjects")} objects and changes '
                         f'{st.get("moveModifiedObjects")}; stateId remaps {st.get("stateIdMaps")}; wraps {len(st.get("wraps", []))}; '
                         f'unmapped index values {len(st.get("suspicious", []))}')
        return 'dry-run both directions (pick KEEP = the side with hard-coded behavior IDs, else the one with more changes):\n' + '\n'.join(lines)
    elif strat == 'nameid':
        if base == '-':
            return 'no base table: extract the vanilla one (base_source: vanilla)'
        c, na, nb = read_nameid(base), read_nameid(e['a']), read_nameid(e['b'])
        bad = [names[s] for s, n in (('a', na), ('b', nb)) if n[:len(c)] != c]
        return (f'base {len(c)}, {names["a"]} appends {len(na) - len(c)}, {names["b"]} appends {len(nb) - len(c)}'
                + (f'; **{", ".join(bad)} changed existing entries -> manual merge**' if bad else '; append-only, OK'))
    elif strat == 'text3':
        n = merge3(kit['git'], base, e['a'], e['b'], None)
        return f'git merge-file: {n} conflict hunk(s)' + (' -> resolve by hand (strategy manual)' if n else ', clean')
    elif strat in ('take', 'manual'):
        side = spec.get('side')
        return f'take {names.get(side, "?")}' if side else '**needs a decision: which side to take (or merge by hand)**'
    else:
        return f'unknown strategy {strat}'
    code, out = ws.ermerge(*args, *common, check=False, quiet=True)
    j = load_json(rep, {})
    confl = j.get('conflicts', [])
    s = f'{"OK" if code == 0 else "CONFLICTS" if code == 3 else "ERROR"}; stats {j.get("stats", {})}'
    if code not in (0, 3):
        s += '\n  ```\n  ' + out.strip()[-800:] + '\n  ```'
    for c in confl[:30]:
        s += f'\n  - conflict `{c["key"]}`: {c["what"]}' + (f' (A={c.get("a")}, B={c.get("b")}, base={c.get("base")})' if c.get('a') is not None else '')
    if len(confl) > 30:
        s += f'\n  - ... {len(confl) - 30} more in {rep.name}'
    return s


def bnd_entries(ws, path, tag):
    tsv = ws.p('dumps', 'bnd', tag + '.tsv')
    ws.ermerge('bnd-list', path, tsv, quiet=True)
    rows = tsv.read_text(encoding='utf-8').splitlines()[2:]
    return {c[1].lower(): c[4] for c in (r.split('\t') for r in rows) if len(c) >= 5}


def fxr_collisions(ws, inv, names):
    """FXR IDs that both mods add or change in any .ffxbnd with different content (which one the game uses is unknown)."""
    added = {'a': defaultdict(list), 'b': defaultdict(list)}
    for k, e in inv['entries'].items():
        if not k.endswith('.ffxbnd.dcx'):
            continue
        base_ents = {}
        if e.get('base'):
            base_ents = bnd_entries(ws, e['base'], 'base__' + Path(k).name)
        for side in ('a', 'b'):
            if side not in e or e.get(side + '_unchanged'):
                continue
            for name, sha in bnd_entries(ws, e[side], side + '__' + Path(k).name).items():
                m = re.search(r'f(\d{9})\.fxr$', name)
                if m and base_ents.get(name) != sha:
                    added[side][int(m.group(1))].append((e['rel'], sha))
    out = []
    for fid in sorted(set(added['a']) & set(added['b'])):
        la, lb = added['a'][fid], added['b'][fid]
        if {s for _, s in la} != {s for _, s in lb}:
            out.append(f'- FXR {fid}: {names["a"]} in {", ".join(sorted({f for f, _ in la}))}; {names["b"]} in '
                       f'{", ".join(sorted({f for f, _ in lb}))}; content differs -> decide (renumber one side or share one)')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ws = Workspace(ap.parse_args().workspace)
    plan, inv = ws.plan, load_json(ws.p('inventory.json'))
    names = {'a': plan['a']['name'], 'b': plan['b']['name'], 'base': plan['base']['name']}
    ensure_vanilla(ws, plan, inv)
    L = ['# Analysis summary', '', f'A = {names["a"]}, B = {names["b"]}, base = {names["base"]}', '', '## Merge dry-runs', '']
    kinds = set()
    for rel, spec in plan['files'].items():
        e = inv['entries'].get(rel.lower())
        if not e:
            L.append(f'- `{rel}`: not in inventory (typo in plan.json?)')
            continue
        if e['status'] != 'both_changed':
            continue
        kinds.add((spec['strategy'], e['a']))
        L.append(f'- `{rel}` [{spec["strategy"]}]: ' + dry_run(ws, rel, spec, e, names))
    missing = [e['rel'] for e in inv['entries'].values() if e['status'] == 'both_changed' and e['rel'] not in plan['files']]
    if missing:
        L += ['', '**Files both mods changed but plan.json does not cover:** ' + ', '.join(f'`{m}`' for m in missing)]

    L += ['', '## Review leads', '']
    for k, e in inv['entries'].items():
        if k.endswith('.hks') and e['status'] == 'both_changed':
            extra = {s: [x['a' if s == 'a' else 'b'] for kk, x in inv['entries'].items()
                         if kk.endswith('.hks') and x['status'] == f'only_{s}'] for s in ('a', 'b')}
            spec = plan['files'].get(e['rel'], {})
            res = hks_analyze.analyze(base_path(ws, e['rel'], spec, e), e['a'], e['b'], extra['a'], extra['b'])
            save_json(ws.p('analysis', safe(e['rel']) + '.hks.json'), res)
            L.append(hks_analyze.to_markdown(e['rel'], res, names))
    fx = fxr_collisions(ws, inv, names)
    L += ['### Effect (FXR) IDs', ''] + (fx or ['- no FXR ID added by both mods with different content']) + ['']
    dlls = [(names[s], e['rel']) for e in inv['entries'].values() for s in ('a', 'b') if s in e and e['rel'].lower().endswith('.dll')]
    L += ['### Native DLLs (need [[natives]] entries in the ME3 profile / ModEngine config)', '']
    L += [f'- {n}: `{r}`' for n, r in dlls] or ['- none']
    for side, extras in inv.get('package_extras', {}).items():
        L += ['', f'### Package files outside the mod folder ({names[side]}): read installers/readmes for config edits', '']
        L += [f'- `{x}`' for x in extras[:40]]
    L += ['', '## Write-back checks (roundtrip)', '']
    for strat, path in sorted(kinds):
        if strat in ('regulation', 'tae', 'bnd', 'behavior'):
            code, out = ws.ermerge('roundtrip', path, '--defs', ws.kit['defs'], check=False, quiet=True)
            L.append(f'- {strat} `{Path(path).name}`: ' + '; '.join(l.strip() for l in out.splitlines() if l[:4] in ('OK r', 'OK b', 'DIFF', 'INFO', 'OK p')))
    ws.p('analysis', 'SUMMARY.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f'wrote {ws.p("analysis", "SUMMARY.md")}')


if __name__ == '__main__':
    main()
