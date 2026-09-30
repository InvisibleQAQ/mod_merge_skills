// roundtrip <file> [--defs <defsDir>]
// Proves the libraries can write a file type back before a merge relies on it:
//   regulation.bin : decrypt -> re-encrypt with the same IV; compare decrypted params; with --defs also
//                    read/write every param through its paramdef and compare bytes
//   BND4 (.dcx)    : read -> write with the same DCX type; compare decompressed binder bytes
//   behbnd / .hkx  : additionally read -> write the behavior graph with HKLib; compare bytes
//   TAE containers : additionally re-serialise every .tae; count files whose bytes change (only matters for
//                    TAE files a merge actually rewrites; content is still checked by tae-dump signatures)
// Prints one line per check with OK / DIFF.
using Andre.Formats;
using SoulsFormats;

static class Roundtrip
{
    static string Ok(bool b) => b ? "OK" : "DIFF";

    public static int Run(string path, string defsDir)
    {
        string name = Path.GetFileName(path).ToLowerInvariant();
        if (name == "regulation.bin") return Regulation(path, defsDir);
        if (name.EndsWith(".hkx")) return Behavior(File.ReadAllBytes(path), name);
        byte[] raw = File.ReadAllBytes(path);
        var dcx = DCX.Type.None;
        byte[] data = DCX.Is(raw) ? DCX.Decompress(raw, out dcx) : raw;
        var bnd = BND4.Read(data);
        byte[] outData = DCX.Decompress(bnd.Write(dcx), out var dcx2);
        Console.WriteLine($"{Ok(outData.AsSpan().SequenceEqual(data))} binder {name}: {bnd.Files.Count} entries, {dcx} -> {dcx2}");
        foreach (var f in bnd.Files.Where(f => f.Name.Replace('/', '\\').Contains(@"\Behaviors\", StringComparison.OrdinalIgnoreCase)))
            Behavior(f.Bytes.ToArray(), Util.ShortName(f.Name));
        var taes = bnd.Files.Where(f => f.Name.EndsWith(".tae", StringComparison.OrdinalIgnoreCase)).ToList();
        if (taes.Count > 0)
        {
            int same = taes.Count(f => TAE.Read(f.Bytes).Write().AsSpan().SequenceEqual(f.Bytes.Span));
            Console.WriteLine($"INFO tae re-serialisation: {same}/{taes.Count} byte-identical (merges only rewrite TAE files both sides changed)");
        }
        return 0;
    }

    static int Behavior(byte[] hkx, string label)
    {
        var g = new Graph(hkx);
        byte[] back = Graph.Write(g.Root);
        Console.WriteLine($"{Ok(back.AsSpan().SequenceEqual(hkx))} behavior {label}: {g.Order.Count} keyed objects, {hkx.Length} -> {back.Length} bytes");
        return 0;
    }

    static int Regulation(string path, string defsDir)
    {
        byte[] enc = File.ReadAllBytes(path);
        var bnd = SFUtil.DecryptERRegulation(path);
        var dcx = bnd.Compression == DCX.Type.None ? DCX.Type.DCX_ZSTD : bnd.Compression;
        var back = SFUtil.DecryptERRegulation(SFUtil.EncryptERRegulation(bnd, enc[..16], dcx));
        bool same = bnd.Files.Count == back.Files.Count && bnd.Files.Zip(back.Files).All(p => p.First.Name == p.Second.Name && Util.SameBytes(p.First, p.Second));
        Console.WriteLine($"{Ok(same)} regulation {bnd.Version}: {bnd.Files.Count} files, compression {dcx}, decrypted content after re-encryption");
        if (defsDir == null) return 0;
        var defs = Dump.LoadDefs(defsDir);
        ulong version = ulong.Parse(bnd.Version);
        int ok = 0, diff = 0, skipped = 0;
        foreach (var f in bnd.Files.Where(f => f.Name.EndsWith(".param", StringComparison.OrdinalIgnoreCase)))
        {
            Param p = null;
            try { p = Dump.LoadParam(f, defs, version); } catch { }
            if (p == null) { skipped++; continue; }
            if (p.Write().AsSpan().SequenceEqual(f.Bytes.Span)) ok++;
            else { diff++; Console.WriteLine($"DIFF param {Path.GetFileNameWithoutExtension(f.Name.Replace('\\', '/'))}"); }
        }
        Console.WriteLine($"{Ok(diff == 0)} params write-back: {ok} identical, {diff} different, {skipped} without paramdef");
        return 0;
    }
}
