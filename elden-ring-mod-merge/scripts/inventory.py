"""File-level comparison of the base and the two mods; drafts plan.json.

usage: python inventory.py --workspace W --a <mod A folder> --b <mod B folder> [--base <base mod folder>]
                           [--a-name NAME] [--b-name NAME] [--base-name NAME] [--force]

Mod folders may be the mod root (the folder ME3/ModEngine loads) or an extracted package containing mod/.
Without --base the base is the unmodded game (files are then compared against vanilla copies at build time).
Writes inventory.json, inventory.md and, unless it exists (or --force), a draft plan.json.
"""
import argparse
import re
from pathlib import Path

from kit import Workspace, find_mod_root, is_junk, save_json, sha256, walk

# Suggested strategy by path; the agent confirms or changes it after analysis (see FILE-TYPES.md).
RULES = [
    (r'(^|/)regulation\.bin$', 'regulation'),
    (r'^action/(event|state|variable)nameid\.txt$', 'nameid'),
    (r'\.behbnd\.dcx$', 'behavior'),
    (r'(^|/)c\d{4}\.anibnd\.dcx$', 'tae'),
    (r'\.(hks|lua|txt|ini|toml|json|xml|csv|js)$', 'text3'),
    (r'bnd\.dcx$', 'bnd'),
]
# Files the base does not ship but the game has in its archives (so a vanilla copy can serve as the base).
NOT_ARCHIVED = [r'^dll/', r'\.dll$', r'\.(ini|toml|json|me3)$']


def suggest(rel):
    low = rel.lower()
    if low.endswith('regulation.bin'):
        return 'regulation'
    for pat, strat in RULES:
        if re.search(pat, low):
            return strat
    return 'take'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--a', required=True)
    ap.add_argument('--b', required=True)
    ap.add_argument('--base', default=None)
    ap.add_argument('--a-name', default='A')
    ap.add_argument('--b-name', default='B')
    ap.add_argument('--base-name', default=None)
    ap.add_argument('--force', action='store_true', help='overwrite an existing plan.json')
    args = ap.parse_args()
    ws = Workspace(args.workspace)

    roots, packages, files, skipped = {}, {}, {}, {}
    for side, folder in (('base', args.base), ('a', args.a), ('b', args.b)):
        if not folder:
            continue
        roots[side], packages[side] = find_mod_root(folder)
        files[side], skipped[side] = walk(roots[side])
        if ws.dir == roots[side] or roots[side] in ws.dir.parents:
            raise SystemExit('the workspace must not be inside a mod folder')

    entries = {}
    keys = set(files['a']) | set(files['b'])
    for k in sorted(keys):
        e = {}
        for side in ('base', 'a', 'b'):
            hit = files.get(side, {}).get(k)
            if hit:
                e['rel'] = e.get('rel', hit[0])
                e[side] = str(hit[1])
                e[side + '_sha'] = sha256(hit[1])
        in_a, in_b = 'a' in e, 'b' in e
        if in_a and in_b:
            e['status'] = 'same' if e['a_sha'] == e['b_sha'] else 'both_changed'
        else:
            e['status'] = 'only_a' if in_a else 'only_b'
        if 'base' in e:
            for side in ('a', 'b'):
                if side in e and e[side + '_sha'] == e['base_sha']:
                    e[side + '_unchanged'] = True
            if e['status'] == 'both_changed' and (e.get('a_unchanged') or e.get('b_unchanged')):
                e['status'] = 'one_changed'
        entries[k] = e

    # Package files outside the mod root: installers, readmes, ME3/ModEngine profiles - the agent must read them.
    extras = {}
    for side in ('a', 'b'):
        pkg, root = packages[side], roots[side]
        if pkg != root and pkg.exists():
            extras[side] = sorted(str(p.relative_to(pkg)) for p in pkg.rglob('*')
                                  if p.is_file() and root not in p.parents and not is_junk(p.name))

    inv = {'roots': {k: str(v) for k, v in roots.items()}, 'packages': {k: str(v) for k, v in packages.items()},
           'names': {'a': args.a_name, 'b': args.b_name, 'base': args.base_name or ('vanilla' if not args.base else 'base')},
           'entries': entries, 'skipped_junk': skipped, 'package_extras': extras}
    save_json(ws.p('inventory.json'), inv)

    need = [e for e in entries.values() if e['status'] == 'both_changed']
    lines = [f'# Inventory', '', f'- base: {inv["names"]["base"]} `{roots.get("base", "(unmodded game)")}`',
             f'- A: {args.a_name} `{roots["a"]}`', f'- B: {args.b_name} `{roots["b"]}`', '',
             '| status | count | meaning |', '|---|---:|---|']
    meaning = {'only_a': 'shipped by A only: copied', 'only_b': 'shipped by B only: copied', 'same': 'identical in A and B: copied',
               'one_changed': 'both ship it but one equals the base: the changed one is copied', 'both_changed': 'both changed it: needs a merge'}
    for st in meaning:
        lines.append(f'| {st} | {sum(1 for e in entries.values() if e["status"] == st)} | {meaning[st]} |')
    lines += ['', '## Files both mods changed', '', '| file | in base | suggested strategy |', '|---|---|---|']
    for e in need:
        lines.append(f'| `{e["rel"]}` | {"yes" if "base" in e else "no"} | {suggest(e["rel"])} |')
    for side, ex in extras.items():
        lines += ['', f'## Package files outside the mod folder ({inv["names"][side]}) - read these', '']
        lines += [f'- `{x}`' for x in ex]
    for side, sk in skipped.items():
        if sk:
            lines += ['', f'## Skipped junk ({side})', ''] + [f'- `{x}`' for x in sk]
    ws.p('inventory.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    if ws.p('plan.json').exists() and not args.force:
        print('plan.json exists; not overwritten (use --force)')
    else:
        plan = {'base': {'name': inv['names']['base'], 'dir': str(roots['base']) if 'base' in roots else None},
                'a': {'name': args.a_name, 'dir': str(roots['a'])}, 'b': {'name': args.b_name, 'dir': str(roots['b'])},
                'exclude': [], 'files': {}}
        for e in need:
            strat = suggest(e['rel'])
            spec = {'strategy': strat, 'base_source': 'base' if 'base' in e else
                    ('none' if any(re.search(p, e['rel'].lower()) for p in NOT_ARCHIVED) else 'vanilla')}
            if strat in ('regulation', 'tae', 'bnd'):
                spec['primary'] = 'a'
            if strat == 'behavior':
                spec['keep'] = 'a'
            if strat == 'nameid':
                spec['keep'] = 'a'
            if strat == 'text3':
                spec['encoding_from'] = 'base' if 'base' in e else 'a'
            if strat == 'take':
                spec['side'] = None
            plan['files'][e['rel']] = spec
        save_json(ws.p('plan.json'), plan)
        print('draft plan.json written; review it with analyze.py before building')
    print(f'{len(entries)} files: ' + ', '.join(f'{st} {sum(1 for e in entries.values() if e["status"] == st)}' for st in meaning))
    print(f'see {ws.p("inventory.md")}')


if __name__ == '__main__':
    main()
