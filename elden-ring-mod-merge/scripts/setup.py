"""Checks prerequisites and builds the ermerge tool into <workspace>/.kit.

usage: python setup.py --workspace <dir> --smithbox <Smithbox program folder> --game <ELDEN RING\\Game> [--dotnet <dotnet.exe>]

Writes <workspace>/kit.json. Prints every missing prerequisite with what to install; exits non-zero if any
required one is missing. Safe to re-run (rebuilds the tool).
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from kit import CSPROJ, Workspace, save_json


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except (FileNotFoundError, OSError) as e:
        return -1, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--smithbox', required=True, help='folder that contains Smithbox.exe and Andre.SoulsFormats.dll')
    ap.add_argument('--game', required=True, help='ELDEN RING\\Game folder (contains eldenring.exe)')
    ap.add_argument('--dotnet', default=None, help='path to dotnet.exe if it is not on PATH')
    a = ap.parse_args()
    ws = Workspace(a.workspace)
    problems, notes = [], []

    if sys.version_info < (3, 9):
        problems.append(f'Python 3.9+ required, found {sys.version.split()[0]}')

    sb = Path(a.smithbox)
    need = ['Andre.SoulsFormats.dll', 'Andre.Formats.dll', 'Havok.HKLib.dll', 'Havok.HKLib.Serialization.dll',
            'Res/HavokTypeRegistry20180100.xml', 'Assets/PARAM/ER/Defs', 'Assets/TAE/TAE.Template.ER.xml']
    missing = [n for n in need if not (sb / n).exists()]
    tfm = None
    if missing:
        problems.append(f'Smithbox folder {sb} is missing: {", ".join(missing)} (download the Windows release zip from '
                        'https://github.com/vawser/Smithbox/releases and extract it; pass the folder containing Smithbox.exe)')
    else:
        m = re.search(rb'\.NETCoreApp,Version=v(\d+)\.(\d+)', (sb / 'Andre.SoulsFormats.dll').read_bytes())
        tfm = f'net{m.group(1).decode()}.{m.group(2).decode()}' if m else None
        if not tfm:
            problems.append('could not read the target framework of Andre.SoulsFormats.dll')

    game = Path(a.game)
    for n in ['eldenring.exe', 'regulation.bin', 'oo2core_6_win64.dll', 'Data0.bhd']:
        if not (game / n).exists():
            problems.append(f'game folder {game} has no {n} (point --game at ...\\ELDEN RING\\Game)')

    dotnet = a.dotnet or shutil.which('dotnet')
    sdk_major = 0
    if not dotnet:
        problems.append('.NET SDK not found (install from https://dotnet.microsoft.com/download; version >= the one Smithbox targets)')
    else:
        code, out = run([dotnet, '--list-sdks'])
        majors = [int(x) for x in re.findall(r'^(\d+)\.\d+\.\d+', out, re.M)]
        sdk_major = max(majors, default=0)
        if tfm and sdk_major < int(tfm[3:].split('.')[0]):
            problems.append(f'.NET SDK {tfm[3:]} or newer required (Smithbox targets {tfm}); installed SDKs: {majors or "none"}')

    git = shutil.which('git')
    if not git:
        problems.append('git not found (needed for three-way text merges of .hks and other scripts): https://git-scm.com/downloads')
    luac = shutil.which('luac') or shutil.which('luac5.1') or shutil.which('luac5.4')
    if not luac:
        notes.append('optional: luac not found; .hks syntax checks will be skipped (install Lua to enable)')

    if problems:
        print('Missing prerequisites:')
        for p in problems:
            print('  - ' + p)
        sys.exit(1)

    kit_dir = ws.p('.kit')
    cmd = [dotnet, 'build', str(CSPROJ), '-c', 'Release', '-o', str(kit_dir / 'bin'), '-nologo', '-v', 'q',
           f'-p:SmithboxDir={sb.resolve()}', f'-p:GameDir={game.resolve()}', f'-p:TargetFramework={tfm}',
           f'-p:BaseIntermediateOutputPath={kit_dir / "obj"}\\']
    print(f'building ermerge ({tfm}) ...')
    code, out = run(cmd)
    if code != 0:
        print(out)
        sys.exit('build failed')
    ermerge = kit_dir / 'bin' / 'ermerge.dll'
    kit = {'dotnet': dotnet, 'ermerge': str(ermerge), 'smithbox': str(sb.resolve()), 'game': str(game.resolve()),
           'defs': str((sb / 'Assets/PARAM/ER/Defs').resolve()), 'tae_template': str((sb / 'Assets/TAE/TAE.Template.ER.xml').resolve()),
           'git': git, 'luac': luac, 'tfm': tfm}
    save_json(ws.p('kit.json'), kit)
    code, out = ws.ermerge('roundtrip', game / 'regulation.bin', check=False, quiet=True)
    if code != 0 or 'OK regulation' not in out:
        print(out)
        sys.exit('smoke test failed: ermerge could not re-encrypt the game regulation.bin')
    print(f'ok: ermerge built at {ermerge}; smoke test passed')
    for n in notes:
        print('  ' + n)


if __name__ == '__main__':
    main()
