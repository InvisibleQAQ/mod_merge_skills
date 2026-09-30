// Shared helpers: argument parsing, binder IO, hashing, conflict reporting.
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using SoulsFormats;

sealed class Args
{
    static readonly HashSet<string> Flags = new() { "--dry-run" };
    public readonly List<string> Pos = new();
    readonly Dictionary<string, string> opts = new();

    public Args(IEnumerable<string> raw)
    {
        var list = raw.ToList();
        for (int i = 0; i < list.Count; i++)
        {
            string a = list[i];
            if (Flags.Contains(a)) opts[a] = "true";
            else if (a.StartsWith("--"))
            {
                if (i + 1 >= list.Count) throw new ArgumentException($"option {a} needs a value");
                opts[a] = list[++i];
            }
            else Pos.Add(a);
        }
    }

    public string this[int i] => i < Pos.Count ? Pos[i] : throw new ArgumentException($"missing argument #{i + 1}");

    // The process switches its working directory to the tool folder (oo2core / Res lookup), so file arguments
    // are resolved against the caller's directory captured at startup. "-" (no file) is passed through.
    public static string CallerDir = Directory.GetCurrentDirectory();
    public string P(int i) => Util.IsNone(this[i]) ? this[i] : Path.GetFullPath(this[i], CallerDir);
    public IEnumerable<string> PathsFrom(int i) => Enumerable.Range(i, Math.Max(0, Pos.Count - i)).Select(P);
    public string Opt(string name, string def = null) => opts.TryGetValue(name, out var v) ? v : def;
    public string OptPath(string name) => Opt(name) is string v ? Path.GetFullPath(v, CallerDir) : null;
    public bool Has(string name) => opts.ContainsKey(name);
    public bool DryRun => Has("--dry-run");
}

static class Util
{
    public static string Sha(ReadOnlySpan<byte> d) => Convert.ToHexString(SHA256.HashData(d));

    // "-" means "no such file on this side" (e.g. the base does not ship it).
    public static bool IsNone(string path) => path == "-" || string.IsNullOrEmpty(path);

    public static BND4 ReadBnd(string path, out DCX.Type type)
    {
        byte[] raw = File.ReadAllBytes(path);
        type = DCX.Type.None;
        byte[] data = DCX.Is(raw) ? DCX.Decompress(raw, out type) : raw;
        if (!BND4.Is(data)) throw new InvalidDataException($"{path}: not a BND4 binder");
        return BND4.Read(data);
    }

    public static BND4 ReadBndOrNull(string path, out DCX.Type type)
    {
        type = DCX.Type.None;
        return IsNone(path) ? null : ReadBnd(path, out type);
    }

    public static void Save(string path, byte[] data)
    {
        string dir = Path.GetDirectoryName(Path.GetFullPath(path));
        Directory.CreateDirectory(dir);
        File.WriteAllBytes(path, data);
    }

    public static bool SameBytes(BinderFile x, BinderFile y) => x.Bytes.Span.SequenceEqual(y.Bytes.Span);

    public static string EntryKey(BinderFile f) => f.Name.Replace('/', '\\').ToLowerInvariant();

    public static string ShortName(string name) => name.Replace('/', '\\').Split('\\').Last();

    public static Dictionary<string, string> LoadResolutions(string path)
    {
        var res = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrEmpty(path) || !File.Exists(path)) return res;
        foreach (var kv in JsonNode.Parse(File.ReadAllText(path)).AsObject())
        {
            string side = kv.Value?.GetValue<string>()?.ToLowerInvariant();
            if (side != "a" && side != "b") throw new InvalidDataException($"{path}: resolution for '{kv.Key}' must be \"a\" or \"b\"");
            res[kv.Key] = side;
        }
        return res;
    }
}

enum Pick { Primary, Other, Conflict }

static class Three
{
    // Classic three-way rule for one item (row, animation, entry, field): keep what changed.
    // "Primary" = the side whose object the result is built on; "Other" = the side being merged in.
    public static Pick Decide(bool hasBase, bool primaryEqOther, bool primaryEqBase, bool otherEqBase)
    {
        if (primaryEqOther) return Pick.Primary;
        if (hasBase && otherEqBase) return Pick.Primary;
        if (hasBase && primaryEqBase) return Pick.Other;
        return Pick.Conflict;
    }

    // Applies a --resolve decision ("a"/"b") for a conflict key, or null if the user has not decided yet.
    public static Pick? Resolved(Dictionary<string, string> res, string key, string primarySide) =>
        res.TryGetValue(key, out var side) ? (side == primarySide ? Pick.Primary : Pick.Other) : null;
}

// Collects merge notes and unresolved conflicts; written as JSON for the Python driver.
sealed class Report
{
    public readonly JsonArray Conflicts = new();
    public readonly JsonArray Notes = new();
    public readonly JsonObject Stats = new();

    public void Conflict(string key, string what, string a = null, string b = null, string baseVal = null) =>
        Conflicts.Add(new JsonObject { ["key"] = key, ["what"] = what, ["a"] = a, ["b"] = b, ["base"] = baseVal });

    public void Note(string text) { Notes.Add(text); Console.WriteLine("  " + text); }

    public void Count(string name, int by = 1) => Stats[name] = (Stats[name]?.GetValue<int>() ?? 0) + by;

    public int Finish(string path)
    {
        if (!string.IsNullOrEmpty(path))
        {
            var o = new JsonObject { ["conflicts"] = Conflicts, ["stats"] = Stats, ["notes"] = Notes };
            Util.Save(path, Encoding.UTF8.GetBytes(o.ToJsonString(new JsonSerializerOptions { WriteIndented = true })));
        }
        foreach (var c in Conflicts) Console.WriteLine($"  CONFLICT {c["key"]}: {c["what"]}");
        Console.WriteLine($"  stats {Stats.ToJsonString()}; conflicts {Conflicts.Count}");
        return Conflicts.Count > 0 ? 3 : 0;
    }
}
