// vanilla-extract <gameDir> <outDir> <gamePath>...
// Copies the game's own version of files out of the encrypted Data*/DLC/sd archives (read-only on the game),
// so a file the base mod does not ship can still be merged three-way against vanilla.
// gamePath examples: /chr/c0000_a00_hi.anibnd.dcx  /sfx/sfxbnd_commoneffects.ffxbnd.dcx  /action/eventnameid.txt
// "regulation.bin" is copied from <gameDir>\regulation.bin (it is not archived).
// Found files are written to <outDir>/<gamePath> (sd archive files to <outDir>/sd/<name>); manifest.tsv lists results.
using System.Security.Cryptography;
using System.Text;
using Andre.Core;
using Andre.Core.Util;
using Andre.Formats;
using SoulsFormats;

static class Vanilla
{
    public static int Extract(string gameDir, string outDir, List<string> paths)
    {
        var manifest = new StringBuilder("Path\tArchive\tSize\tSHA256\n");
        var targets = new List<string>();
        foreach (string p in paths)
        {
            if (p.TrimStart('/').Equals("regulation.bin", StringComparison.OrdinalIgnoreCase))
            {
                byte[] reg = File.ReadAllBytes(Path.Combine(gameDir, "regulation.bin"));
                Util.Save(Path.Combine(outDir, "regulation.bin"), reg);
                manifest.Append($"/regulation.bin\t(game folder)\t{reg.Length}\t{Util.Sha(reg)}\n");
            }
            else targets.Add("/" + p.Replace('\\', '/').TrimStart('/').ToLowerInvariant());
        }
        var found = new HashSet<string>();
        foreach (string archive in BinderArchive.GetArchiveNames(Game.ER))
        {
            string bhd = Path.Combine(gameDir, archive + ".bhd"), bdt = Path.Combine(gameDir, archive + ".bdt");
            if (!File.Exists(bhd) || !File.Exists(bdt)) continue;
            using var ar = new BinderArchive(bhd, bdt, Game.ER);
            bool sd = archive.StartsWith("sd", StringComparison.OrdinalIgnoreCase);
            foreach (string path in targets.Where(t => !found.Contains(t)))
            {
                string lookup = sd && path.StartsWith("/sd/") ? path[3..] : path;
                var header = ar.TryGetFileFromHash(BhdDictionary.ComputeHash(lookup, BHD5.Game.EldenRing));
                if (header == null) continue;
                byte[] data = ar.ReadFile(header);
                Util.Save(Path.Combine(outDir, (sd && !path.StartsWith("/sd/") ? "sd" + path : path).TrimStart('/')), data);
                manifest.Append($"{path}\t{archive}\t{data.Length}\t{Util.Sha(data)}\n");
                found.Add(path);
            }
        }
        foreach (string miss in targets.Where(t => !found.Contains(t))) manifest.Append($"{miss}\tNOT_FOUND\t\t\n");
        Util.Save(Path.Combine(outDir, "manifest.tsv"), new UTF8Encoding(false).GetBytes(manifest.ToString()));
        Console.WriteLine($"vanilla-extract: {found.Count}/{targets.Count} archived files found -> {outDir}");
        return 0;
    }
}
