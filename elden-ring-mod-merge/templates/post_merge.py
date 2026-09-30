"""Decision patches applied by build.py after the merge was verified. Copy to <workspace>/hooks/post_merge.py.

usage (by build.py): python post_merge.py <staging folder> <workspace folder>
Each patch replaces bytes that must occur exactly once; a missing anchor fails the build instead of silently
skipping a decision (e.g. after a mod update). Keep line endings as in the target file (\\r\\n vs \\n).
build.py then diffs each patched file against its pre-hook copy (reports/hooks.diff): every changed hunk must carry
a `-- merge ...` comment, and there must be one hunk per patch() call (it counts the "patched" lines printed below).
"""
import sys
from pathlib import Path

staging = Path(sys.argv[1])


def patch(rel, old, new):
    p = staging / rel
    data = p.read_bytes()
    n = data.count(old)
    if n != 1:
        sys.exit(f'{rel}: anchor found {n} times, expected exactly once: {old[:80]!r}')
    p.write_bytes(data.replace(old, new))
    print(f'patched {rel}')


# Decision 1.1 (see decisions.md): disable feature X at its single entry point.
# patch('action/script/c0000.hks',
#       b'function StartFeatureX(arg)\r\n',
#       b'function StartFeatureX(arg)\r\ndo return FALSE end -- merge: feature X disabled (decision 1.1)\r\n')
