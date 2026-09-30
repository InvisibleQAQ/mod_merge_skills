"""Text merges: action/*nameid.txt (append-only name tables) and generic three-way text (git merge-file).
Also line diffs (difflib) for checks that must not depend on git's alignment."""
import difflib
import re
import subprocess
import tempfile
from pathlib import Path

BOM = b'\xef\xbb\xbf'
NAMEID_ENTRY = re.compile(r'^(\d+)\s*= "(.*)"$')


# ---------- plain text (.hks and other scripts) ----------
def read_text(path):
    raw = Path(path).read_bytes()
    bom = raw.startswith(BOM)
    raw = raw[3:] if bom else raw
    text = raw.decode('utf-8', errors='surrogateescape')
    return text.replace('\r\n', '\n'), {'bom': bom, 'crlf': '\r\n' in text}


def read_lines(path):
    """Lines of a text file without BOM / line-ending / final-newline differences; [] for no file ('-')."""
    return [] if path in (None, '-') else read_text(path)[0].splitlines()


def line_opcodes(old, new):
    """difflib opcodes (tag, i1, i2, j1, j2) turning line list `old` into `new`, without 'equal' ones.
    The common head and tail are cut first: most mod diffs touch a small part of a large script."""
    head = 0
    while head < min(len(old), len(new)) and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < min(len(old), len(new)) - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    sm = difflib.SequenceMatcher(None, old[head:len(old) - tail], new[head:len(new) - tail], autojunk=False)
    return [(t, i1 + head, i2 + head, j1 + head, j2 + head) for t, i1, i2, j1, j2 in sm.get_opcodes() if t != 'equal']


def write_text(path, text, meta):
    if meta['crlf']:
        text = text.replace('\n', '\r\n')
    data = text.encode('utf-8', errors='surrogateescape')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes((BOM if meta['bom'] else b'') + data)


def merge3(git, base, a, b, out, encoding_from='base', tmp=None):
    """Three-way merge with git merge-file after normalising BOM / CRLF / final newline.
    Returns the number of conflict hunks (0 = clean). Conflicted output keeps <<<<<<< A / ||||||| BASE / >>>>>>> B markers.
    Output encoding (BOM, line endings) follows `encoding_from` ('base', 'a' or 'b'). Scratch files go to `tmp`."""
    texts, metas = {}, {}
    for side, p in (('base', base), ('a', a), ('b', b)):
        if p in (None, '-'):
            texts[side], metas[side] = '', None
            continue
        t, m = read_text(p)
        texts[side], metas[side] = (t if t.endswith('\n') else t + '\n'), m
    with tempfile.TemporaryDirectory(dir=tmp) as tmp:
        for side, t in texts.items():
            Path(tmp, side).write_bytes(t.encode('utf-8', errors='surrogateescape'))
        r = subprocess.run([git, 'merge-file', '-p', '--diff3', '-L', 'A', '-L', 'BASE', '-L', 'B',
                            str(Path(tmp, 'a')), str(Path(tmp, 'base')), str(Path(tmp, 'b'))], capture_output=True)
    if r.returncode < 0 or r.returncode > 127:
        raise RuntimeError(f'git merge-file failed: {r.stderr.decode(errors="replace")}')
    meta = metas.get(encoding_from) or metas['a'] or metas['b']
    if out:
        write_text(out, r.stdout.decode('utf-8', errors='surrogateescape'), meta)
    return r.returncode


# ---------- nameid tables ----------
def read_nameid(path):
    names = []
    lines = Path(path).read_bytes().split(b'\n')
    if not lines[0].startswith(b'Num'):
        raise ValueError(f'{path}: not a nameid table')
    for raw in lines[1:]:
        t = raw.rstrip(b'\r').rstrip(b'\x00 ').decode('utf-8')
        if not t:
            continue
        m = NAMEID_ENTRY.match(t)
        if not m or int(m.group(1)) != len(names) + 1:
            raise ValueError(f'{path}: unexpected line {t!r}')
        names.append(m.group(2))
    return names


def merge_nameid(base, a, b, out, keep='a'):
    """Base entries stay byte-identical; the KEEP side's appended names keep their numbers, the other side's
    are appended after them and renumbered. Returns (merged names, list of problems)."""
    c, na, nb = read_nameid(base), read_nameid(a), read_nameid(b)
    problems = [f'{side} changed or removed existing entries' for side, n in (('A', na), ('B', nb)) if n[:len(c)] != c]
    if problems:
        return None, problems
    first, second = (na[len(c):], nb[len(c):]) if keep == 'a' else (nb[len(c):], na[len(c):])
    merged = c + first + [n for n in second if n not in first]
    if out:
        raw = Path(base).read_bytes()
        body = raw.split(b'\n', 1)[1]
        body = body[:body.rindex(b'"') + 1].rstrip(b'\r') + b'\r\n' if c else b''
        data = b'Num  = %d\r\n' % len(merged) + body
        for i, name in enumerate(merged[len(c):], len(c) + 1):
            data += ('%-4d = "%s"\r\n' % (i, name)).encode('utf-8')
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(data + b'\x00' * 4)
        if read_nameid(out) != merged:
            raise RuntimeError(f'{out}: written table does not read back')
    return merged, []
