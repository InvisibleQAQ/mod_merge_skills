using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Text.Json.Nodes;
using Andre.Formats;
using SoulsFormats;

internal static class Program
{
    static string Smithbox = "", Dotnet = "", Codec = "", Work = "", Vanilla = "";
    static PARAMDEF Def = null!;
    static byte[] Seed = [];
    static string Version = "";
    static int Checks;

    public static int Main(string[] args)
    {
        if (args.Length != 5) throw new ArgumentException("Args: dotnet codec.dll smithbox vanilla.bin new-test-directory");
        Dotnet = Path.GetFullPath(args[0]); Codec = Path.GetFullPath(args[1]);
        Smithbox = Path.GetFullPath(args[2]); Vanilla = Path.GetFullPath(args[3]); Work = Path.GetFullPath(args[4]);
        if (Directory.Exists(Work)) throw new IOException("Use a new test directory");
        Directory.CreateDirectory(Work);
        Directory.SetCurrentDirectory(Smithbox);
        AssemblyLoadContext.Default.Resolving += (_, name) => {
            string path = Path.Combine(Smithbox, name.Name + ".dll");
            return File.Exists(path) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
        };
        AssemblyLoadContext.Default.ResolvingUnmanagedDll += (_, name) => {
            string path = Path.Combine(Smithbox, name.EndsWith(".dll") ? name : name + ".dll");
            return File.Exists(path) ? NativeLibrary.Load(path) : IntPtr.Zero;
        };
        try { Run(); Console.WriteLine($"PASS: {Checks} codec assertions"); return 0; }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Run()
    {
        using var actual = SFUtil.DecryptERRegulation(Vanilla);
        Version = actual.Version;
        var file = actual.Files.Single(f => Path.GetFileName(f.Name.Replace('\\', '/')) == "ActionButtonParam.param" || Path.GetFileName(f.Name.Replace('\\', '/')) == "ActionButtonParam.PARAM");
        Def = PARAMDEF.XmlDeserialize(Path.Combine(Smithbox, "Assets/PARAM/ER/Defs/ActionButtonParam.xml"), true);
        var source = Param.Read(file.Bytes);
        source.ApplyParamdef(Def, ulong.Parse(Version), "ActionButtonParam");
        var seed = new Param(source);
        for (int i = 0; i < 3; i++) {
            var row = new Param.Row(source.Rows[i], seed) { ID = i + 1, Name = "fixture-" + i };
            seed.AddRow(row);
        }
        Seed = seed.Write();

        var disjoint = Case("disjoint", p => Change(p, 1, "regionType", 1), p => Change(p, 1, "category", 1));
        Check(Analyze(disjoint) == 0, "different fields do not conflict");
        Check(Build(disjoint) == 0, "different fields build");
        var merged = ReadOutput(disjoint);
        Check(Get(merged, 1, "regionType") == Get(NewParam(), 1, "regionType") + 1, "A field retained");
        Check(Get(merged, 1, "category") == Get(NewParam(), 1, "category") + 1, "B field retained");

        var conflict = Case("field-conflict", p => Change(p, 1, "category", 1), p => Change(p, 1, "category", 2));
        Check(Analyze(conflict) == 2, "different values conflict");
        Check(Build(conflict) == 2, "unresolved conflict does not build");
        Check(!File.Exists(Path.Combine(conflict, "out.bin")), "unresolved output absent");
        Decide(conflict, "b");
        Check(Build(conflict) == 0, "resolved field builds");
        Check(Get(ReadOutput(conflict), 1, "category") == Get(NewParam(), 1, "category") + 2, "selected B field used");

        var additions = Case("additions", p => Add(p, 100), p => Add(p, 101));
        Check(Analyze(additions) == 0, "independent additions automatic");
        Check(Build(additions) == 0, "independent additions build");
        Check(ReadOutput(additions).Rows.Select(r => r.ID).ToHashSet().SetEquals([1, 2, 3, 100, 101]), "both new rows retained");

        var insert = Case("insert-order", p => p.InsertRow(0, new Param.Row(p[1]!, p) { ID = 0 }), _ => { });
        Check(Analyze(insert) == 0 && Build(insert) == 0, "inserted row builds");
        Check(ReadOutput(insert).Rows.Select(r => r.ID).SequenceEqual([0, 1, 2, 3]), "source insertion order retained");

        var sameAdd = Case("same-id-new", p => Add(p, 100), p => { Add(p, 100); Change(p, 100, "category", 1); });
        Check(Analyze(sameAdd) == 2, "different new same-ID rows conflict");
        Decide(sameAdd, "a");
        Check(Build(sameAdd) == 0, "new row decision builds");
        Check(Get(ReadOutput(sameAdd), 100, "category") == Get(NewParam(), 1, "category"), "new row selected intact");

        var deletion = Case("deletion", p => p.RemoveRow(p[2]!), _ => { });
        Check(Analyze(deletion) == 0 && Build(deletion) == 0, "one-sided deletion is automatic");
        Check(ReadOutput(deletion)[2] is null, "deleted row absent");

        var deleteEdit = Case("delete-edit", p => p.RemoveRow(p[2]!), p => Change(p, 2, "category", 1));
        Check(Analyze(deleteEdit) == 2, "delete/edit conflicts");
        Decide(deleteEdit, "b");
        Check(Build(deleteEdit) == 0 && ReadOutput(deleteEdit)[2] is not null, "edit decision retains row");

        var duplicate = Case("duplicate", p => Change(p, 1, "category", 1), _ => { }, true);
        Check(Analyze(duplicate) == 2, "modified duplicate IDs are not silently collapsed");
        Decide(duplicate, "a");
        Check(Build(duplicate) == 0, "explicit whole-table duplicate decision builds");
        Check(ReadOutput(duplicate).Rows.Count(r => r.ID == 1) == 2, "duplicate row instances preserved");

        var metadata = Case("param-metadata", p => p.Unk06 += 1, _ => { });
        Check(Analyze(metadata) == 2, "header-only change is not silently discarded");
        Decide(metadata, "a");
        Check(Build(metadata) == 0, "header decision builds");
        Check(ReadOutput(metadata).Unk06 == NewParam().Unk06 + 1, "selected header retained");

        var stale = Case("stale", _ => { }, _ => { });
        Check(Analyze(stale) == 0, "identity analysis");
        Write(Path.Combine(stale, "a.bin"), p => Change(p, 1, "category", 1));
        Check(Build(stale) == 1 && !File.Exists(Path.Combine(stale, "out.bin")), "stale input binding blocks output");

        var version = Case("version", _ => { }, _ => { });
        using (var binder = SFUtil.DecryptERRegulation(Path.Combine(version, "b.bin"))) {
            binder.Version = "11611000";
            SFUtil.EncryptERRegulation(Path.Combine(version, "b.bin"), binder);
        }
        Check(Analyze(version) == 1, "different versions rejected");
        Check(Build(disjoint) == 1, "existing output never overwritten");
        Check(Analyze(disjoint) == 1, "existing analysis report never overwritten");
    }

    static Param NewParam() { var p = Param.Read(Seed); p.ApplyParamdef(Def, ulong.Parse(Version), "ActionButtonParam"); return p; }
    static int Get(Param p, int id, string field) => Convert.ToInt32(p[id]![field]!.Value.Value);
    static void Change(Param p, int id, string field, int amount) { var cell = p[id]![field]!.Value; cell.Value = Convert.ChangeType(Get(p, id, field) + amount, cell.Value.GetType()); }
    static void Add(Param p, int id) => p.AddRow(new Param.Row(p[1]!, p) { ID = id, Name = "added" });
    static string Case(string name, Action<Param> a, Action<Param> b, bool duplicates = false)
    {
        var folder = Path.Combine(Work, name); Directory.CreateDirectory(folder);
        Write(Path.Combine(folder, "base.bin"), _ => { }, duplicates);
        Write(Path.Combine(folder, "a.bin"), a, duplicates);
        Write(Path.Combine(folder, "b.bin"), b, duplicates);
        return folder;
    }
    static void Write(string path, Action<Param> mutate, bool duplicate = false)
    {
        var p = NewParam(); if (duplicate) p.AddRow(new Param.Row(p[1]!, p)); mutate(p);
        using var bnd = new BND4 { Version = Version };
        bnd.Files.Add(new BinderFile(Binder.FileFlags.Flag1, 1, "ActionButtonParam.param", p.Write()));
        bnd.Files.Add(new BinderFile(Binder.FileFlags.Flag1, 2, "unchanged.bin", new byte[] { 1, 3, 5 }));
        SFUtil.EncryptERRegulation(path, bnd);
    }
    static int Analyze(string folder) => Invoke("analyze", folder);
    static int Build(string folder) => Invoke("build", folder);
    static int Invoke(string command, string folder)
    {
        var psi = new ProcessStartInfo(Dotnet) { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, CreateNoWindow = true };
        foreach (var value in new[] { Codec, command, "--base", Path.Combine(folder, "base.bin"), "--a", Path.Combine(folder, "a.bin"), "--b", Path.Combine(folder, "b.bin"), "--smithbox", Smithbox, "--report", Path.Combine(folder, "report.json") }) psi.ArgumentList.Add(value);
        if (command == "build") foreach (var value in new[] { "--decisions", Path.Combine(folder, "report.decisions.json"), "--output", Path.Combine(folder, "out.bin") }) psi.ArgumentList.Add(value);
        using var process = Process.Start(psi)!;
        var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit(); Task.WaitAll(stdout, stderr);
        File.AppendAllText(Path.Combine(Work, "commands.log"), $"{command} {Path.GetFileName(folder)} -> {process.ExitCode}\n{stdout.Result}{stderr.Result}\n");
        return process.ExitCode;
    }
    static void Decide(string folder, string side)
    {
        var path = Path.Combine(folder, "report.decisions.json");
        var document = JsonNode.Parse(File.ReadAllText(path))!;
        foreach (var key in document["decisions"]!.AsObject().Select(p => p.Key).ToArray()) document["decisions"]![key] = side;
        File.WriteAllText(path, document.ToJsonString());
    }
    static Param ReadOutput(string folder)
    {
        using var binder = SFUtil.DecryptERRegulation(Path.Combine(folder, "out.bin"));
        Check(binder.Files.Single(f => f.Name == "unchanged.bin").Bytes.Span.SequenceEqual(new byte[] { 1, 3, 5 }), "unknown unchanged entry preserved");
        var p = Param.Read(binder.Files.Single(f => f.Name == "ActionButtonParam.param").Bytes);
        p.ApplyParamdef(Def, ulong.Parse(Version), "ActionButtonParam");
        return p;
    }
    static void Check(bool value, string message) { if (!value) throw new Exception("FAILED: " + message); Checks++; Console.WriteLine("OK: " + message); }
}
