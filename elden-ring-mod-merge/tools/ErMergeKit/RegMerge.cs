// reg-merge <base|-> <a> <b> <defsDir> <out> --primary a|b [--label-a T] [--label-b T]
//           [--resolve r.json] [--report rep.json] [--dry-run]
// Three-way merge of regulation.bin at row and field level. The primary side's regulation is the starting
// point (keep the side whose rows still carry names), the other side's changes relative to the base are
// applied: new rows (inserted in ID order), changed rows, and changed fields of rows both sides touched.
// A field both sides changed differently is a conflict; resolution keys: "Param/ID/field" or "Param/ID"
// (whole row), value "a"/"b". Rows are matched by (ID, occurrence) because some params repeat IDs.
// New rows without a name get --label-<side> as their name (editor-only; the game ignores row names).
using Andre.Formats;
using SoulsFormats;

static class RegMerge
{
    static bool Eq(object x, object y) =>
        x is Array ax && y is Array ay ? System.Collections.StructuralComparisons.StructuralEqualityComparer.Equals(ax, ay) : Equals(x, y);

    static bool RowEq(List<Param.Column> xc, Param.Row x, List<Param.Column> yc, Param.Row y)
    {
        for (int i = 0; i < xc.Count; i++) if (!Eq(xc[i].GetValue(x), yc[i].GetValue(y))) return false;
        return true;
    }

    static Dictionary<(int, int), Param.Row> Index(Param p)
    {
        var d = new Dictionary<(int, int), Param.Row>();
        var seen = new Dictionary<int, int>();
        foreach (var r in p.Rows)
        {
            int occ = seen.TryGetValue(r.ID, out var n) ? n + 1 : 0;
            seen[r.ID] = occ;
            d[(r.ID, occ)] = r;
        }
        return d;
    }

    public static int Run(Args args)
    {
        string primary = Program.Primary(args), other = primary == "a" ? "b" : "a";
        string otherLabel = args.Opt("--label-" + other, "");
        var res = Util.LoadResolutions(args.OptPath("--resolve"));
        var rep = new Report();
        BND4 bs = Util.IsNone(args.P(0)) ? null : SFUtil.DecryptERRegulation(args.P(0));
        BND4 A = SFUtil.DecryptERRegulation(args.P(1)), B = SFUtil.DecryptERRegulation(args.P(2));
        if (A.Version != B.Version || (bs != null && bs.Version != A.Version))
            throw new InvalidDataException($"regulation versions differ: base {bs?.Version} a {A.Version} b {B.Version} (mods built for different game versions)");
        var (P, Q) = primary == "a" ? (A, B) : (B, A);
        ulong version = ulong.Parse(P.Version);
        var defs = Dump.LoadDefs(args.P(3));
        foreach (var pf in P.Files.Where(f => f.Name.EndsWith(".param", StringComparison.OrdinalIgnoreCase)))
        {
            var qf = Q.Files.SingleOrDefault(f => f.Name == pf.Name);
            var bf = bs?.Files.SingleOrDefault(f => f.Name == pf.Name);
            if (qf == null || Util.SameBytes(pf, qf) || (bf != null && Util.SameBytes(qf, bf))) continue;
            string name = Path.GetFileNameWithoutExtension(pf.Name.Replace('\\', '/'));
            Param pp = Dump.LoadParam(pf, defs, version), qp = Dump.LoadParam(qf, defs, version), bp = bf != null ? Dump.LoadParam(bf, defs, version) : null;
            if (pp == null || qp == null) { rep.Conflict(name, "no paramdef for this param; cannot merge rows"); continue; }
            if (MergeParam(name, pp, qp, bp, res, primary, other, otherLabel, rep)) pf.Bytes = pp.Write();
        }
        int code = rep.Finish(args.OptPath("--report"));
        if (code == 0 && !args.DryRun)
        {
            var dcx = P.Compression == DCX.Type.None ? DCX.Type.DCX_ZSTD : P.Compression;
            Util.Save(args.P(4), SFUtil.EncryptERRegulation(P, dcx));
            Console.WriteLine($"reg-merge -> {args.P(4)} (version {P.Version}, {dcx})");
        }
        return code;
    }

    static bool MergeParam(string name, Param pp, Param qp, Param bp, Dictionary<string, string> res, string primary, string other, string label, Report rep)
    {
        List<Param.Column> pc = pp.Columns.ToList(), qc = qp.Columns.ToList(), bc = bp?.Columns.ToList();
        if (pc.Count != qc.Count || (bc != null && bc.Count != pc.Count)) { rep.Conflict(name, "paramdef layouts differ between sides"); return false; }
        var P = Index(pp); var Q = Index(qp); var Bx = bp != null ? Index(bp) : new();
        bool touched = false;
        foreach (var key in Q.Keys.Union(Bx.Keys).OrderBy(k => k).ToList())
        {
            P.TryGetValue(key, out var p); Q.TryGetValue(key, out var q); Bx.TryGetValue(key, out var b);
            string rk = key.Item2 == 0 ? $"{name}/{key.Item1}" : $"{name}/{key.Item1}#{key.Item2}";
            if (q == null)
            {
                if (p == null) continue;
                if (RowEq(pc, p, bc, b)) { pp.RemoveRow(p); touched = true; rep.Note($"{rk}: removed by {other}"); }
                else rep.Conflict(rk, $"row removed by {other}, changed by {primary}");
                continue;
            }
            if (b != null && RowEq(qc, q, bc, b)) continue;
            if (p == null)
            {
                if (b != null) { rep.Conflict(rk, $"row removed by {primary}, changed by {other}"); continue; }
                var row = new Param.Row(q, pp) { Name = string.IsNullOrEmpty(q.Name) ? label : q.Name };
                int idx = 0;
                while (idx < pp.Rows.Count && pp.Rows[idx].ID <= q.ID) idx++;
                pp.InsertRow(idx, row);
                touched = true; rep.Count($"rows added from {other}");
                continue;
            }
            if (RowEq(pc, p, qc, q)) continue;
            if (b != null && RowEq(pc, p, bc, b))
            {
                var row = new Param.Row(q, pp) { Name = !string.IsNullOrEmpty(p.Name) ? p.Name : !string.IsNullOrEmpty(q.Name) ? q.Name : b.Name };
                int idx = pp.IndexOfRow(p);
                pp.RemoveRowAt(idx);
                pp.InsertRow(idx, row);
                touched = true; rep.Count($"rows changed by {other}");
                continue;
            }
            // Both changed the row: merge field by field.
            var rowPick = Three.Resolved(res, rk, primary);
            int fromOther = 0;
            for (int i = 0; i < pc.Count; i++)
            {
                object pv = pc[i].GetValue(p), qv = qc[i].GetValue(q), bv = b != null ? bc[i].GetValue(b) : null;
                var pick = Three.Decide(b != null, Eq(pv, qv), b != null && Eq(pv, bv), b != null && Eq(qv, bv));
                string field = pc[i].Def.InternalName;
                if (pick == Pick.Conflict) pick = Three.Resolved(res, $"{rk}/{field}", primary) ?? rowPick ?? Pick.Conflict;
                if (pick == Pick.Other) { pc[i].SetValue(p, qv); fromOther++; touched = true; }
                else if (pick == Pick.Conflict) rep.Conflict($"{rk}/{field}", "field changed differently by both sides",
                    Convert.ToString(primary == "a" ? pv : qv), Convert.ToString(primary == "a" ? qv : pv), Convert.ToString(bv));
            }
            rep.Note($"{rk}: changed by both, {fromOther} fields taken from {other}");
            rep.Count("rows merged field by field");
        }
        return touched;
    }
}
