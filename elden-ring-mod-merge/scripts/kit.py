"""Shared helpers for the elden-ring-mod-merge scripts: workspace files, running ermerge, file walking.

Workspace layout (one folder per merge job, never inside a mod or game folder):
  kit.json        tool locations written by setup.py
  plan.json       what to merge and how (inventory.py drafts it, the agent edits it after the user decides)
  inventory.*     file-level comparison of base / A / B
  analysis/       dry-run reports and heuristic findings (analyze.py)
  vanilla/        game files extracted when the base mod does not ship a file
  dumps/          text dumps used by verify.py
  staging/        the merged mod files (build.py); deploy.py copies them into the game's mod folder
  reports/        per-file merge reports, verify report, hook log
  hooks/post_merge.py   optional decision patches applied after merging (see WORKFLOW.md)
  backup/         files replaced by deploy.py (for rollback)
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CSPROJ = SKILL_DIR / 'tools' / 'ErMergeKit' / 'ErMergeKit.csproj'

# Folders that make a directory look like an Elden Ring mod root (the folder ME3/ModEngine points at).
MOD_MARKERS = {'regulation.bin', 'action', 'chr', 'parts', 'param', 'event', 'map', 'msg', 'sfx', 'sd', 'script',
               'menu', 'asset', 'material', 'movie', 'other', 'cutscene', 'font', 'expression', 'obj', 'dll'}
# Never merged or deployed: backups, logs, editor caches, OS junk.
JUNK = [r'\.bak$', r'\.backup$', r'\.bak\d*$', r'\.log$', r'\.tmp$', r'(^|/)_dsas_cache/', r'(^|/)thumbs\.db$',
        r'(^|/)desktop\.ini$', r'\.before-[^/]*$', r'(^|/)\.git/', r'\.orig$', r'~$']


def fail(msg, code=1):
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(code)


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        fail(f'{p} not found')
    return json.loads(p.read_text(encoding='utf-8'))


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def is_junk(rel):
    low = rel.lower()
    return any(re.search(p, low) for p in JUNK)


def find_mod_root(folder):
    """Returns (mod_root, package_root). Accepts the mod folder itself or an extracted package with a mod/ subfolder."""
    p = Path(folder).resolve()
    if not p.is_dir():
        fail(f'{p} is not a folder')

    def score(d):
        return len({c.name.lower() for c in d.iterdir()} & MOD_MARKERS) if d.is_dir() else 0
    if score(p / 'mod') > score(p):
        return p / 'mod', p
    if score(p) == 0:
        subs = [d for d in p.iterdir() if d.is_dir() and score(d) > 0]
        if len(subs) == 1:
            return subs[0], p
        fail(f'{p} does not look like an Elden Ring mod folder (expected files such as regulation.bin, chr/, action/, parts/)')
    return p, p


def walk(root):
    """Maps lower-case relative path -> (relative path with original case, absolute Path). Skips junk."""
    out, skipped = {}, []
    root = Path(root)
    for dirpath, _, files in os.walk(root):
        for fn in files:
            ap = Path(dirpath) / fn
            rel = ap.relative_to(root).as_posix()
            if is_junk(rel):
                skipped.append(rel)
                continue
            out[rel.lower()] = (rel, ap)
    return out, skipped


class Workspace:
    def __init__(self, path):
        self.dir = Path(path).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)

    def p(self, *parts):
        return self.dir.joinpath(*parts)

    @property
    def kit(self):
        return load_json(self.p('kit.json'))

    @property
    def plan(self):
        return load_json(self.p('plan.json'))

    def ermerge(self, *args, check=True, quiet=False):
        """Runs ermerge; returns (exit code, output). Exit code 3 means unresolved conflicts."""
        kit = self.kit
        cmd = [kit['dotnet'], kit['ermerge'], *[str(a) for a in args]]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        out = (r.stdout or '') + (r.stderr or '')
        if not quiet:
            print(out.rstrip())
        if check and r.returncode not in (0, 3):
            fail(f'ermerge {args[0]} failed (exit {r.returncode})')
        return r.returncode, out


def base_path(ws, rel, spec, inv_entry):
    """Path of the common ancestor of a file, '-' when there is none."""
    src = spec.get('base_source', 'base')
    if src == 'base' and inv_entry.get('base'):
        return inv_entry['base']
    if src == 'vanilla':
        v = ws.p('vanilla', *rel.lower().split('/'))
        if v.exists():
            return str(v)
        fail(f'{rel}: vanilla copy missing; run build.py/analyze.py with a configured game folder (setup.py --game)')
    return '-'


def rel_key(rel):
    return rel.replace('\\', '/').lower()


def copy_file(src, dst):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
