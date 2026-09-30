"""Copies staging/ into the game's mod folder with a backup, or rolls the last deployment back.

usage: python deploy.py --workspace W --target "<...\\ELDEN RING\\Game\\mod>"            (preview only)
       python deploy.py --workspace W --target "<...>" --yes                        (deploy)
       python deploy.py --workspace W --target "<...>" --rollback --yes             (undo the last deploy)

Preview lists what would be overwritten / added. Deploy requires reports/BUILD.json status "ok", backs up every
file it overwrites to backup/<timestamp>/ with manifest.tsv, copies, and re-hashes every copied file.
If a file to be overwritten differs from the base mod's copy (something else was installed on top of the base),
deploy stops unless --force is given. Rollback restores the backups and deletes files the deploy added, but only
files whose hash still matches what was deployed.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__
from kit import Workspace, copy_file, fail, load_json, sha256  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--rollback', action='store_true')
    a = ap.parse_args()
    ws = Workspace(a.workspace)
    target = Path(a.target).resolve()
    if not target.is_dir():
        fail(f'{target} is not a folder')
    if a.rollback:
        return rollback(ws, target, a.yes)
    build = load_json(ws.p('reports', 'BUILD.json'))
    if build.get('status') != 'ok':
        fail(f'last build status is {build.get("status")!r}; run build.py until it finishes ok')
    staging = ws.p('staging')
    files = sorted(p for p in staging.rglob('*') if p.is_file())
    base_dir = ws.plan['base'].get('dir')
    over, new, foreign = [], [], []
    for p in files:
        rel = p.relative_to(staging)
        t = target / rel
        if t.exists():
            over.append(rel)
            b = Path(base_dir) / rel if base_dir else None
            if b and b.exists() and sha256(b) != sha256(t) and sha256(p) != sha256(t):
                foreign.append(rel)
        else:
            new.append(rel)
    print(f'target: {target}\n  overwrite {len(over)} files, add {len(new)} files')
    for r in over:
        print(f'    overwrite {r.as_posix()}')
    for r in new:
        print(f'    add       {r.as_posix()}')
    if foreign:
        print('  these target files are neither the base version nor the merged one (another mod installed?):')
        for r in foreign:
            print(f'    ! {r.as_posix()}')
        if not a.force:
            fail('refusing to overwrite them without --force (they will still be backed up)')
    if not a.yes:
        print('preview only; re-run with --yes after the user confirms')
        return
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    bdir = ws.p('backup', stamp)
    manifest = ['action\tpath\tsha256_before\tsha256_deployed']
    for p in files:
        rel = p.relative_to(staging)
        t = target / rel
        before = ''
        if t.exists():
            before = sha256(t)
            copy_file(t, bdir / rel)
        copy_file(p, t)
        deployed = sha256(t)
        if deployed != sha256(p):
            fail(f'copy check failed for {rel}')
        manifest.append(f'{"overwrite" if before else "new"}\t{rel.as_posix()}\t{before}\t{deployed}')
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / 'manifest.tsv').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    (bdir / 'target.txt').write_text(str(target), encoding='utf-8')
    print(f'deployed {len(files)} files (hash-checked); backup + manifest in {bdir}')


def rollback(ws, target, yes):
    dirs = sorted(d for d in ws.p('backup').glob('*') if (d / 'manifest.tsv').exists())
    if not dirs:
        fail('no deployment backup found')
    bdir = dirs[-1]
    if Path((bdir / 'target.txt').read_text(encoding='utf-8')).resolve() != target:
        fail(f'the last backup ({bdir.name}) was made for another target folder')
    rows = [l.split('\t') for l in (bdir / 'manifest.tsv').read_text(encoding='utf-8').splitlines()[1:] if l]
    print(f'rollback of {bdir.name}: restore {sum(r[0] == "overwrite" for r in rows)}, delete {sum(r[0] == "new" for r in rows)}')
    if not yes:
        print('preview only; re-run with --yes')
        return
    for action, rel, before, deployed in rows:
        t = target / rel
        if t.exists() and sha256(t) != deployed:
            print(f'  skip {rel}: changed since deployment')
            continue
        if action == 'overwrite':
            copy_file(bdir / rel, t)
        elif t.exists():
            t.unlink()
    print('rollback done')


if __name__ == '__main__':
    main()
