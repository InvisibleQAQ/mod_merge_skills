"""Regression check: compares a build with a reference mod folder.

usage: python regression/compare.py --workspace W --reference <mod folder> [--staging <folder>]

Passes when both folders hold the same relative paths and every file is byte-identical, except regulation.bin
(its AES IV is random): there the param-dump output (every param, row, field and row name) must be identical.
Uses the ermerge build of workspace W (dumps are cached in W/dumps/cache). Exit code 1 on any difference.
"""
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'elden-ring-mod-merge' / 'scripts'))
from kit import Workspace, sha256, walk  # noqa: E402


def same_params(ws, got, ref):
    dg, dr = Path(ws.dump('param', got)), Path(ws.dump('param', ref))
    names = sorted({p.name for p in dg.glob('*.tsv')} | {p.name for p in dr.glob('*.tsv')})
    diff = [n for n in names if not ((dg / n).exists() and (dr / n).exists() and (dg / n).read_bytes() == (dr / n).read_bytes())]
    return diff, len(names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--reference', required=True)
    ap.add_argument('--staging', default=None)
    a = ap.parse_args()
    ws = Workspace(a.workspace)
    got, ref = walk(a.staging or ws.p('staging'))[0], walk(a.reference)[0]
    problems = [f'only in the build: {got[k][0]}' for k in sorted(set(got) - set(ref))]
    problems += [f'only in the reference: {ref[k][0]}' for k in sorted(set(ref) - set(got))]
    identical = 0
    for k in sorted(set(got) & set(ref)):
        g, r = got[k][1], ref[k][1]
        if sha256(g) == sha256(r):
            identical += 1
        elif k.endswith('regulation.bin'):
            diff, n = same_params(ws, g, r)
            if diff:
                problems.append(f'{got[k][0]}: param dumps differ: {diff[:10]}')
            else:
                print(f'{got[k][0]}: encrypted bytes differ (random IV), all {n} param dumps identical')
        else:
            problems.append(f'{got[k][0]}: bytes differ')
    print(f'{len(got)} files in the build, {len(ref)} in the reference; {identical} byte-identical')
    for p in problems:
        print('  DIFF ' + p)
    print('regression OK' if not problems else f'regression FAILED: {len(problems)} difference(s)')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
