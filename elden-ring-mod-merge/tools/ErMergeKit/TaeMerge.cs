// tae-merge <base|-> <a> <b> <out> --primary a|b [--resolve r.json] [--report rep.json] [--dry-run]
// Merges a TAE container binder (c0000.anibnd.dcx) three-way:
//   entry level  : an entry only one side changed is taken byte-for-byte (no re-serialisation);
//   TAE level    : for an entry both sides changed, animations are merged by (ID, occurrence);
//                  TAE header fields follow the side that changed them.
// Resolution keys: "<entry.tae>/<animID>" or "<entry.tae>/<animID>#<occurrence>" for duplicates.
using System.Text;
using SoulsFormats;

static class TaeMerge
{
    public static string HeaderText(TAE.Animation.AnimMiniHeader h) => h switch
    {
        TAE.Animation.AnimMiniHeader.Standard s => $"Standard loop={s.IsLoopByDefault} importsHkx={s.ImportsHKX} delay={s.AllowDelayLoad} src={s.ImportHKXSourceAnimID}",
        TAE.Animation.AnimMiniHeader.ImportOtherAnim o => $"ImportOtherAnim from={o.ImportFromAnimID} unk={o.Unknown}",
        null => "null",
        _ => h.Type.ToString(),
    };

    // Content signature of one animation: header, file name, event groups and events with raw parameter bytes.
    public static string Sig(TAE.Animation a, bool big)
    {
        var sb = new StringBuilder();
        sb.Append(a.ID).Append('|').Append(HeaderText(a.MiniHeader)).Append('|').Append(a.AnimFileName).Append('|');
        var groups = a.EventGroups ?? new List<TAE.EventGroup>();
        foreach (var g in groups)
        {
            var d = g.GroupData;
            sb.Append($"g{g.GroupType}:{d.DataType}:{d.CutsceneEntityType}:{d.CutsceneEntityIDPart1}:{d.CutsceneEntityIDPart2}:{d.Area}:{d.Block};");
        }
        foreach (var e in a.Events)
            sb.Append($"e{e.Type}:{e.Unk04}:{e.StartTime:R}:{e.EndTime:R}:{groups.IndexOf(e.Group)}:{Convert.ToHexString(e.GetParameterBytes(big))};");
        return Util.Sha(Encoding.UTF8.GetBytes(sb.ToString()));
    }

    static Dictionary<(long, int), TAE.Animation> Index(TAE t)
    {
        var d = new Dictionary<(long, int), TAE.Animation>();
        var seen = new Dictionary<long, int>();
        foreach (var a in t.Animations)
        {
            int occ = seen.TryGetValue(a.ID, out var n) ? n + 1 : 0;
            seen[a.ID] = occ;
            d[(a.ID, occ)] = a;
        }
        return d;
    }

    public static int Run(Args args)
    {
        string primary = Program.Primary(args), other = primary == "a" ? "b" : "a";
        var res = Util.LoadResolutions(args.OptPath("--resolve"));
        var rep = new Report();
        var bs = Util.ReadBndOrNull(args.P(0), out _);
        var A = Util.ReadBnd(args.P(1), out var ta);
        var B = Util.ReadBnd(args.P(2), out var tb);
        var (P, Q, dcx) = primary == "a" ? (A, B, ta) : (B, A, tb);
        var baseByKey = bs?.Files.ToDictionary(Util.EntryKey) ?? new();
        var pByKey = P.Files.ToDictionary(Util.EntryKey);
        bool entriesSorted = P.Files.Zip(P.Files.Skip(1)).All(x => x.First.ID <= x.Second.ID);
        foreach (var qe in Q.Files)
        {
            string key = Util.EntryKey(qe), name = Util.ShortName(qe.Name);
            baseByKey.TryGetValue(key, out var be);
            if (!pByKey.TryGetValue(key, out var pe))
            {
                if (be != null) { rep.Conflict(name, $"deleted by {primary}, present in {other}"); continue; }
                P.Files.Add(new BinderFile(qe.Flags, qe.ID, qe.Name, qe.Bytes.ToArray()));
                rep.Count($"entries added from {other}");
                continue;
            }
            var pick = Three.Decide(be != null, Util.SameBytes(pe, qe), be != null && Util.SameBytes(pe, be), be != null && Util.SameBytes(qe, be));
            if (pick == Pick.Primary) continue;
            if (pick == Pick.Other) { pe.Bytes = qe.Bytes.ToArray(); rep.Count($"entries taken from {other}"); continue; }
            if (!name.EndsWith(".tae", StringComparison.OrdinalIgnoreCase))
            {
                var r = Three.Resolved(res, name, primary);
                if (r == Pick.Other) pe.Bytes = qe.Bytes.ToArray();
                else if (r == null) rep.Conflict(name, "non-TAE entry changed by both");
                continue;
            }
            pe.Bytes = MergeTae(name, TAE.Read(pe.Bytes), TAE.Read(qe.Bytes), be != null ? TAE.Read(be.Bytes) : null, res, primary, other, rep);
        }
        foreach (var be in bs?.Files ?? new List<BinderFile>())
            if (!Q.Files.Any(f => Util.EntryKey(f) == Util.EntryKey(be)) && pByKey.ContainsKey(Util.EntryKey(be)))
                rep.Note($"{Util.ShortName(be.Name)}: missing in {other}, kept from {primary}");
        if (entriesSorted) P.Files = P.Files.OrderBy(f => f.ID).ToList();
        int code = rep.Finish(args.OptPath("--report"));
        if (code == 0 && !args.DryRun) { Util.Save(args.P(3), P.Write(dcx)); Console.WriteLine($"tae-merge -> {args.P(3)}"); }
        return code;
    }

    static byte[] MergeTae(string name, TAE pt, TAE qt, TAE bt, Dictionary<string, string> res, string primary, string other, Report rep)
    {
        bool big = pt.BigEndian;
        var P = Index(pt); var Q = Index(qt); var Bx = bt != null ? Index(bt) : new();
        bool sorted = pt.Animations.Zip(pt.Animations.Skip(1)).All(x => x.First.ID <= x.Second.ID);
        int added = 0, taken = 0, removed = 0;
        foreach (var key in Q.Keys.Union(Bx.Keys).ToList())
        {
            P.TryGetValue(key, out var p); Q.TryGetValue(key, out var q); Bx.TryGetValue(key, out var b);
            string ck = key.Item2 == 0 ? $"{name}/{key.Item1}" : $"{name}/{key.Item1}#{key.Item2}";
            string sp = p != null ? Sig(p, big) : null, sq = q != null ? Sig(q, big) : null, sb = b != null ? Sig(b, big) : null;
            if (q == null)
            {
                if (p == null) continue;
                if (sp == sb) { pt.Animations.Remove(p); removed++; }
                else rep.Conflict(ck, $"deleted by {other}, changed by {primary}");
                continue;
            }
            if (b != null && sq == sb) continue;
            if (p == null)
            {
                if (b == null) { pt.Animations.Add(q); added++; }
                else rep.Conflict(ck, $"deleted by {primary}, changed by {other}");
                continue;
            }
            var pick = Three.Decide(b != null, sp == sq, sp == sb, sq == sb);
            if (pick == Pick.Conflict) pick = Three.Resolved(res, ck, primary) ?? Pick.Conflict;
            if (pick == Pick.Other) { pt.Animations[pt.Animations.IndexOf(p)] = q; taken++; }
            else if (pick == Pick.Conflict) rep.Conflict(ck, "animation changed differently by both sides");
        }
        if (bt != null)
        {
            if (pt.ID == bt.ID && qt.ID != bt.ID) pt.ID = qt.ID;
            if (pt.Flags.AsSpan().SequenceEqual(bt.Flags) && !qt.Flags.AsSpan().SequenceEqual(bt.Flags)) pt.Flags = qt.Flags;
            if (pt.SkeletonName == bt.SkeletonName) pt.SkeletonName = qt.SkeletonName;
            if (pt.SibName == bt.SibName) pt.SibName = qt.SibName;
        }
        if (sorted) pt.Animations = pt.Animations.OrderBy(x => x.ID).ToList();
        rep.Note($"{name}: +{added} animations from {other}, {taken} replaced by {other}'s version, {removed} removed -> {pt.Animations.Count}");
        rep.Count("animations added", added); rep.Count("animations taken", taken);
        return pt.Write();
    }
}
