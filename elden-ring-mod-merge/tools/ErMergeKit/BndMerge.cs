// bnd-merge <base|-> <a> <b> <out> --primary a|b [--resolve r.json] [--report rep.json] [--dry-run]
//   Entry-level three-way merge of any BND4 binder (HKX animation binders, ffxbnd, msgbnd, talkesdbnd ...).
//   Entries are matched by name. An .fmg entry changed by both sides is merged per text ID; any other entry
//   changed by both is a conflict (resolution key = entry file name, value "a"/"b").
//   Entries added by both sides with the same BND ID but different names are reported as conflicts.
//   Use base '-' when the base does not ship the file (then identical additions merge, different ones conflict).
// bnd-drop <in> <out|-> <nameFragment>... [--dry-run]   removes entries whose full name contains any fragment
//   (case-insensitive) and prints every removed entry with the fragment that matched it. A fragment that
//   matches no entry is an error (exit 1, nothing written): a typo must not silently keep both copies.
using SoulsFormats;

static class BndMerge
{
    public static int Run(Args args)
    {
        string primary = Program.Primary(args), other = primary == "a" ? "b" : "a";
        var res = Util.LoadResolutions(args.OptPath("--resolve"));
        var rep = new Report();
        var bs = Util.ReadBndOrNull(args.P(0), out _);
        var A = Util.ReadBnd(args.P(1), out var ta);
        var B = Util.ReadBnd(args.P(2), out var tb);
        var (P, Q, dcx) = primary == "a" ? (A, B, ta) : (B, A, tb);
        bool sorted = P.Files.Zip(P.Files.Skip(1)).All(x => x.First.ID <= x.Second.ID);
        var baseByKey = bs?.Files.ToDictionary(Util.EntryKey) ?? new();
        var pByKey = P.Files.ToDictionary(Util.EntryKey);
        var qKeys = Q.Files.Select(Util.EntryKey).ToHashSet();
        foreach (var qe in Q.Files)
        {
            string key = Util.EntryKey(qe), name = Util.ShortName(qe.Name);
            baseByKey.TryGetValue(key, out var be);
            if (!pByKey.TryGetValue(key, out var pe))
            {
                if (be != null && Util.SameBytes(qe, be)) { rep.Note($"{name}: removed by {primary}, unchanged in {other} -> stays removed"); continue; }
                if (be != null) { rep.Conflict(name, $"removed by {primary}, changed by {other}"); continue; }
                P.Files.Add(new BinderFile(qe.Flags, qe.ID, qe.Name, qe.Bytes.ToArray()));
                rep.Count($"added from {other}");
                continue;
            }
            var pick = Three.Decide(be != null, Util.SameBytes(pe, qe), be != null && Util.SameBytes(pe, be), be != null && Util.SameBytes(qe, be));
            if (pick == Pick.Primary) continue;
            if (pick == Pick.Other) { pe.Bytes = qe.Bytes.ToArray(); rep.Count($"taken from {other}"); continue; }
            if (name.EndsWith(".fmg", StringComparison.OrdinalIgnoreCase))
            {
                pe.Bytes = MergeFmg(name, FMG.Read(pe.Bytes), FMG.Read(qe.Bytes), be != null ? FMG.Read(be.Bytes) : null, res, primary, other, rep);
                continue;
            }
            var r = Three.Resolved(res, name, primary);
            if (r == Pick.Other) { pe.Bytes = qe.Bytes.ToArray(); rep.Note($"{name}: resolved -> {other}"); }
            else if (r == null) rep.Conflict(name, "entry changed differently by both sides");
        }
        foreach (var (key, be) in baseByKey)
            if (!qKeys.Contains(key) && pByKey.TryGetValue(key, out var pe))
            {
                if (Util.SameBytes(pe, be)) { P.Files.Remove(pe); rep.Note($"{Util.ShortName(be.Name)}: removed by {other}"); }
                else rep.Conflict(Util.ShortName(be.Name), $"removed by {other}, changed by {primary}");
            }
        foreach (var g in P.Files.GroupBy(f => f.ID).Where(g => g.Count() > 1))
            rep.Conflict($"id:{g.Key}", "BND ID used by several entries: " + string.Join(", ", g.Select(f => Util.ShortName(f.Name))));
        if (sorted) P.Files = P.Files.OrderBy(f => f.ID).ToList();
        rep.Stats["entries"] = P.Files.Count;
        int code = rep.Finish(args.OptPath("--report"));
        if (code == 0 && !args.DryRun) { Util.Save(args.P(3), P.Write(dcx)); Console.WriteLine($"bnd-merge -> {args.P(3)} ({P.Files.Count} entries, {dcx})"); }
        return code;
    }

    static byte[] MergeFmg(string name, FMG p, FMG q, FMG b, Dictionary<string, string> res, string primary, string other, Report rep)
    {
        var P = p.Entries.GroupBy(e => e.ID).ToDictionary(g => g.Key, g => g.First());
        var Q = q.Entries.GroupBy(e => e.ID).ToDictionary(g => g.Key, g => g.First());
        var B = b?.Entries.GroupBy(e => e.ID).ToDictionary(g => g.Key, g => g.First()) ?? new();
        int changed = 0;
        foreach (int id in Q.Keys.Union(B.Keys))
        {
            P.TryGetValue(id, out var pe); Q.TryGetValue(id, out var qe); B.TryGetValue(id, out var be);
            string pt = pe?.Text, qt = qe?.Text, bt = be?.Text;
            var pick = Three.Decide(b != null, pt == qt, pt == bt, qt == bt);
            if (pick == Pick.Conflict) pick = Three.Resolved(res, $"{name}/{id}", primary) ?? Pick.Conflict;
            if (pick == Pick.Conflict) { rep.Conflict($"{name}/{id}", "text changed differently by both sides", primary == "a" ? pt : qt, primary == "a" ? qt : pt, bt); continue; }
            if (pick != Pick.Other) continue;
            changed++;
            if (pe == null) p.Entries.Add(new FMG.Entry(p, id, qt));
            else if (qe == null) p.Entries.Remove(pe);
            else pe.Text = qt;
        }
        p.Entries = p.Entries.OrderBy(e => e.ID).ToList();
        rep.Note($"{name}: FMG merged, {changed} text entries from {other}");
        return p.Write();
    }

    public static int Drop(Args args)
    {
        string input = args.P(0), output = args.P(1);
        var fragments = args.Pos.Skip(2).ToList();
        if (fragments.Count == 0) throw new ArgumentException("bnd-drop needs at least one name fragment");
        var b = Util.ReadBnd(input, out var t);
        var drop = new HashSet<BinderFile>();
        var unmatched = new List<string>();
        foreach (string x in fragments)
        {
            var hits = b.Files.Where(f => f.Name.Contains(x, StringComparison.OrdinalIgnoreCase)).ToList();
            if (hits.Count == 0) unmatched.Add(x);
            foreach (var f in hits)
            {
                drop.Add(f);
                Console.WriteLine($"  dropped {f.ID} {Util.ShortName(f.Name)} (fragment \"{x}\")");
            }
        }
        if (unmatched.Count > 0)
        {
            Console.Error.WriteLine($"ERROR: {input}: no entry name contains {string.Join(", ", unmatched.Select(x => $"\"{x}\""))}; nothing written");
            return 1;
        }
        b.Files.RemoveAll(drop.Contains);
        if (args.DryRun) { Console.WriteLine($"bnd-drop (dry run): {drop.Count} entries would be dropped, {b.Files.Count} left"); return 0; }
        Util.Save(output, b.Write(t));
        Console.WriteLine($"bnd-drop -> {output} ({drop.Count} dropped, {b.Files.Count} entries left)");
        return 0;
    }
}
