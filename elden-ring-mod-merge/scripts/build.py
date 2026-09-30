"""Builds the merged mod into <workspace>/staging, verifies it, then applies decision patches.

usage: python build.py --workspace W

1. vanilla copies for files whose base_source is "vanilla"
2. every file only one side changed: copied (plan entries may still override: take + drop_entries, manual, exclude)
3. every file both changed: merged with its plan strategy; unresolved conflicts stop the build (exit 3)
4. verify.py (three-way expectations) on the raw merge result
5. hooks/post_merge.py <staging> <workspace> if present: the user's decisions that are code edits
6. luac -p on merged/patched .hks when Lua is installed
Writes reports/BUILD.json + reports/BUILD.md. deploy.py refuses to run unless the last build finished "ok".
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import verify
from analyze import ensure_vanilla
from kit import Workspace, base_path, copy_file, fail, load_json, save_json, sha256
from text_merge import merge3, merge_nameid


def merge_one(ws, rel, spec, e, names, dst):
    """Returns (how, sources, conflict_message or None)."""
    kit, strat = ws.kit, spec['strategy']
    rep = ws.p('reports', rel.replace('/', '__') + '.json')
    res_file = ws.p('reports', rel.replace('/', '__') + '.resolve.json')
    save_json(res_file, spec.get('resolve', {}))
    base = base_path(ws, rel, spec, e) if e['status'] == 'both_changed' else '-'
    common = ['--report', rep, '--resolve', res_file]
    if strat == 'regulation':
        code, _ = ws.ermerge('reg-merge', base, e['a'], e['b'], kit['defs'], dst, '--primary', spec.get('primary', 'a'),
                             '--label-a', spec.get('label_a', names['a']), '--label-b', spec.get('label_b', names['b']), *common)
    elif strat in ('tae', 'bnd'):
        code, _ = ws.ermerge(f'{strat}-merge', base, e['a'], e['b'], dst, '--primary', spec.get('primary', 'a'), *common)
    elif strat == 'behavior':
        keep = spec.get('keep', 'a')
        move = 'b' if keep == 'a' else 'a'
        code, _ = ws.ermerge('beh-merge', base, e[keep], e[move], dst, '--wrap-order', spec.get('wrap_order', 'move-outer'), *common)
    elif strat == 'nameid':
        _, problems = merge_nameid(base, e['a'], e['b'], dst, spec.get('keep', 'a'))
        code = 3 if problems else 0
        if problems:
            print('  ' + '; '.join(problems))
    elif strat == 'text3':
        n = merge3(kit['git'], base, e['a'], e['b'], dst, spec.get('encoding_from', 'base'))
        code = 3 if n else 0
        if n:
            keep = ws.p('conflicts', *rel.split('/'))
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), keep)
            print(f'  {n} conflict hunk(s); marked file saved to {keep}. Resolve it into resolved/{rel} and set '
                  f'"strategy": "manual", "source": "resolved/{rel}"')
    elif strat == 'manual':
        src = ws.p(*spec['source'].split('/'))
        if not src.exists():
            fail(f'{rel}: manual source {src} missing')
        copy_file(src, dst)
        return 'manual', [str(src)], None
    elif strat == 'take':
        side = spec.get('side')
        if side not in ('a', 'b'):
            return 'take', [], 'needs "side": "a" or "b"'
        if spec.get('drop_entries'):
            ws.ermerge('bnd-drop', e[side], dst, *spec['drop_entries'])
        else:
            copy_file(e[side], dst)
        return 'take', [e[side]], None
    else:
        return strat, [], f'unknown strategy {strat}'
    return strat, [base, e['a'], e['b']], ('unresolved conflicts, see ' + str(rep)) if code == 3 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ws = Workspace(ap.parse_args().workspace)
    kit, plan, inv = ws.kit, ws.plan, load_json(ws.p('inventory.json'))
    names = {'a': plan['a']['name'], 'b': plan['b']['name']}
    staging = ws.p('staging')
    if staging.exists():
        shutil.rmtree(staging)
    ws.p('reports').mkdir(exist_ok=True)
    ensure_vanilla(ws, plan, inv)
    exclude = {x.lower() for x in plan.get('exclude', [])}
    items, problems = [], []
    save_json(ws.p('reports', 'BUILD.json'), {'status': 'running', 'files': []})
    for k, e in sorted(inv['entries'].items()):
        rel = e['rel']
        if k in exclude:
            items.append({'rel': rel, 'how': 'excluded'})
            continue
        dst = staging.joinpath(*rel.split('/'))
        spec = plan['files'].get(rel)
        if spec is None:
            if e['status'] == 'both_changed':
                problems.append(f'{rel}: both mods changed it but plan.json has no entry')
                continue
            side = 'a' if e['status'] in ('only_a', 'same') or (e['status'] == 'one_changed' and not e.get('a_unchanged')) else 'b'
            copy_file(e[side], dst)
            items.append({'rel': rel, 'how': 'copy', 'source': e[side], 'side': side})
            continue
        print(f'[{spec["strategy"]}] {rel}')
        how, sources, err = merge_one(ws, rel, spec, e, names, dst)
        if err:
            problems.append(f'{rel}: {err}')
            continue
        items.append({'rel': rel, 'how': how, 'source': sources[0] if len(sources) == 1 else None, 'sources': sources})
    if problems:
        save_json(ws.p('reports', 'BUILD.json'), {'status': 'conflicts', 'problems': problems, 'files': items})
        print('\nBUILD STOPPED - decisions needed:\n  ' + '\n  '.join(problems))
        sys.exit(3)
    save_json(ws.p('reports', 'BUILD.json'), {'status': 'verifying', 'files': items})
    print('\nverifying ...')
    if verify.run(ws):
        save_json(ws.p('reports', 'BUILD.json'), {'status': 'verify_failed', 'files': items})
        sys.exit('verification failed; see reports/VERIFY.md')

    hook = ws.p('hooks', 'post_merge.py')
    patched = []
    if hook.exists():
        before = {p: sha256(p) for p in staging.rglob('*') if p.is_file()}
        r = subprocess.run([sys.executable, str(hook), str(staging), str(ws.dir)])
        if r.returncode:
            sys.exit(f'hook {hook} failed (exit {r.returncode})')
        after = {p: sha256(p) for p in staging.rglob('*') if p.is_file()}
        patched = sorted(str(p.relative_to(staging).as_posix()) for p in after if before.get(p) != after[p])
        print(f'hook patched: {patched}')
    if kit.get('luac'):
        for p in staging.rglob('*.hks'):
            text = p.read_bytes().removeprefix(b'\xef\xbb\xbf')
            with tempfile.NamedTemporaryFile('wb', suffix='.lua', delete=False) as t:
                t.write(text)
            r = subprocess.run([kit['luac'], '-p', t.name], capture_output=True, text=True)
            Path(t.name).unlink()
            if r.returncode:
                sys.exit(f'Lua syntax error in {p}: {r.stderr.strip()}')
        print('luac -p: all .hks files parse')
    for it in items:
        p = staging.joinpath(*it['rel'].split('/'))
        if p.exists():
            it['sha256'] = sha256(p)
    save_json(ws.p('reports', 'BUILD.json'), {'status': 'ok', 'files': items, 'hook_patched': patched})
    lines = ['# Build', '', f'{len([i for i in items if i["how"] != "excluded"])} files in `{staging}`', '',
             '| file | how | hook patched |', '|---|---|---|']
    lines += [f'| `{i["rel"]}` | {i["how"]} | {"yes" if i["rel"] in patched else ""} |' for i in items]
    ws.p('reports', 'BUILD.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'build ok -> {staging}')


if __name__ == '__main__':
    main()
