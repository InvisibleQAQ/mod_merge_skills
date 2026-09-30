"""Independent verification of staging/ against the three inputs (does not reuse the C# merge code).

usage: python verify.py --workspace W        (build.py runs it automatically before applying hooks)

For every file: what the three-way rule says the result must contain, compared with what was written.
  copy/take   bytes equal the chosen source (take + drop_entries: entries equal the source minus dropped ones)
  regulation  every row/field of every param (text dumps), names included
  tae         every animation signature and TAE header
  bnd         every entry hash (FMG entries both sides changed are listed, not byte-checked)
  behavior    semantic check with indices resolved to names: KEEP untouched, MOVE's objects and changes
              present, tables = KEEP + MOVE tail, state-ID remaps and wrapper nesting as reported
  nameid      base entries unchanged, KEEP numbering unchanged, every added name present once
  text3       no conflict markers
Writes reports/VERIFY.md; exit code 1 when anything is wrong.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from kit import Workspace, base_path, load_json, sha256
from text_merge import read_nameid, read_text

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


def verify_regulation(ws, rel, spec, e, names):
    kit, errs = ws.kit, []
    prim = spec.get('primary', 'a')
    oth = 'b' if prim == 'a' else 'a'
    label = spec.get(f'label_{oth}', names[oth])
    res = spec.get('resolve', {})
    dumps = {}
    base = base_path(ws, rel, spec, e)
    for tag, path in (('p', e[prim]), ('q', e[oth]), ('b', base), ('x', ws.p('staging', rel))):
        if path == '-':
            dumps[tag] = {}
            continue
        d = ws.p('dumps', 'verify', 'reg_' + tag)
        ws.ermerge('param-dump', path, kit['defs'], d, quiet=True)
        dumps[tag] = load_params(d)
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
def tae_dump(ws, path, tag):
    out = ws.p('dumps', 'verify', f'tae_{tag}.jsonl')
    ws.ermerge('tae-dump', path, out, quiet=True)
    anims, heads = [], {}
    for line in out.read_text(encoding='utf-8').splitlines():
        o = json.loads(line)
        if o['kind'] == 'tae':
            heads[o['entry'].lower()] = (o['taeId'], o['flags'], o['skeleton'], o['sib'])
        else:
            anims.append(o)
    return occ_keys(anims, lambda o: (o['entry'].lower(), o['id'])), heads


def verify_tae(ws, rel, spec, e, names):
    prim = spec.get('primary', 'a')
    oth = 'b' if prim == 'a' else 'a'
    res, errs = spec.get('resolve', {}), []
    base = base_path(ws, rel, spec, e)
    (P, HP), (Q, HQ), (X, HX) = tae_dump(ws, e[prim], 'p'), tae_dump(ws, e[oth], 'q'), tae_dump(ws, ws.p('staging', rel), 'x')
    B, HB = tae_dump(ws, base, 'b') if base != '-' else ({}, {})
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


def bnd_list(ws, path, tag):
    out = ws.p('dumps', 'verify', f'bnd_{tag}.tsv')
    ws.ermerge('bnd-list', path, out, quiet=True)
    rows = [r.split('\t') for r in out.read_text(encoding='utf-8').splitlines()[2:]]
    return {r[1].lower(): (int(r[0]), r[4]) for r in rows if len(r) >= 5}


def verify_bnd(ws, rel, spec, e, names):
    prim = spec.get('primary', 'a')
    oth = 'b' if prim == 'a' else 'a'
    res, errs, notes = spec.get('resolve', {}), [], []
    base = base_path(ws, rel, spec, e)
    P, Q, X = bnd_list(ws, e[prim], 'p'), bnd_list(ws, e[oth], 'q'), bnd_list(ws, ws.p('staging', rel), 'x')
    B = bnd_list(ws, base, 'b') if base != '-' else {}
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
def beh_load(ws, path, tag):
    prefix = ws.p('dumps', 'verify', f'beh_{tag}')
    ws.ermerge('beh-dump', path, prefix, quiet=True)
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


def verify_behavior(ws, rel, spec, e, names):
    keep = spec.get('keep', 'a')
    move = 'b' if keep == 'a' else 'a'
    rep = load_json(ws.p('reports', rel.replace('/', '__') + '.json'), {})
    info = rep.get('stats', {}).get('behavior', {})
    maps, wraps = info.get('stateIdMaps', {}), info.get('wraps', [])
    B, TB = beh_load(ws, base_path(ws, rel, spec, e), 'b')
    K, TK = beh_load(ws, e[keep], 'k')
    M, TM = beh_load(ws, e[move], 'm')
    X, TX = beh_load(ws, ws.p('staging', rel), 'x')
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
def verify_nameid(ws, rel, spec, e, names):
    keep = spec.get('keep', 'a')
    other = 'b' if keep == 'a' else 'a'
    c = read_nameid(base_path(ws, rel, spec, e))
    k, o, x = read_nameid(e[keep]), read_nameid(e[other]), read_nameid(ws.p('staging', rel))
    errs = []
    if x[:len(c)] != c:
        errs.append('base entries changed')
    if x[len(c):len(k)] != k[len(c):]:
        errs.append('KEEP side numbering changed')
    if sorted(set(x)) != sorted(set(c) | set(k) | set(o)) or len(x) != len(set(x)):
        errs.append('added names missing or duplicated')
    return errs, [f'{len(x)} entries']


def verify_text3(ws, rel, spec, e, names):
    t, _ = read_text(ws.p('staging', rel))
    bad = [m for m in ('<<<<<<< A', '>>>>>>> B', '||||||| BASE') if m in t]
    return ([f'conflict markers left: {bad}'] if bad else []), []


def verify_copy(ws, rel, src):
    return ([] if sha256(src) == sha256(ws.p('staging', rel)) else [f'bytes differ from {src}']), []


def run(ws):
    plan, inv = ws.plan, load_json(ws.p('inventory.json'))
    names = {'a': plan['a']['name'], 'b': plan['b']['name']}
    build = load_json(ws.p('reports', 'BUILD.json'))
    fns = {'regulation': verify_regulation, 'tae': verify_tae, 'bnd': verify_bnd, 'behavior': verify_behavior,
           'nameid': verify_nameid, 'text3': verify_text3}
    results = []
    for item in build['files']:
        rel, how = item['rel'], item['how']
        e = inv['entries'][rel.lower()]
        spec = plan['files'].get(rel, {})
        if rel in build.get('hook_patched', []) and how in ('copy', 'take'):
            errs, notes = [], ['changed by hooks/post_merge.py after the build verified it']
        elif how in fns:
            errs, notes = fns[how](ws, rel, spec, e, names)
        elif how == 'copy' or (how == 'take' and not spec.get('drop_entries')):
            errs, notes = verify_copy(ws, rel, item['source'])
        elif how == 'take':
            src = bnd_list(ws, item['source'], 'src')
            drop = [d.lower() for d in spec['drop_entries']]
            want = {n: v for n, v in src.items() if not any(d in n for d in drop)}
            errs, notes = ([] if want == bnd_list(ws, ws.p('staging', rel), 'x') else ['entries differ from source minus dropped']), \
                          [f'dropped {len(src) - len(want)} entries']
        else:
            errs, notes = [], [f'{how}: not verified automatically']
        results.append((rel, how, errs, notes))
        print(f'{"FAIL" if errs else "ok  "} {how:10} {rel}' + ''.join(f'\n       {x}' for x in errs[:10]))
    lines = ['# Verification', '', '| file | strategy | result | notes |', '|---|---|---|---|']
    for rel, how, errs, notes in results:
        lines.append(f'| `{rel}` | {how} | {"FAIL: " + "; ".join(errs[:5]) if errs else "ok"} | {"; ".join(notes)} |')
    ws.p('reports', 'VERIFY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return sum(len(r[2]) for r in results)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    n = run(Workspace(ap.parse_args().workspace))
    print(f'{n} problem(s); see reports/VERIFY.md')
    sys.exit(1 if n else 0)


if __name__ == '__main__':
    main()
