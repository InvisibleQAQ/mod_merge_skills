// ermerge: Elden Ring two-mod merge toolkit (base + mod A + mod B). See ../../TOOLS.md for the full reference.
// Exit codes: 0 ok, 1 error, 2 usage, 3 unresolved conflicts (nothing written unless all are resolved).
using System.Globalization;

static class Program
{
    const string Usage = @"ermerge <command> ...
  inspect
    bnd-list     <binder.dcx> <out.tsv> [extractDir]
    tae-dump     <anibnd.dcx> <out.jsonl> [TAE.Template.ER.xml]
    param-dump   <regulation.bin> <defsDir> <outDir>
    beh-dump     <c0000.behbnd.dcx|behavior.hkx> <outPrefix>
    roundtrip    <file> [--defs <defsDir>]
    vanilla-extract <gameDir> <outDir> <gamePath>...   (e.g. /chr/c0000_a00_hi.anibnd.dcx, regulation.bin)
  merge (base may be '-' when no base copy exists; --primary picks whose layout/header wins)
    reg-merge    <base> <a> <b> <defsDir> <out> --primary a|b [--label-a T] [--label-b T]
    tae-merge    <base> <a> <b> <out> --primary a|b
    bnd-merge    <base> <a> <b> <out> --primary a|b
    beh-merge    <base.behbnd> <keep.behbnd> <move.behbnd> <out.behbnd> [--wrap-order move-outer|keep-outer]
    bnd-drop     <in.dcx> <out.dcx|-> <nameFragment>... [--dry-run]   (every fragment must match an entry)
  common merge options: --resolve <resolutions.json> --report <report.json> --dry-run";

    static int Main(string[] argv)
    {
        // SoulsFormats looks for oo2core_*.dll and HKLib for Res\ in the current directory.
        Args.CallerDir = Directory.GetCurrentDirectory();
        Directory.SetCurrentDirectory(AppContext.BaseDirectory);
        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
        CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;
        if (argv.Length == 0) { Console.Error.WriteLine(Usage); return 2; }
        var a = new Args(argv.Skip(1));
        try
        {
            return argv[0] switch
            {
                "bnd-list" => Dump.BndList(a.P(0), a.P(1), a.Pos.Count > 2 ? a.P(2) : null),
                "tae-dump" => Dump.TaeDump(a.P(0), a.P(1), a.Pos.Count > 2 ? a.P(2) : null),
                "param-dump" => Dump.ParamDump(a.P(0), a.P(1), a.P(2)),
                "beh-dump" => BehCommands.Dump(a.P(0), a.P(1)),
                "roundtrip" => Roundtrip.Run(a.P(0), a.OptPath("--defs")),
                "vanilla-extract" => Vanilla.Extract(a.P(0), a.P(1), a.Pos.Skip(2).ToList()),
                "reg-merge" => RegMerge.Run(a),
                "tae-merge" => TaeMerge.Run(a),
                "bnd-merge" => BndMerge.Run(a),
                "beh-merge" => BehCommands.Merge(a),
                "bnd-drop" => BndMerge.Drop(a),
                _ => Fail($"unknown command {argv[0]}\n{Usage}"),
            };
        }
        catch (ArgumentException e) { return Fail($"{e.Message}\n{Usage}"); }
        catch (Exception e) { Console.Error.WriteLine($"ERROR: {e}"); return 1; }
    }

    static int Fail(string msg) { Console.Error.WriteLine(msg); return 2; }

    public static string Primary(Args a)
    {
        string p = a.Opt("--primary")?.ToLowerInvariant();
        return p is "a" or "b" ? p : throw new ArgumentException("--primary a|b is required");
    }
}
