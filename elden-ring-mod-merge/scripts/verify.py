"""Independent verification of staging/ against the three inputs (does not reuse the C# merge code).

usage: python verify.py --workspace W        (build.py runs it on the raw merge, before applying hooks)

For every file: what the three-way rule says the result must contain, compared with what was written.
  copy/take   bytes equal the chosen source (take + drop_entries: entries equal the source minus dropped ones;
              every fragment must match at least one entry)
  regulation  every row/field of every param (text dumps), names included
  tae         every animation signature and TAE header
  bnd         every entry hash (FMG entries both sides changed are listed, not byte-checked)
  behavior    semantic check with indices resolved to names: KEEP untouched, MOVE's objects and changes
              present, tables = KEEP + MOVE tail, state-ID remaps and wrapper nesting as reported
  nameid      base entries unchanged, KEEP numbering unchanged, every added name present once
  text3       no conflict markers; every line A and B changed against the base is in the result (difflib, not
              git): line counts = base + A's changes + B's changes, and each changed block appears contiguously
  hooks       files hooks/post_merge.py changed are checked on their pre-hook copy (reports/prehook/); the hook
              diff (reports/hooks.diff) must consist of labelled hunks (`-- merge ...`), one per patch() call
After a build, staging files must still have the hashes the build recorded.
Writes reports/VERIFY.md; exit code 1 when anything is wrong.
"""
import argparse
import csv
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__
from kit import Workspace, base_path, load_json, sha256  # noqa: E402
from text_merge import line_opcodes, read_lines, read_nameid, read_text  # noqa: E402

csv.field_size_limit(1 << 30)
EVENT_FIELDS = {'m_eventId', 'm_enterEventId', 'm_exitEventId', 'm_endOfClipEventId'}
SINGLETONS = {'hkbBehaviorGraphData', 'hkbBehaviorGraphStringData', 'hkbVariableValueSet'}


def decide(has_base, p_eq_q, p_eq_b, q_eq_b):
    if p_eq_q or (has_base and q_eq_b):
        return 'p'
    if has_base and p_eq_b:
        return 'q'
    return 'conflict'


def occ_keys(items, key):
    seen, out = defaultdict(int), {}
    for it in items:
        k = key(it)
        out[(k, seen[k])] = it
        seen[k] += 1
    return out


# ---------- regulation ----------
def load_params(d):
    out = {}
    for f in Path(d).glob('*.tsv'):
        if f.name.startswith('_'):
            continue
        with open(f, encoding='utf-8', newline='') as fh:
            rows = list(csv.reader(fh, delimiter='\t'))
        out[f.stem] = (rows[0], occ_keys([(int(r[0]), r[1], tuple(r[2:])) for r in rows[1:] if r], lambda r: r[0]))
    return out


def verify_regulation(ws, rel, spec, e, names, xpath):
    errs = []
    prim = spec.get('primary', 'a')
    oth = 'b' if prim == 'a' else 'a'
    label = spec.get(f'label_{oth}', names[oth])
    res = spec.get('resolve', {})
    dumps = {}
    base = base_path(ws, rel, spec, e)
    for tag, path in (('p', e[prim]), ('q', e[oth]), ('b', base), ('x', xpath)):
        dumps[tag] = {} if path == '-' else load_params(ws.dump('param', path))
    for param, (hdr, X) in dumps['x'].items():
        P, Q, B = (dumps[t].get(param, (None, {}))[1] for t in ('p', 'q', 'b'))
        exp = dict(P)
        for key in set(Q) | set(B):
            p, q, b = P.get(key), Q.get(key), B.get(key)
            rk = f'{param}/{key[0]}' + (f'#{key[1]}' if key[1] else '')
            if q is None:
                if p is not None and b is not None and p[2] == b[2]:
                    exp.pop(key)
                continue
            if b is not None and q[2] == b[2]:
                continue
            if p is None:
                exp[key] = (q[0], q[1] or label, q[2])
                continue
            if p[2] == q[2]:
                continue
            if b is not None and p[2] == b[2]:
                exp[key] = (p[0], p[1] or q[1] or b[1], q[2])
                continue
            vals = list(p[2])
            for i, field in enumerate(hdr[2:]):
                pv, qv, bv = p[2][i], q[2][i], b[2][i] if b else None
                d = decide(b is not None, pv == qv, pv == bv, qv == bv)
                if d == 'conflict':
                    side = res.get(f'{rk}/{field}') or res.get(rk)
                    d = None if side is None else ('p' if side == prim else 'q')
                if d == 'q':
                    vals[i] = qv
                elif d is None:
                    errs.append(f'{rk}/{field}: unresolved conflict but a file was written')
            exp[key] = (p[0], p[1], tuple(vals))
        if set(exp) != set(X):
            errs.append(f'{param}: rows differ (missing {sorted(set(exp) - set(X))[:5]}, extra {sorted(set(X) - set(exp))[:5]})')
        for key in set(exp) & set(X):
            if exp[key][1:] != X[key][1:]:
                errs.append(f'{param}/{key[0]}: row content or name differs from the three-way expectation')
    return errs, [f'{sum(len(v[1]) for v in dumps["x"].values())} rows in {len(dumps["x"])} params checked']


# ---------- TAE / BND ----------
def tae_dump(ws, path):
    anims, heads = [], {}
    for line in ws.dump('tae', path).read_text(encoding='utf-8').splitlines():
        o = json.loads(line)
        if o['kind'] == 'tae':
            heads[o['entry'].lower()] = (o['taeId'], o['flags'], o['skeleton'], o['sib'])
        else:
            anims.append(o)
    return occ_keys(anims, lambda o: (o['entry'].lower(), o['id'])), heads


def verify_tae(ws, rel, spec, e, names, xpath):
    prim = spec.get('primary', 'a')
    oth = 'b' if prim == 'a' else 'a'
    res, errs = spec.get('resolve', {}), []
    base = base_path(ws, rel, spec, e)
    (P, HP), (Q, HQ), (X, HX) = tae_dump(ws, e[prim]), tae_dump(ws, e[oth]), tae_dump(ws, xpath)
    B, HB = tae_dump(ws, base) if base != '-' else ({}, {})
    exp = {k: v['sig'] for k, v in P.items()}
    for key in set(Q) | set(B):
        p, q, b = (d.get(key, {}).get('sig') for d in (P, Q, B))
        if q is None:
            if p is not None and b is not None and p == b:
                exp.pop(key)
            continue
        if b is not None and q == b:
            continue
        if p is None:
            exp[key] = q
            continue
        d = decide(b is not None, p == q, p == b, q == b)
        if d == 'conflict':
            (entry, aid), occ = key
            side = res.get(f'{entry}/{aid}' + (f'#{occ}' if occ else ''))
            d = None if side is None else ('p' if side == prim else 'q')
        if d == 'q':
            exp[key] = q
        elif d is None:
            errs.append(f'{key}: unresolved conflict but a file was written')
    got = {k: v['sig'] for k, v in X.items()}
    if exp != got:
        diff = [k for k in set(exp) | set(got) if exp.get(k) != got.get(k)]
        errs.append(f'{len(diff)} animations differ from the three-way expectation, e.g. {sorted(diff)[:5]}')
    for entry, hx in HX.items():
        hp, hq, hb = HP.get(entry), HQ.get(entry), HB.get(entry)
        want = hp if hp is not None else hq
        if hp is not None and hq is not None and hb is not None:
            want = tuple(q if p == b else p for p, q, b in zip(hp, hq, hb))
        if hx != want:
            errs.append(f'{entry}: TAE header {hx} != expected {want}')
    return errs, [f'{len(got)} animations in {len(HX)} TAE files checked']


def bnd_list(ws, path):
    rows = [r.split('\t') for r in ws.dump('bnd', path).read_text(encoding='utf-8').splitlines()[2:]]
    return {r[1].lower(): (int(r[0]), r[4]) for r in rows if len(r) >= 5}


def verify_bnd(ws, rel, spec, e, names, xpath):
    prim = spec.get('primary', 'a')
    oth = 'b' if prim == 'a' else 'a'
    res, errs, notes = spec.get('resolve', {}), [], []
    base = base_path(ws, rel, spec, e)
    P, Q, X = bnd_list(ws, e[prim]), bnd_list(ws, e[oth]), bnd_list(ws, xpath)
    B = bnd_list(ws, base) if base != '-' else {}
    exp = dict(P)
    for name in set(Q) | set(B):
        p, q, b = P.get(name), Q.get(name), B.get(name)
        if q is None:
            if p is not None and b is not None and p[1] == b[1]:
                exp.pop(name)
            continue
        if b is not None and q[1] == b[1]:
            continue
        if p is None:
            if b is None:
                exp[name] = q
            continue
        d = decide(b is not None, p[1] == q[1], b is not None and p[1] == b[1], b is not None and q[1] == b[1])
        short = name.replace('/', '\\').split('\\')[-1]
        if d == 'conflict':
            if short.endswith('.fmg'):
                notes.append(f'{short}: FMG merged per text ID (content checked by the tool, not here)')
                exp[name] = X.get(name)
                continue
            side = res.get(short)
            d = None if side is None else ('p' if side == prim else 'q')
        if d == 'q':
            exp[name] = q
        elif d is None:
            errs.append(f'{short}: unresolved conflict but a file was written')
    if exp != X:
        diff = sorted(k for k in set(exp) | set(X) if exp.get(k) != X.get(k))
        errs.append(f'{len(diff)} entries differ from the three-way expectation, e.g. {diff[:5]}')
    ids = defaultdict(list)
    for n, (i, _) in X.items():
        ids[i].append(n)
    errs += [f'BND ID {i} used by {v}' for i, v in ids.items() if len(v) > 1]
    return errs, notes + [f'{len(X)} entries checked']


# ---------- behavior ----------
def beh_load(ws, path):
    prefix = ws.dump('beh', path)
    nodes = {}
    for line in Path(str(prefix) + '.nodes.jsonl').read_text(encoding='utf-8').splitlines():
        o = json.loads(line)
        nodes[o['key']] = o
    return nodes, json.loads(Path(str(prefix) + '.tables.json').read_text(encoding='utf-8'))


def resolver(t):
    ev, var, anim = t.get('eventNames') or [], t.get('variableNames') or [], t.get('animationNames') or []

    def res(v, ptype=None, field=None, owner=None):
        if isinstance(v, dict):
            tp = v.get('$type', ptype)
            return {k: res(x, tp, k, v) for k, x in v.items()}
        if isinstance(v, list):
            return [res(x, ptype, field, owner) for x in v]
        if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer():
            i = int(v)
            if (field in EVENT_FIELDS or (field == 'm_id' and ptype in ('hkbEventProperty', 'hkbEventBase', 'hkbEvent'))) and 0 <= i < len(ev):
                return 'EV:' + ev[i]
            if field == 'm_variableIndex' and owner and owner.get('m_bindingType') == 'BINDING_TYPE_VARIABLE' and 0 <= i < len(var):
                return 'VAR:' + var[i]
            if field == 'm_animationInternalId' and 0 <= i < len(anim):
                return 'ANIM:' + anim[i]
        return v
    return res


def map_to_state(v, smap):
    """Applies a state-ID map to m_toStateId values inside transition objects/lists."""
    if isinstance(v, dict):
        return {k: (smap.get(str(int(x)), x) if k == 'm_toStateId' and isinstance(x, (int, float)) else map_to_state(x, smap)) for k, x in v.items()}
    if isinstance(v, list):
        return [map_to_state(x, smap) for x in v]
    return v


def verify_behavior(ws, rel, spec, e, names, xpath):
    keep = spec.get('keep', 'a')
    move = 'b' if keep == 'a' else 'a'
    rep = load_json(ws.p('reports', rel.replace('/', '__') + '.json'), {})
    info = rep.get('stats', {}).get('behavior', {})
    maps, wraps = info.get('stateIdMaps', {}), info.get('wraps', [])
    B, TB = beh_load(ws, base_path(ws, rel, spec, e))
    K, TK = beh_load(ws, e[keep])
    M, TM = beh_load(ws, e[move])
    X, TX = beh_load(ws, xpath)
    rB, rK, rM, rX = resolver(TB), resolver(TK), resolver(TM), resolver(TX)
    errs = []
    for t in TB:
        if (TX.get(t) or []) != (TK.get(t) or []) + (TM.get(t) or [])[len(TB.get(t) or []):]:
            errs.append(f'table {t}: merged != KEEP + MOVE tail')
    move_new = [k for k in M if k not in B]
    move_mod = {k for k in B if k in M and B[k]['fields'] != M[k]['fields']}
    if len(X) != len(K) + len(move_new):
        errs.append(f'object count {len(X)} != KEEP {len(K)} + MOVE new {len(move_new)}')
    wrap_by_slot = {w['slot']: w for w in wraps}
    wrap_keep_nodes = {w[x] for w in wraps for x in ('outer', 'inner', 'holder') if w.get(x)}
    for k, o in K.items():
        if k not in X:
            errs.append(f'KEEP object missing: {k}')
        elif k not in move_mod and k not in SINGLETONS and k not in wrap_keep_nodes and o['fields'] != X[k]['fields']:
            errs.append(f'KEEP object changed although MOVE did not touch it: {k}')
    # state machine of every MOVE-new state (for stateId maps)
    sm_of = {}
    for k, o in M.items():
        if o['type'] == 'hkbStateMachine':
            for ref in o['fields'].get('m_states') or []:
                sm_of.setdefault(ref[1:], k)
    for k in move_new:
        if k not in X:
            errs.append(f'MOVE object missing: {k}')
            continue
        want = rM(M[k]['fields'])
        smap = maps.get(sm_of.get(k, ''), {})
        if smap and M[k]['type'] == 'hkbStateMachine.StateInfo':
            want = dict(want)
            want['m_stateId'] = smap.get(str(want['m_stateId']), want['m_stateId'])
            want['m_transitions'] = map_to_state(want.get('m_transitions'), smap)
        for w in wraps:
            if w.get('holder', w['outer']) == k:
                want = json.loads(json.dumps(want).replace(json.dumps('@' + w['original']), json.dumps('@' + w['inner'])))
        if want != rX(X[k]['fields']):
            errs.append(f'MOVE object differs after index resolution: {k}')

    def expect(b, m, k, mr, kr, path, smap):
        """Expected merged value (index-resolved). Whether a side changed something is decided on RAW values:
        a base index past the end of the base table can resolve to a name in a longer table without any change."""
        if b == m:
            return kr
        if isinstance(m, list) and isinstance(b, list) and isinstance(k, list) and len(m) >= len(b) <= len(k):
            out = [expect(b[i], m[i], k[i], mr[i], kr[i], f'{path}[{i}]', smap) for i in range(len(b))] + kr[len(b):]
            tail = mr[len(b):]
            return out + (map_to_state(tail, smap) if smap else tail)
        if isinstance(m, dict) and isinstance(b, dict) and isinstance(k, dict) and m.get('$type') == b.get('$type') and '$type' in m:
            return {f: expect(b.get(f), m.get(f), k.get(f), mr.get(f), kr.get(f), f'{path}.{f}', smap) for f in m}
        if k == b:
            return mr
        w = wrap_by_slot.get(path)
        if w:
            return '@' + w['outer']
        return {'__conflict__': path}
    for k in move_mod:
        if k in SINGLETONS:
            continue
        smap = maps.get(k, {})
        fb, fm, fk = B[k]['fields'], M[k]['fields'], K[k]['fields']
        mr, kr = rM(fm), rK(fk)
        want = {f: expect(fb.get(f), fm.get(f), fk.get(f), mr.get(f), kr.get(f), f'{k}.{f}',
                          smap if f == 'm_wildcardTransitions' else {}) for f in fm}
        if want != rX(X[k]['fields']):
            errs.append(f'MOVE change to base object not reproduced: {k}')
    for k, o in X.items():
        if o['type'] == 'hkbStateMachine':
            ids = defaultdict(set)
            for ref in o['fields'].get('m_states') or []:
                ids[X[ref[1:]]['fields']['m_stateId']].add(ref)
            dup = [i for i, r in ids.items() if len(r) > 1]
            if dup:
                errs.append(f'{k}: duplicate stateIds {dup}')
    return errs, [f'{len(X)} objects; MOVE new {len(move_new)}, MOVE-changed base objects {len(move_mod)}; '
                  f'stateId maps {maps}; wraps {len(wraps)}']


# ---------- text ----------
def verify_nameid(ws, rel, spec, e, names, xpath):
    keep = spec.get('keep', 'a')
    other = 'b' if keep == 'a' else 'a'
    c = read_nameid(base_path(ws, rel, spec, e))
    k, o, x = read_nameid(e[keep]), read_nameid(e[other]), read_nameid(xpath)
    errs = []
    if x[:len(c)] != c:
        errs.append('base entries changed')
    if x[len(c):len(k)] != k[len(c):]:
        errs.append('KEEP side numbering changed')
    if sorted(set(x)) != sorted(set(c) | set(k) | set(o)) or len(x) != len(set(x)):
        errs.append('added names missing or duplicated')
    return errs, [f'{len(x)} entries']


def verify_text3(ws, rel, spec, e, names, xpath):
    """Independent of git merge-file and of its alignment: every line either side changed is accounted for."""
    t, _ = read_text(xpath)
    bad = [m for m in ('<<<<<<< A', '>>>>>>> B', '||||||| BASE') if m in t]
    if bad:
        return [f'conflict markers left: {bad}'], []
    base, x = read_lines(base_path(ws, rel, spec, e)), t.splitlines()
    side = {s: read_lines(e[s]) for s in ('a', 'b')}
    hunks = {s: {(i1, i2, tuple(side[s][j1:j2])) for _, i1, i2, j1, j2 in line_opcodes(base, side[s])} for s in ('a', 'b')}
    want = Counter(base)
    for i1, i2, new in hunks['a'] | hunks['b']:  # a change both sides made identically counts once
        want.subtract(base[i1:i2])
        want.update(new)
    got, errs = Counter(x), []
    off = {line: got[line] - want[line] for line in set(want) | set(got) if got[line] != want[line]}
    if off:
        extra, lost = [k for k, d in off.items() if d > 0], [k for k, d in off.items() if d < 0]
        errs.append(f'line accounting: {sum(d for d in off.values() if d > 0)} line(s) neither side has (e.g. {extra[:2]}), '
                    f'{-sum(d for d in off.values() if d < 0)} line(s) missing (e.g. {lost[:2]})')
    joined = '\n' + '\n'.join(x) + '\n'
    for s in ('a', 'b'):
        missing = [i1 + 1 for i1, _, new in sorted(hunks[s]) if new and '\n' + '\n'.join(new) + '\n' not in joined]
        if missing:
            errs.append(f"{names[s]}'s changed block(s) at base line(s) {missing[:5]} not found contiguously in the result")
    return errs, [f'changed blocks: {names["a"]} {len(hunks["a"])}, {names["b"]} {len(hunks["b"])}; line counts = base + both']


def verify_copy(ws, rel, src, xpath):
    return ([] if sha256(src) == sha256(xpath) else [f'bytes differ from {src}']), []


def verify_take_drop(ws, rel, spec, src, xpath):
    entries = bnd_list(ws, src)
    hits = {d: [n for n in entries if d.lower() in n] for d in spec['drop_entries']}
    dropped = {n for h in hits.values() for n in h}
    errs = [f'drop fragment "{d}" matches no entry of {Path(src).name}' for d, h in hits.items() if not h]
    if {n: v for n, v in entries.items() if n not in dropped} != bnd_list(ws, xpath):
        errs.append('entries differ from the source minus the dropped ones')
    short = sorted(n.replace('/', '\\').split('\\')[-1] for n in dropped)
    return errs, [f'dropped {len(dropped)} of {len(entries)}: {", ".join(short)}']


# ---------- hooks ----------
LUA_LABEL = re.compile(r'--\s*merge\b')


def under_test(ws, rel, build):
    """The file the three-way rules describe: its pre-hook copy when hooks/post_merge.py changed it."""
    pre = ws.p('reports', 'prehook', *rel.split('/'))
    return pre if rel in build.get('hook_patched', []) and pre.exists() else ws.p('staging', *rel.split('/'))


def check_hooks(ws, build):
    """Writes reports/hooks.diff; every hunk must add a labelled line, one hunk per patch() call.
    Returns (errors, markdown lines for VERIFY.md, {file: (hunks, lines added, lines removed)})."""
    errs, rows, diff, total, stats = [], [], [], 0, {}
    for rel in build.get('hook_patched', []):
        pre, post = ws.p('reports', 'prehook', *rel.split('/')), ws.p('staging', *rel.split('/'))
        if not pre.exists():
            rows.append(f'| `{rel}` | not a text file: no diff, not re-verified | |')
            continue
        old, new = read_lines(pre), read_lines(post)
        ops = line_opcodes(old, new)
        label = LUA_LABEL if rel.lower().endswith(('.hks', '.lua')) else re.compile('merge', re.I)
        bare = [i1 + 1 for _, i1, _, j1, j2 in ops if not any(label.search(x) for x in new[j1:j2])]
        if bare:
            errs.append(f'{rel}: hook change(s) at pre-hook line(s) {bare} carry no `-- merge ...` label')
        total += len(ops)
        stats[rel] = (len(ops), sum(j2 - j1 for *_, j1, j2 in ops), sum(i2 - i1 for _, i1, i2, *_ in ops))
        rows.append(f'| `{rel}` | {stats[rel][0]} hunk(s), +{stats[rel][1]} / -{stats[rel][2]} lines | '
                    f'{", ".join(str(j1 + 1) for *_, j1, _ in ops)} |')
        diff += difflib.unified_diff(old, new, f'prehook/{rel}', f'staging/{rel}', lineterm='')
    calls = build.get('hook_patch_calls') or 0
    if calls and calls != total:
        errs.append(f'the hook made {total} hunk(s) with {calls} patch() call(s): each patch must be one contiguous, labelled edit')
    ws.p('reports', 'hooks.diff').write_text('\n'.join(diff) + '\n', encoding='utf-8')
    lines = ['', '## Hook changes (hooks/post_merge.py; full diff in reports/hooks.diff)', '',
             '| file | change | changed lines (after the hook) |', '|---|---|---|'] + rows
    lines += ['', f'{"FAIL: " + "; ".join(errs) if errs else "ok"} - {total} hunk(s); {calls} patch() call(s) reported by the hook']
    return errs, lines, stats


def run(ws):
    plan, inv = ws.plan, load_json(ws.p('inventory.json'))
    names = {'a': plan['a']['name'], 'b': plan['b']['name']}
    build = load_json(ws.p('reports', 'BUILD.json'))
    fns = {'regulation': verify_regulation, 'tae': verify_tae, 'bnd': verify_bnd, 'behavior': verify_behavior,
           'nameid': verify_nameid, 'text3': verify_text3}
    results = []
    for item in build['files']:
        rel, how = item['rel'], item['how']
        if how == 'excluded':
            results.append((rel, how, [], ['not in staging']))
            continue
        e = inv['entries'][rel.lower()]
        spec = plan['files'].get(rel, {})
        staged, x = ws.p('staging', *rel.split('/')), under_test(ws, rel, build)
        hooked = rel in build.get('hook_patched', [])
        if hooked and x == staged:
            errs, notes = [], ['changed by the hook; not a text file, so only the build verified it (before the hook)']
        elif how in fns:
            errs, notes = fns[how](ws, rel, spec, e, names, x)
        elif how == 'copy' or (how == 'take' and not spec.get('drop_entries')):
            errs, notes = verify_copy(ws, rel, item['source'], x)
        elif how == 'take':
            errs, notes = verify_take_drop(ws, rel, spec, item['source'], x)
        else:
            errs, notes = [], [f'{how}: not verified automatically']
        if hooked and x != staged:
            notes.append('checked on the pre-hook copy')
        if item.get('sha256') and staged.exists() and sha256(staged) != item['sha256']:
            errs.append('staging file changed since the build')
        results.append((rel, how, errs, notes))
        print(f'{"FAIL" if errs else "ok  "} {how:10} {rel}' + ''.join(f'\n       {m}' for m in errs[:10]))
    lines = ['# Verification', '', '| file | strategy | result | notes |', '|---|---|---|---|']
    for rel, how, errs, notes in results:
        lines.append(f'| `{rel}` | {how} | {"FAIL: " + "; ".join(errs[:5]) if errs else "ok"} | {"; ".join(notes)} |')
    n = sum(len(r[2]) for r in results)
    if 'hook_patched' in build:
        herrs, hlines, _ = check_hooks(ws, build)
        lines += hlines
        n += len(herrs)
    ws.p('reports', 'VERIFY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return n


def append_hooks(ws):
    """build.py, after the hook ran: the same hook section a standalone verify.py run writes."""
    errs, lines, stats = check_hooks(ws, load_json(ws.p('reports', 'BUILD.json')))
    with open(ws.p('reports', 'VERIFY.md'), 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return errs, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    n = run(Workspace(ap.parse_args().workspace))
    print(f'{n} problem(s); see reports/VERIFY.md')
    sys.exit(1 if n else 0)


if __name__ == '__main__':
    main()
