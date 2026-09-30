// beh-dump  <behbnd|hkx> <outPrefix>      -> <outPrefix>.nodes.jsonl (key,type,parent,fields) + <outPrefix>.tables.json
// beh-merge <base.behbnd> <keep.behbnd> <move.behbnd> <out.behbnd> [--wrap-order move-outer|keep-outer]
//           [--report rep.json] [--dry-run]
// The KEEP side's graph is the result's base: none of its event/variable/animation indices or state IDs move.
// Choose as KEEP the mod whose scripts or DLL hard-code behavior indices (e.g. compare MasterActiveState with
// a state ID); the MOVE side's changes relative to the base are transplanted onto it:
//   - new objects are attached; references to base objects are redirected to KEEP's copies;
//   - lists MOVE appended to (states, wildcard transitions, selector children, blender children, the event /
//     variable / animation-name tables) get MOVE's tail after KEEP's;
//   - slots MOVE repointed are repointed in KEEP unless KEEP repointed them too; if both wrapped the same
//     original in a new selector, the wrappers are nested (--wrap-order, default: MOVE outer);
//   - MOVE's event ids, variable indices and m_animationInternalId values past the base tables are shifted by
//     KEEP's growth; MOVE's new states whose stateId collides with KEEP's in the same state machine get new IDs.
// Anything else both sides changed is a conflict: nothing is written and the report lists it.
using System.Collections;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using SoulsFormats;

static class BehCommands
{
    public static int Dump(string path, string outPrefix)
    {
        var g = new Graph(Graph.LoadBehaviorHkx(path, out _, out _, out _));
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPrefix + ".x")));
        using (var w = new StreamWriter(outPrefix + ".nodes.jsonl", false, new UTF8Encoding(false)))
            foreach (var o in g.Order)
                w.WriteLine(new JsonObject
                {
                    ["key"] = g.Keys[o], ["type"] = R.TypeName(o.GetType()),
                    ["parent"] = g.Parents.TryGetValue(o, out var p) ? p : null, ["fields"] = g.FieldsJson(o),
                }.ToJsonString());
        var data = g.ByKey.TryGetValue("hkbBehaviorGraphData", out var d) ? d : null;
        var sd = g.StringData;
        var tables = new JsonObject();
        JsonNode F(object o, string f) => o == null ? null : g.Ser(o.GetType().GetField(f)?.GetValue(o));
        foreach (var f in new[] { "m_eventNames", "m_variableNames", "m_animationNames", "m_characterPropertyNames", "m_attributeNames" })
            tables[f.Substring(2)] = F(sd, f);
        foreach (var f in new[] { "m_eventInfos", "m_variableInfos", "m_variableBounds", "m_characterPropertyInfos", "m_attributeDefaults" })
            tables[f.Substring(2)] = F(data, f);
        File.WriteAllText(outPrefix + ".tables.json", tables.ToJsonString(), new UTF8Encoding(false));
        Console.WriteLine($"{path}: {g.Order.Count} keyed objects");
        return 0;
    }

    public static int Merge(Args args)
    {
        var baseG = new Graph(Graph.LoadBehaviorHkx(args.P(0), out var baseBnd, out _, out _));
        var keepG = new Graph(Graph.LoadBehaviorHkx(args.P(1), out var keepBnd, out var dcx, out var keepEntry));
        var moveG = new Graph(Graph.LoadBehaviorHkx(args.P(2), out var moveBnd, out _, out _));
        bool moveOuter = args.Opt("--wrap-order", "move-outer") != "keep-outer";
        var m = new BehMerger(baseG, keepG, moveG, moveOuter);
        var rep = m.Run();
        // The other behbnd entries (project / character data) must not have been changed by MOVE.
        if (keepBnd != null && moveBnd != null && baseBnd != null)
            foreach (var mf in moveBnd.Files)
            {
                var bf = baseBnd.Files.FirstOrDefault(f => Util.EntryKey(f) == Util.EntryKey(mf));
                var kf = keepBnd.Files.FirstOrDefault(f => Util.EntryKey(f) == Util.EntryKey(mf));
                if (kf == keepEntry || (bf != null && Util.SameBytes(mf, bf))) continue;
                if (kf != null && bf != null && Util.SameBytes(kf, bf)) { kf.Bytes = mf.Bytes.ToArray(); m.Log($"{Util.ShortName(mf.Name)}: taken from MOVE"); }
                else if (kf == null || !Util.SameBytes(kf, mf)) rep.Conflict(Util.ShortName(mf.Name), "non-behavior entry of the behbnd changed by both sides");
            }
        string repPath = args.OptPath("--report");
        rep.Stats["behavior"] = m.Json;
        if (repPath != null) File.WriteAllLines(Path.ChangeExtension(repPath, ".log.txt"), m.LogLines, new UTF8Encoding(false));
        int code = rep.Finish(repPath);
        if (code != 0 || args.DryRun) return code;
        byte[] hkx = Graph.Write(keepG.Root);
        if (keepBnd == null) Util.Save(args.P(3), hkx);
        else { keepEntry.Bytes = hkx; Util.Save(args.P(3), keepBnd.Write(dcx)); }
        Console.WriteLine($"beh-merge -> {args.P(3)} (behavior hkx {hkx.Length} bytes)");
        return 0;
    }
}

sealed class BehMerger
{
    readonly Graph B, K, M;           // base, keep, move
    readonly bool moveOuter;
    readonly Report rep = new();
    public readonly List<string> LogLines = new();
    public readonly JsonObject Json = new();
    readonly HashSet<object> fixedUp = new(ReferenceEqualityComparer.Instance);
    readonly HashSet<object> ownedByBaseNodes = new(ReferenceEqualityComparer.Instance);
    readonly HashSet<object> sharedUnnamed = new(ReferenceEqualityComparer.Instance);
    readonly List<string> suspicious = new();
    readonly JsonArray wraps = new();
    int bEv, dEv, mEv, bVar, dVar, mVar, bAnim, dAnim, mAnim;

    static readonly HashSet<string> EventFields = new() { "m_eventId", "m_enterEventId", "m_exitEventId", "m_endOfClipEventId" };
    static readonly HashSet<string> EventIdOwners = new() { "hkbEventProperty", "hkbEventBase", "hkbEvent" };
    static readonly HashSet<string> StateFields = new() { "m_stateId", "m_toStateId", "m_fromNestedStateId", "m_toNestedStateId", "m_startStateId" };

    public BehMerger(Graph b, Graph k, Graph m, bool moveOuter) { B = b; K = k; M = m; this.moveOuter = moveOuter; }

    public void Log(string s) => LogLines.Add(s);

    public Report Run()
    {
        bEv = B.TableCount("m_eventNames"); dEv = K.TableCount("m_eventNames") - bEv; mEv = M.TableCount("m_eventNames") - bEv;
        bVar = B.TableCount("m_variableNames"); dVar = K.TableCount("m_variableNames") - bVar; mVar = M.TableCount("m_variableNames") - bVar;
        bAnim = B.TableCount("m_animationNames"); dAnim = K.TableCount("m_animationNames") - bAnim; mAnim = M.TableCount("m_animationNames") - bAnim;
        Log($"tables base/keep+/move+: events {bEv}/{dEv}/{mEv}, variables {bVar}/{dVar}/{mVar}, animation names {bAnim}/{dAnim}/{mAnim}");
        Json["shift"] = new JsonObject { ["events"] = dEv, ["variables"] = dVar, ["animations"] = dAnim, ["baseEvents"] = bEv, ["baseVariables"] = bVar, ["baseAnimations"] = bAnim };
        if (dEv < 0 || dVar < 0 || dAnim < 0 || mEv < 0 || mVar < 0 || mAnim < 0) { rep.Conflict("tables", "a side shrank a behavior table; unsupported"); return rep; }

        var moveNew = M.Order.Where(o => !B.ByKey.ContainsKey(M.Keys[o])).ToList();
        foreach (var o in moveNew)
            if (K.ByKey.ContainsKey(M.Keys[o])) rep.Conflict(M.Keys[o], "both sides added an object with this name");
        foreach (var k in B.ByKey.Keys) if (!K.ByKey.ContainsKey(k) || !M.ByKey.ContainsKey(k)) rep.Conflict(k, "base object removed by a side; unsupported");
        if (rep.Conflicts.Count > 0) return rep;
        Log($"MOVE new keyed objects: {moveNew.Count}");
        foreach (var o in M.Order.Where(o => B.ByKey.ContainsKey(M.Keys[o]))) CollectOwned(o);

        var plans = PlanStateIds();
        int modified = 0;
        foreach (var o in M.Order)
        {
            string key = M.Keys[o];
            if (!B.ByKey.TryGetValue(key, out var bo) || B.SigFields(bo) == M.SigFields(o)) continue;
            modified++;
            try { ApplyDelta(bo, o, K.ByKey[key], key); }
            catch (MergeConflict c) { rep.Conflict(c.Key, c.Message); }
        }
        Log($"MOVE-modified base objects applied: {modified}");
        ApplyStateIds(plans);
        CheckStateIds();

        var refs = CountRefs(M.Root);
        var shared = sharedUnnamed.Where(o => refs.TryGetValue(o, out var c) && c > 1).ToList();
        Log($"unnamed objects shared with base nodes and duplicated by the transplant: {shared.Count}"
            + string.Concat(shared.GroupBy(o => R.TypeName(o.GetType())).Select(g => $" {g.Key}x{g.Count()}")));
        foreach (var s in suspicious.Distinct()) { Log("SUSPICIOUS unmapped value in MOVE's new index range: " + s); }
        Json["suspicious"] = new JsonArray(suspicious.Distinct().Select(s => (JsonNode)s).ToArray());
        Json["moveNewObjects"] = moveNew.Count;
        Json["moveModifiedObjects"] = modified;
        Json["wraps"] = wraps;
        foreach (var l in LogLines) Console.WriteLine("  " + l);
        return rep;
    }

    sealed class MergeConflict : Exception { public string Key; public MergeConflict(string key, string msg) : base(msg) { Key = key; } }

    // ---------- state IDs ----------
    static IEnumerable<object> States(object sm) => ((IEnumerable)sm.GetType().GetField("m_states").GetValue(sm)).Cast<object>();
    static int StateId(object st) => Convert.ToInt32(st.GetType().GetField("m_stateId").GetValue(st));
    static int WildCount(object sm)
    {
        var w = sm.GetType().GetField("m_wildcardTransitions").GetValue(sm);
        return w == null ? 0 : ((IList)w.GetType().GetField("m_transitions").GetValue(w)).Count;
    }

    Dictionary<string, (Dictionary<int, int> map, int keepWild)> PlanStateIds()
    {
        var plans = new Dictionary<string, (Dictionary<int, int>, int)>();
        var jmaps = new JsonObject();
        foreach (var o in M.Order.Where(o => R.TypeName(o.GetType()) == "hkbStateMachine"))
        {
            string key = M.Keys[o];
            if (!B.ByKey.TryGetValue(key, out var bo)) continue;
            var baseIds = States(bo).Select(StateId).ToHashSet();
            var keepIds = States(K.ByKey[key]).Select(StateId).ToHashSet();
            var moveAdded = States(o).Select(StateId).Where(id => !baseIds.Contains(id)).Distinct().ToList();
            int next = keepIds.Concat(States(o).Select(StateId)).DefaultIfEmpty(0).Max() + 1;
            var map = new Dictionary<int, int>();
            foreach (int id in moveAdded) if (keepIds.Contains(id)) map[id] = next++;
            plans[key] = (map, WildCount(K.ByKey[key]));
            if (map.Count == 0) continue;
            Log($"stateId remap {key}: " + string.Join(", ", map.Select(p => $"{p.Key}->{p.Value}")));
            var jm = new JsonObject();
            foreach (var p in map) jm[p.Key.ToString()] = p.Value;
            jmaps[key] = jm;
        }
        Json["stateIdMaps"] = jmaps;
        return plans;
    }

    void ApplyStateIds(Dictionary<string, (Dictionary<int, int> map, int keepWild)> plans)
    {
        var done = new HashSet<object>(ReferenceEqualityComparer.Instance);
        foreach (var (key, plan) in plans)
        {
            if (plan.map.Count == 0) continue;
            var sm = K.ByKey[key];
            foreach (var st in States(sm))
            {
                if (!(M.Keys.TryGetValue(st, out var sk) && !B.ByKey.ContainsKey(sk)) || !done.Add(st)) continue;
                var f = st.GetType().GetField("m_stateId");
                if (plan.map.TryGetValue(StateId(st), out int nid)) f.SetValue(st, Convert.ChangeType(nid, f.FieldType));
                RemapTransitions(st.GetType().GetField("m_transitions").GetValue(st), 0, plan.map, sk);
            }
            RemapTransitions(sm.GetType().GetField("m_wildcardTransitions").GetValue(sm), plan.keepWild, plan.map, key + " wildcard");
        }
    }

    void RemapTransitions(object arr, int from, Dictionary<int, int> map, string where)
    {
        if (arr == null) return;
        var list = (IList)arr.GetType().GetField("m_transitions").GetValue(arr);
        for (int i = from; i < list.Count; i++)
        {
            object t = list[i];
            var f = t.GetType().GetField("m_toStateId");
            int to = Convert.ToInt32(f.GetValue(t));
            if (!map.TryGetValue(to, out int nto)) continue;
            f.SetValue(t, Convert.ChangeType(nto, f.FieldType));
            list[i] = t;
            Log($"  {where}[{i}] toStateId {to} -> {nto}");
        }
    }

    void CheckStateIds()
    {
        foreach (var o in K.Order.Where(o => R.TypeName(o.GetType()) == "hkbStateMachine"))
        {
            var dup = States(o).Distinct(ReferenceEqualityComparer.Instance).GroupBy(StateId).Where(g => g.Count() > 1).Select(g => g.Key).ToList();
            if (dup.Count > 0) rep.Conflict(K.Keys[o], "duplicate stateIds after merge: " + string.Join(",", dup));
        }
    }

    // ---------- transplanting MOVE objects ----------
    void CollectOwned(object o)
    {
        foreach (var f in R.Fields(o.GetType()))
        {
            var v = f.GetValue(o);
            IEnumerable<object> items = v is IList l ? l.Cast<object>() : new[] { v };
            foreach (var i in items)
                if (R.IsRefObject(i) && !M.Keys.ContainsKey(i) && ownedByBaseNodes.Add(i)) CollectOwned(i);
        }
    }

    static Dictionary<object, int> CountRefs(object root)
    {
        var refs = new Dictionary<object, int>(ReferenceEqualityComparer.Instance);
        var seen = new HashSet<object>(ReferenceEqualityComparer.Instance) { root };
        var stack = new Stack<object>(); stack.Push(root);
        while (stack.Count > 0)
        {
            var o = stack.Pop();
            foreach (var f in R.Fields(o.GetType()))
            {
                var v = f.GetValue(o);
                IEnumerable<object> items = v is IList l ? l.Cast<object>() : new[] { v };
                foreach (var i in items.Where(R.IsRefObject))
                {
                    refs[i] = refs.TryGetValue(i, out var c) ? c + 1 : 1;
                    if (seen.Add(i)) stack.Push(i);
                }
            }
        }
        return refs;
    }

    object MapRef(object m)
    {
        if (m != null && M.Keys.TryGetValue(m, out var k) && B.ByKey.ContainsKey(k)) return K.ByKey[k];
        return m;
    }

    object Transplant(object v)
    {
        if (R.IsScalar(v)) return v;
        if (R.IsStruct(v)) { object boxed = v; FixFields(boxed); return boxed; }
        var mapped = MapRef(v);
        if (ReferenceEquals(mapped, v) && fixedUp.Add(v))
        {
            if (!M.Keys.ContainsKey(v) && ownedByBaseNodes.Contains(v)) sharedUnnamed.Add(v);
            FixFields(v);
        }
        return mapped;
    }

    void FixFields(object o)
    {
        foreach (var f in R.Fields(o.GetType()))
        {
            var v = f.GetValue(o);
            if (v is IList list)
                for (int i = 0; i < list.Count; i++) list[i] = R.IsScalar(list[i]) ? Remap(o, f, list[i]) : Transplant(list[i]);
            else
                f.SetValue(o, R.IsScalar(v) ? Remap(o, f, v) : Transplant(v));
        }
    }

    object Remap(object owner, FieldInfo f, object v)
    {
        if (v == null || !v.GetType().IsPrimitive || v is bool || v is float || v is double) return v;
        long x = Convert.ToInt64(v);
        string n = f.Name, ot = R.TypeName(owner.GetType());
        object Shift(long d) => Convert.ChangeType(x + d, v.GetType());
        if (EventFields.Contains(n) || (n == "m_id" && EventIdOwners.Contains(ot))) return x >= bEv ? Shift(dEv) : v;
        if (n == "m_variableIndex" && ot == "hkbVariableBindingSet.Binding")
            return owner.GetType().GetField("m_bindingType").GetValue(owner).ToString() == "BINDING_TYPE_VARIABLE" && x >= bVar ? Shift(dVar) : v;
        if (n == "m_syncVariableIndex") return x >= bVar ? Shift(dVar) : v;
        if (n == "m_animationInternalId") return x >= bAnim ? Shift(dAnim) : v;
        if (StateFields.Contains(n)) return v;
        if ((x >= bEv && x < bEv + mEv) || (x >= bVar && x < bVar + mVar) || (x >= bAnim && x < bAnim + mAnim)) suspicious.Add($"{ot}.{n}={x}");
        return v;
    }

    // ---------- applying MOVE's changes to base objects ----------
    bool Keyed(Graph g, object v) => v != null && g.Keys.ContainsKey(v);

    void ApplyDelta(object b, object m, object k, string path)
    {
        if (b.GetType() != m.GetType() || k.GetType() != m.GetType()) throw new MergeConflict(path, "type changed");
        foreach (var f in R.Fields(m.GetType()))
        {
            object bv = f.GetValue(b), mv = f.GetValue(m), kv = f.GetValue(k);
            if (B.Sig(bv) == M.Sig(mv)) continue;
            string p = path + "." + f.Name;
            if (mv is IList ml)
            {
                var bl = (IList)bv; var kl = (IList)kv;
                if (ml.Count < bl.Count || kl.Count < bl.Count) throw new MergeConflict(p, "a side removed items from this list; unsupported");
                for (int i = 0; i < bl.Count; i++)
                    if (B.Sig(bl[i]) != M.Sig(ml[i])) kl[i] = ApplyOne(bl[i], ml[i], kl[i], m, f, $"{p}[{i}]");
                if (ml.Count > bl.Count)
                {
                    int before = kl.Count;
                    for (int i = bl.Count; i < ml.Count; i++) kl.Add(R.IsScalar(ml[i]) ? Remap(m, f, ml[i]) : Transplant(ml[i]));
                    Log($"{p}: appended {ml.Count - bl.Count} after KEEP's {before}");
                }
            }
            else f.SetValue(k, ApplyOne(bv, mv, kv, m, f, p));
        }
    }

    object ApplyOne(object bv, object mv, object kv, object mOwner, FieldInfo f, string p)
    {
        if (Keyed(M, mv) || Keyed(B, bv))
        {
            if (K.Sig(kv) == B.Sig(bv)) { Log($"{p}: {B.Sig(bv)} -> {M.Sig(mv)}"); return Transplant(mv); }
            return Wrap(bv, mv, kv, p);
        }
        if (R.IsScalar(mv))
        {
            if (Equals(kv, bv)) { Log($"{p}: {bv} -> {mv}"); return Remap(mOwner, f, mv); }
            if (Equals(kv, mv)) return kv;
            throw new MergeConflict(p, $"value changed by both (base {bv}, KEEP {kv}, MOVE {mv})");
        }
        if (bv == null || kv == null) throw new MergeConflict(p, "inline object added/removed by a side");
        if (R.IsStruct(mv)) { object boxed = kv; ApplyDelta(bv, mv, boxed, p); return boxed; }
        ApplyDelta(bv, mv, kv, p);
        return kv;
    }

    // Both sides replaced the same slot with a new object that references the original: nest the wrappers.
    object Wrap(object bv, object mv, object kv, string p)
    {
        if (!Keyed(M, mv) || B.ByKey.ContainsKey(M.Keys[mv]) || !Keyed(B, bv) || !Keyed(K, kv) || B.ByKey.ContainsKey(K.Keys[kv]))
            throw new MergeConflict(p, "both sides changed this reference and it is not a wrapper pattern");
        object kOrig = K.ByKey[B.Keys[bv]];
        object mw = Transplant(mv);
        object outer = moveOuter ? mw : kv, inner = moveOuter ? kv : mw;
        object holder = FindHolder(outer, kOrig);
        if (holder == null || Replace(holder, kOrig, inner) == 0)
            throw new MergeConflict(p, $"{(moveOuter ? M.Keys[mv] : K.Keys[kv])} does not lead to the original {B.Keys[bv]} through new objects");
        string msg = $"{p}: WRAP {(moveOuter ? "MOVE " + M.Keys[mv] : "KEEP " + K.Keys[kv])} (outer) -> {(moveOuter ? "KEEP " + K.Keys[kv] : "MOVE " + M.Keys[mv])} (inner) -> {B.Keys[bv]}";
        Log(msg);
        wraps.Add(new JsonObject { ["slot"] = p, ["outer"] = moveOuter ? M.Keys[mv] : K.Keys[kv], ["inner"] = moveOuter ? K.Keys[kv] : M.Keys[mv],
            ["holder"] = KeyOf(holder), ["original"] = B.Keys[bv] });
        return outer;
    }

    string KeyOf(object o) => M.Keys.TryGetValue(o, out var k) ? k : K.Keys.TryGetValue(o, out var k2) ? k2 : null;
    bool IsBaseObject(object o) => K.Keys.TryGetValue(o, out var k) && B.ByKey.ContainsKey(k);

    // A wrapper may itself be wrapped (A -> A' -> original). Walk through objects that are new on that side
    // (stopping at base objects) to the one that references the original.
    object FindHolder(object outer, object original)
    {
        var seen = new HashSet<object>(ReferenceEqualityComparer.Instance) { outer };
        var queue = new Queue<(object, int)>();
        queue.Enqueue((outer, 0));
        while (queue.Count > 0)
        {
            var (o, depth) = queue.Dequeue();
            var refs = R.Fields(o.GetType()).Select(f => f.GetValue(o)).SelectMany(v => v is IList l ? l.Cast<object>() : new[] { v })
                .Where(R.IsRefObject).ToList();
            if (refs.Any(r => ReferenceEquals(r, original))) return o;
            if (depth >= 8) continue;
            foreach (var r in refs) if (!IsBaseObject(r) && seen.Add(r)) queue.Enqueue((r, depth + 1));
        }
        return null;
    }

    static int Replace(object holder, object from, object to)
    {
        int n = 0;
        foreach (var f in R.Fields(holder.GetType()))
        {
            var v = f.GetValue(holder);
            if (v is IList l) { for (int i = 0; i < l.Count; i++) if (ReferenceEquals(l[i], from)) { l[i] = to; n++; } }
            else if (ReferenceEquals(v, from)) { f.SetValue(holder, to); n++; }
        }
        return n;
    }
}
