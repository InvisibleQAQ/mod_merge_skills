"""Builds the merged mod into <workspace>/staging, verifies it, applies decision patches and checks the result.

usage: python build.py --workspace W

1. vanilla copies for files whose base_source is "vanilla"
2. every file only one side changed: copied (plan entries may still override: take + drop_entries, manual, exclude)
3. every file both changed: merged with its plan strategy; unresolved conflicts stop the build (exit 3)
4. verify.py (three-way expectations) on the raw merge result
5. hooks/post_merge.py <staging> <workspace> if present: the user's decisions that are code edits. Text files are
   copied to reports/prehook/ first; the hook's changes are written to reports/hooks.diff and must be labelled
   hunks, one per patch() call (checked by verify.py, reported in VERIFY.md)
6. luac -p on every .hks when Lua is installed (exact with Lua 5.1; other versions only approximate the check)
7. crosscheck.py: references between files (names, SpEffects, effects, hard-coded states); errors stop the build
Writes reports/BUILD.json + reports/BUILD.md. deploy.py refuses to run unless the last build finished "ok".
"""
import argparse
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__
import crosscheck  # noqa: E402
import verify  # noqa: E402
from analyze import ensure_vanilla  # noqa: E402
from kit import TEXT_EXT, Workspace, base_path, copy_file, copy_side, fail, load_json, save_json, sha256  # noqa: E402
from text_merge import merge3, merge_nameid  # noqa: E402


def merge_one(ws, rel, spec, e, names, dst):
    """Returns (how, sources, conflict_message or None, note)."""
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
        n = merge3(kit['git'], base, e['a'], e['b'], dst, spec.get('encoding_from', 'base'), tmp=ws.dir)
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
        return 'manual', [str(src)], None, ''
    elif strat == 'take':
        side = spec.get('side')
        if side not in ('a', 'b'):
            return 'take', [], 'needs "side": "a" or "b"', ''
        if not spec.get('drop_entries'):
            copy_file(e[side], dst)
            return 'take', [e[side]], None, ''
        code, out = ws.ermerge('bnd-drop', e[side], dst, *spec['drop_entries'], check=False)
        if code:
            return 'take', [e[side]], 'drop_entries: ' + out.strip().splitlines()[-1], ''
        return 'take', [e[side]], None, f'{sum(x.strip().startswith("dropped ") for x in out.splitlines())} entries dropped'
    else:
        return strat, [], f'unknown strategy {strat}', ''
    return strat, [base, e['a'], e['b']], ('unresolved conflicts, see ' + str(rep)) if code == 3 else None, ''


def run_hook(ws, staging, items):
    """Runs hooks/post_merge.py on staging after snapshotting its text files; returns (patched files, patch() calls)."""
    hook = ws.p('hooks', 'post_merge.py')
    if not hook.exists():
        return [], 0
    for p in staging.rglob('*'):
        if p.is_file() and p.suffix.lower() in TEXT_EXT:
            copy_file(p, ws.p('reports', 'prehook', p.relative_to(staging)))
    before = {p: sha256(p) for p in staging.rglob('*') if p.is_file()}
    r = subprocess.run([sys.executable, '-B', str(hook), str(staging), str(ws.dir)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    print((r.stdout or '') + (r.stderr or ''), end='')
    if r.returncode:
        save_json(ws.p('reports', 'BUILD.json'), {'status': 'hook_failed', 'files': items})
        sys.exit(f'hook {hook} failed (exit {r.returncode})')
    after = {p: sha256(p) for p in staging.rglob('*') if p.is_file()}
    patched = sorted(p.relative_to(staging).as_posix() for p in after if before.get(p) != after[p])
    print(f'hook patched: {patched}')
    return patched, sum(1 for x in (r.stdout or '').splitlines() if x.startswith('patched '))


def check_lua(ws, staging, items):
    """luac -p on every .hks (BOM removed; the temp copy stays inside the workspace). Returns the BUILD.md line."""
    kit = ws.kit
    if not kit.get('luac'):
        return 'luac: not run (setup.py found no Lua compiler)'
    tmp = ws.p('reports', 'luac_check.lua')
    for p in sorted(staging.rglob('*.hks')):
        tmp.write_bytes(p.read_bytes().removeprefix(b'\xef\xbb\xbf'))
        r = subprocess.run([kit['luac'], '-p', str(tmp)], capture_output=True, text=True)
        if r.returncode:
            save_json(ws.p('reports', 'BUILD.json'), {'status': 'lua_syntax_error', 'files': items})
            sys.exit(f'Lua syntax error in {p}: {r.stderr.strip().replace(str(tmp), p.name)}')
    tmp.unlink(missing_ok=True)
    ver = kit.get('luac_version') or 'unknown'
    print(f'luac -p (Lua {ver}): all .hks files parse')
    return f'luac -p (Lua {ver}): all .hks files parse' + (
        '' if ver == '5.1' else ' - Havok Script is Lua 5.1 syntax, so this is necessary, not sufficient')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ws = Workspace(ap.parse_args().workspace)
    plan, inv = ws.plan, load_json(ws.p('inventory.json'))
    names = {'a': plan['a']['name'], 'b': plan['b']['name']}
    staging = ws.p('staging')
    for stale in (staging, ws.p('reports', 'prehook')):
        if stale.exists():
            shutil.rmtree(stale)
    ws.p('reports').mkdir(exist_ok=True)
    for stale in ('hooks.diff', 'CROSSCHECK.md', 'CROSSCHECK.json'):
        ws.p('reports', stale).unlink(missing_ok=True)
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
            side = copy_side(e)
            copy_file(e[side], dst)
            items.append({'rel': rel, 'how': 'copy', 'source': e[side], 'side': side})
            continue
        print(f'[{spec["strategy"]}] {rel}')
        how, sources, err, note = merge_one(ws, rel, spec, e, names, dst)
        if err:
            problems.append(f'{rel}: {err}')
            continue
        items.append({'rel': rel, 'how': how, 'source': sources[0] if len(sources) == 1 else None, 'sources': sources, 'note': note})
    if problems:
        save_json(ws.p('reports', 'BUILD.json'), {'status': 'conflicts', 'problems': problems, 'files': items})
        print('\nBUILD STOPPED - decisions needed:\n  ' + '\n  '.join(problems))
        sys.exit(3)
    save_json(ws.p('reports', 'BUILD.json'), {'status': 'verifying', 'files': items})
    print('\nverifying ...')
    if verify.run(ws):
        save_json(ws.p('reports', 'BUILD.json'), {'status': 'verify_failed', 'files': items})
        sys.exit('verification failed; see reports/VERIFY.md')

    patched, calls = run_hook(ws, staging, items)
    save_json(ws.p('reports', 'BUILD.json'), {'status': 'checking', 'files': items, 'hook_patched': patched, 'hook_patch_calls': calls})
    hook_errs, hook_stats = verify.append_hooks(ws)
    if hook_errs:
        save_json(ws.p('reports', 'BUILD.json'), {'status': 'hook_check_failed', 'files': items, 'hook_patched': patched})
        sys.exit('hook check failed:\n  ' + '\n  '.join(hook_errs) + '\nsee reports/VERIFY.md and reports/hooks.diff')
    lua_line = check_lua(ws, staging, items)
    print('cross-file checks ...')
    cross = crosscheck.run(ws)
    if cross['error']:
        save_json(ws.p('reports', 'BUILD.json'), {'status': 'crosscheck_failed', 'files': items, 'hook_patched': patched})
        sys.exit(f'{cross["error"]} cross-file error(s) introduced by the merge; see reports/CROSSCHECK.md')

    for it in items:
        p = staging.joinpath(*it['rel'].split('/'))
        if p.exists():
            it['sha256'] = sha256(p)
    save_json(ws.p('reports', 'BUILD.json'), {'status': 'ok', 'files': items, 'hook_patched': patched, 'hook_patch_calls': calls})
    hunks = sum(h for h, _, _ in hook_stats.values())
    lines = ['# Build', '', f'{len([i for i in items if i["how"] != "excluded"])} files in `{staging}`', '',
             f'- hooks: {len(patched)} file(s) patched, {hunks} hunk(s), {calls} patch() call(s) '
             '(diff: reports/hooks.diff; checks: reports/VERIFY.md)',
             f'- {lua_line}',
             f'- cross-file checks: {cross["error"]} errors, {cross["warn"]} warnings, {cross["info"]} info (reports/CROSSCHECK.md)',
             '', '| file | how | hook patched | notes |', '|---|---|---|---|']
    for i in items:
        h = hook_stats.get(i['rel'])
        mark = f'{h[0]} hunk(s), +{h[1]} / -{h[2]} lines' if h else ('yes (not a text file)' if i['rel'] in patched else '')
        lines.append(f'| `{i["rel"]}` | {i["how"]} | {mark} | {i.get("note", "")} |')
    ws.p('reports', 'BUILD.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'build ok -> {staging}')


if __name__ == '__main__':
    main()
