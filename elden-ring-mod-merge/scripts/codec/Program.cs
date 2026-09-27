using System.Globalization;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using Andre.Formats;
using SoulsFormats;

internal static class Program
{
    private const string Schema = "er-regulation-three-way-v1";
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, PropertyNameCaseInsensitive = true };

    private static int Main(string[] args)
    {
        try
        {
            var command = args.FirstOrDefault() ?? "";
            var options = Options.Parse(args.Skip(1).ToArray());
            return command switch
            {
                "analyze" => Analyze(options),
                "build" => Build(options),
                _ => Fail("Usage: analyze|build --base <file> --a <file> --b <file> --smithbox <Smithbox.Release/Output> --report <file>; build additionally requires --decisions <file> --output <new file>.")
            };
        }
        catch (ConflictRequiredException ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 2;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }

    private static int Analyze(Options options)
    {
        var request = Request.From(options, false);
        Runtime.Configure(request.Smithbox);
        EnsureReportPath(request.Report, request.InputPaths);
        EnsureFreshOutput(request.Report, request.InputPaths);
        using var plan = MergePlan.Create(request);
        WriteJson(request.Report, plan.Report);
        var template = Path.ChangeExtension(request.Report, ".decisions.json");
        if (!File.Exists(template)) WriteJson(template, new { inputs = plan.Report.Inputs, decisions = plan.Conflicts.ToDictionary(conflict => conflict.Key, _ => "", StringComparer.Ordinal) });
        Console.WriteLine($"{plan.Conflicts.Count} conflict(s) written to {request.Report}");
        return plan.Conflicts.Count == 0 ? 0 : 2;
    }

    private static int Build(Options options)
    {
        var request = Request.From(options, true);
        Runtime.Configure(request.Smithbox);
        EnsureReportPath(request.Report, request.InputPaths);
        EnsureFreshOutput(request.Output!, request.InputPaths);
        var verification = request.Output + ".verified.json";
        EnsureFreshVerification(verification, request);
        var prior = ReadReport(request.Report);
        using var plan = MergePlan.Create(request);
        ValidateReportBinding(prior, plan.Report);
        var decisions = Decisions.Read(request.Decisions, plan.Report.Inputs);
        var unresolved = plan.Conflicts.Where(c => !decisions.Values.TryGetValue(c.Key, out var source) || !Source.IsValid(source)).ToList();
        if (unresolved.Count > 0)
            throw new ConflictRequiredException($"{unresolved.Count} conflict(s) have no base/a/b decision.");

        var result = plan.Materialize(decisions.Values);
        SFUtil.EncryptERRegulation(request.Output!, result.Binder);
        VerifyOutput(request, result);
        WriteJson(verification, new Verification { Inputs = plan.Report.Inputs, Output = request.Output!, OutputSha256 = HashFile(request.Output!), Fingerprint = plan.Report.Fingerprint, Status = "verified" });
        Console.WriteLine($"Merged regulation written to {request.Output}");
        return 0;
    }

    private static void VerifyOutput(Request request, Materialized result)
    {
        using var output = SFUtil.DecryptERRegulation(request.Output);
        if (!string.Equals(output.Version, result.Binder.Version, StringComparison.Ordinal))
            throw new InvalidDataException("Output regulation version differs from the verified plan.");
        if (output.Files.Count != result.Binder.Files.Count || !BinderMetadataEquals(output, result.Binder))
            throw new InvalidDataException("Output binder metadata or entry count differs from the verified plan.");
        foreach (var expectedFile in result.Binder.Files)
        {
            var actualFile = FindFile(output, FileKey(expectedFile));
            if (actualFile is null || !FileEquals(actualFile, expectedFile))
                throw new InvalidDataException($"Output binder entry verification failed for {FileKey(expectedFile)}.");
        }
        foreach (var expected in result.Params)
        {
            var file = FindFile(output, expected.FileKey) ?? throw new InvalidDataException($"Output is missing {expected.FileKey}.");
            var actual = Param.Read(file.Bytes);
            ApplyDefinition(actual, expected.ParamName, result.BinderVersion, result.Defs);
            if (!ParamEquals(expected.Param, actual))
                throw new InvalidDataException($"Output semantic verification failed for {expected.ParamName}.");
        }
        foreach (var expected in result.OpaqueFiles)
        {
            var actual = FindFile(output, expected.Key);
            if (expected.File is null)
            {
                if (actual is not null) throw new InvalidDataException($"Output retained deleted entry {expected.Key}.");
            }
            else if (actual is null || !FileEquals(actual, expected.File))
            {
                throw new InvalidDataException($"Output semantic verification failed for opaque entry {expected.Key}.");
            }
        }
    }

    private static void ApplyDefinition(Param param, string paramName, ulong version, IReadOnlyDictionary<string, PARAMDEF> defs)
    {
        ApplyFixups(param, version);
        if (string.IsNullOrEmpty(param.ParamType) || !defs.TryGetValue(param.ParamType, out var def))
            throw new InvalidDataException($"No PARAMDEF for {paramName} ({param.ParamType ?? "<null>"}).");
        param.ApplyParamdef(def, version, paramName);
    }

    private static void ApplyFixups(Param param, ulong version)
    {
        if (version >= 10601000 && param.ParamType == "CHR_MODEL_PARAM_ST") param.ExpandParamSize(12, 16);
        if (version >= 11210015)
        {
            if (param.ParamType == "GAME_SYSTEM_COMMON_PARAM_ST") param.ExpandParamSize(880, 1024);
            if (param.ParamType == "POSTURE_CONTROL_PARAM_WEP_RIGHT_ST") param.ExpandParamSize(112, 144);
            if (param.ParamType == "SIGN_PUDDLE_PARAM_ST") param.ExpandParamSize(32, 48);
        }
    }

    private static Dictionary<string, PARAMDEF> LoadDefinitions(string smithbox)
    {
        var directory = Path.Combine(smithbox, "Assets", "PARAM", "ER", "Defs");
        if (!Directory.Exists(directory)) throw new DirectoryNotFoundException($"Defs directory not found: {directory}");
        var defs = new Dictionary<string, PARAMDEF>(StringComparer.Ordinal);
        foreach (var path in Directory.EnumerateFiles(directory, "*.xml"))
        {
            var def = PARAMDEF.XmlDeserialize(path, true);
            if (string.IsNullOrEmpty(def.ParamType)) throw new InvalidDataException($"PARAMDEF has no ParamType: {path}");
            if (!defs.TryAdd(def.ParamType, def)) throw new InvalidDataException($"Duplicate PARAMDEF ParamType: {def.ParamType}");
        }
        return defs;
    }

    private static bool ParamEquals(Param left, Param right)
    {
        if (!ParamMetadataEquals(left, right) || left.Rows.Count != right.Rows.Count || left.Columns.Count != right.Columns.Count) return false;
        for (var i = 0; i < left.Rows.Count; i++)
        {
            if (!RowEquals(left.Rows[i], right.Rows[i])) return false;
        }
        return true;
    }

    private static bool ParamMetadataEquals(Param left, Param right) =>
        string.Equals(left.ParamType, right.ParamType, StringComparison.Ordinal) && left.BigEndian == right.BigEndian && left.Format2D == right.Format2D &&
        left.Format2E == right.Format2E && left.ParamdefFormatVersion == right.ParamdefFormatVersion && left.Unk06 == right.Unk06 &&
        left.ParamdefDataVersion == right.ParamdefDataVersion && left.RowSize == right.RowSize;

    private static bool RowEquals(Param.Row? left, Param.Row? right)
    {
        if (left is null || right is null) return left is null && right is null;
        return left.ID == right.ID && string.Equals(left.Name, right.Name, StringComparison.Ordinal) && left.DataEquals(right);
    }

    private static bool ValueEquals(object left, object right) => left switch
    {
        float x when right is float y => BitConverter.SingleToInt32Bits(x) == BitConverter.SingleToInt32Bits(y),
        double x when right is double y => BitConverter.DoubleToInt64Bits(x) == BitConverter.DoubleToInt64Bits(y),
        byte[] x when right is byte[] y => x.AsSpan().SequenceEqual(y),
        _ => Equals(left, right)
    };

    private static object? DisplayValue(object? value) => value switch
    {
        float x => new Dictionary<string, string> { ["type"] = "f32", ["bits"] = $"0x{BitConverter.SingleToInt32Bits(x):X8}", ["value"] = x.ToString("R", CultureInfo.InvariantCulture) },
        double x => new Dictionary<string, string> { ["type"] = "f64", ["bits"] = $"0x{BitConverter.DoubleToInt64Bits(x):X16}", ["value"] = x.ToString("R", CultureInfo.InvariantCulture) },
        byte[] x => new Dictionary<string, string> { ["type"] = "bytes", ["base64"] = Convert.ToBase64String(x) },
        BinderFile x => new EntrySummary(x.ID, x.Name, x.Flags.ToString(), x.CompressionType.ToString(), Convert.ToHexString(SHA256.HashData(x.Bytes.Span))),
        Param x => new ParamSummary(x.ParamType ?? "", x.Rows.Count, x.RowSize, new {
            x.BigEndian, Format2D = x.Format2D.ToString(), Format2E = x.Format2E.ToString(),
            x.ParamdefFormatVersion, x.Unk06, x.ParamdefDataVersion }),
        Param.Row x => new RowSummary(x.ID, x.Name, x.Columns.ToDictionary(column => column.Def.InternalName, column => DisplayValue(x[column].Value), StringComparer.Ordinal)),
        BND4 x => new BinderSummary(x.Version, x.Format.ToString(), x.Unk04, x.Unk05, x.BigEndian, x.BitBigEndian, x.Unicode, x.Extended),
        _ => value
    };

    private static bool FileEquals(BinderFile left, BinderFile right) =>
        left.ID == right.ID && left.Flags == right.Flags && left.CompressionType == right.CompressionType &&
        string.Equals(left.Name, right.Name, StringComparison.Ordinal) && left.Bytes.Span.SequenceEqual(right.Bytes.Span);

    private static bool FileMetadataEquals(BinderFile left, BinderFile right) =>
        left.ID == right.ID && left.Flags == right.Flags && left.CompressionType == right.CompressionType && string.Equals(left.Name, right.Name, StringComparison.Ordinal);

    private static bool BinderMetadataEquals(BND4 left, BND4 right) =>
        left.Format == right.Format && left.Unk04 == right.Unk04 && left.Unk05 == right.Unk05 && left.BigEndian == right.BigEndian &&
        left.BitBigEndian == right.BitBigEndian && left.Unicode == right.Unicode && left.Extended == right.Extended;

    private static BinderFile CloneFile(BinderFile source) => new(source.Flags, source.ID, source.Name, source.Bytes.ToArray()) { CompressionType = source.CompressionType };
    private static BinderFile? FindFile(BND4 binder, string key) => binder.Files.FirstOrDefault(file => FileKey(file) == key);
    private static string FileKey(BinderFile file) => $"{file.ID}:{file.Name ?? "<null>"}";
    private static string ParamName(BinderFile file) => Path.GetFileNameWithoutExtension((file.Name ?? "").Replace('\\', Path.DirectorySeparatorChar));
    private static bool IsParamFile(BinderFile file) => file.Name?.EndsWith(".PARAM", StringComparison.OrdinalIgnoreCase) == true;
    private static string HashFile(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
    private static string HashDirectory(string directory) => Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(string.Join("\n", Directory.EnumerateFiles(directory, "*.xml").OrderBy(x => x, StringComparer.Ordinal).Select(path => $"{Path.GetFileName(path)}:{HashFile(path)}")))));
    private static void WriteJson(string path, object value)
    {
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(stream, value, Json);
    }
    private static int Fail(string message) { Console.Error.WriteLine(message); return 1; }

    private static void EnsureReportPath(string report, IEnumerable<string> inputs)
    {
        if (inputs.Any(input => PathsEqual(input, report))) throw new InvalidOperationException("Report path must not overwrite an input.");
    }
    private static void EnsureFreshOutput(string output, IEnumerable<string> inputs)
    {
        if (inputs.Any(input => PathsEqual(input, output))) throw new InvalidOperationException("Output path must not overwrite an input.");
        if (File.Exists(output)) throw new IOException("Output already exists; choose a new path.");
    }
    private static void EnsureFreshVerification(string verification, Request request)
    {
        var protectedPaths = request.InputPaths.Concat([request.Report, request.Decisions!, request.Output!]);
        if (protectedPaths.Any(path => PathsEqual(path, verification))) throw new InvalidOperationException("Verification sidecar path overlaps another request path.");
        if (File.Exists(verification)) throw new IOException("Verification sidecar already exists; choose a new output path.");
    }
    private static bool PathsEqual(string left, string right) => string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);
    private static Report ReadReport(string path) => JsonSerializer.Deserialize<Report>(File.ReadAllText(path), Json) ?? throw new InvalidDataException("Report is empty or invalid JSON.");
    private static void ValidateReportBinding(Report supplied, Report fresh)
    {
        if (supplied.Schema != Schema || !string.Equals(supplied.Fingerprint, fresh.Fingerprint, StringComparison.Ordinal) || !supplied.Inputs.Equals(fresh.Inputs))
            throw new InvalidDataException("Report binding does not match the current inputs, definitions, or dependency DLLs.");
        var suppliedKeys = supplied.Conflicts.Select(c => c.Key).OrderBy(x => x, StringComparer.Ordinal);
        var freshKeys = fresh.Conflicts.Select(c => c.Key).OrderBy(x => x, StringComparer.Ordinal);
        if (!suppliedKeys.SequenceEqual(freshKeys, StringComparer.Ordinal)) throw new InvalidDataException("Report conflict keys do not match fresh analysis.");
    }

    private static class Runtime
    {
        private static bool _configured;
        public static void Configure(string smithbox)
        {
            if (_configured) return;
            Directory.SetCurrentDirectory(smithbox);
            AssemblyLoadContext.Default.Resolving += (_, name) =>
            {
                if (string.IsNullOrWhiteSpace(name.Name)) return null;
                var path = Path.Combine(smithbox, $"{name.Name}.dll");
                return File.Exists(path) ? Assembly.LoadFrom(path) : null;
            };
            foreach (var name in new[] { "Andre.Core", "Andre.Formats", "Andre.SoulsFormats" })
            {
                var expected = Path.Combine(smithbox, name + ".dll");
                var loaded = Assembly.LoadFrom(expected);
                if (HashFile(loaded.Location) != HashFile(expected))
                    throw new InvalidOperationException($"Loaded {name} differs from --smithbox; rebuild codec with that SmithboxDir.");
            }
            var souls = Assembly.LoadFrom(Path.Combine(smithbox, "Andre.SoulsFormats.dll"));
            NativeLibrary.SetDllImportResolver(souls, (libraryName, _, _) =>
            {
                var oodle = Path.Combine(smithbox, "oo2core_9_win64.dll");
                return libraryName.Contains("oo2core", StringComparison.OrdinalIgnoreCase) && File.Exists(oodle) && NativeLibrary.TryLoad(oodle, out var handle) ? handle : IntPtr.Zero;
            });
            _configured = true;
        }
    }

    private sealed class Options
    {
        private readonly Dictionary<string, string> _values = new(StringComparer.Ordinal);
        public string Require(string name) => _values.TryGetValue(name, out var value) && !string.IsNullOrWhiteSpace(value) ? Path.GetFullPath(value) : throw new ArgumentException($"Missing --{name}.");
        public static Options Parse(string[] args)
        {
            var result = new Options();
            for (var i = 0; i < args.Length; i++)
            {
                if (!args[i].StartsWith("--", StringComparison.Ordinal) || i + 1 == args.Length) throw new ArgumentException("Options must be --name value pairs.");
                result._values.Add(args[i][2..], args[++i]);
            }
            return result;
        }
    }

    private sealed record Request(string Base, string A, string B, string Smithbox, string Report, string? Decisions, string? Output)
    {
        public string[] InputPaths => [Base, A, B];
        public static Request From(Options options, bool build)
        {
            var request = new Request(options.Require("base"), options.Require("a"), options.Require("b"), options.Require("smithbox"), options.Require("report"), build ? options.Require("decisions") : null, build ? options.Require("output") : null);
            foreach (var path in request.InputPaths) if (!File.Exists(path)) throw new FileNotFoundException("Input not found.", path);
            if (!Directory.Exists(request.Smithbox)) throw new DirectoryNotFoundException($"Smithbox output directory not found: {request.Smithbox}");
            return request;
        }
    }

    private sealed class Source
    {
        public const string Base = "base";
        public const string A = "a";
        public const string B = "b";
        public static bool IsValid(string source) => source is Base or A or B;
    }

    private sealed class RegulationSource : IDisposable
    {
        public required string Label { get; init; }
        public required string Path { get; init; }
        public required string Hash { get; init; }
        public required BND4 Binder { get; init; }
        public required Dictionary<string, BinderFile> Files { get; init; }
        public Dictionary<string, ParsedParam> Params { get; } = new(StringComparer.Ordinal);
        public List<string> ParseWarnings { get; } = [];
        public void Dispose() => Binder.Dispose();
    }

    private sealed record ParsedParam(string FileKey, string Name, BinderFile File, Param Param);

    private sealed class MergePlan : IDisposable
    {
        private readonly RegulationSource _base;
        private readonly RegulationSource _a;
        private readonly RegulationSource _b;
        private readonly Dictionary<string, PARAMDEF> _defs;
        private readonly List<Action<Dictionary<string, string>, Materialized>> _actions = [];
        public List<Conflict> Conflicts { get; } = [];
        public Report Report { get; private set; } = new();

        private MergePlan(RegulationSource @base, RegulationSource a, RegulationSource b, Dictionary<string, PARAMDEF> defs)
        {
            _base = @base; _a = a; _b = b; _defs = defs;
        }

        public static MergePlan Create(Request request)
        {
            var defs = LoadDefinitions(request.Smithbox);
            var baseSource = Load(Source.Base, request.Base, defs);
            var a = Load(Source.A, request.A, defs);
            var b = Load(Source.B, request.B, defs);
            if (!string.Equals(baseSource.Binder.Version, a.Binder.Version, StringComparison.Ordinal) || !string.Equals(baseSource.Binder.Version, b.Binder.Version, StringComparison.Ordinal) || !ulong.TryParse(baseSource.Binder.Version, out _))
            {
                baseSource.Dispose(); a.Dispose(); b.Dispose();
                throw new InvalidDataException("All regulations must have the same numeric BND4 version; version upgrades are not supported.");
            }
            var plan = new MergePlan(baseSource, a, b, defs);
            plan.Analyze();
            plan.Report = plan.MakeReport(request.Smithbox);
            return plan;
        }

        private static RegulationSource Load(string label, string path, Dictionary<string, PARAMDEF> defs)
        {
            var binder = SFUtil.DecryptERRegulation(path);
            var files = new Dictionary<string, BinderFile>(StringComparer.Ordinal);
            foreach (var file in binder.Files)
            {
                if (!files.TryAdd(FileKey(file), file)) throw new InvalidDataException($"Duplicate binder file identity in {label}: {FileKey(file)}");
            }
            var source = new RegulationSource { Label = label, Path = path, Hash = HashFile(path), Binder = binder, Files = files };
            if (!ulong.TryParse(binder.Version, out var version)) throw new InvalidDataException($"Invalid BND4 version in {label}: {binder.Version}");
            foreach (var file in binder.Files.Where(IsParamFile))
            {
                try
                {
                    var param = Param.Read(file.Bytes);
                    var name = ParamName(file);
                    ApplyDefinition(param, name, version, defs);
                    source.Params.Add(FileKey(file), new ParsedParam(FileKey(file), name, file, param));
                }
                catch (Exception ex)
                {
                    source.ParseWarnings.Add($"{label}:{FileKey(file)}: {ex.GetType().Name}: {ex.Message}");
                }
            }
            return source;
        }

        private void Analyze()
        {
            if (!Program.BinderMetadataEquals(_base.Binder, _a.Binder) || !Program.BinderMetadataEquals(_base.Binder, _b.Binder))
                AddConflict("binder-meta", "__binder__", null, null, _base.Binder, _a.Binder, _b.Binder);
            var keys = _base.Files.Keys.Union(_a.Files.Keys, StringComparer.Ordinal).Union(_b.Files.Keys, StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal);
            foreach (var key in keys)
            {
                _base.Files.TryGetValue(key, out var baseFile);
                _a.Files.TryGetValue(key, out var aFile);
                _b.Files.TryGetValue(key, out var bFile);
                if (baseFile is null || aFile is null || bFile is null || !_base.Params.TryGetValue(key, out var baseParam) || !_a.Params.TryGetValue(key, out var aParam) || !_b.Params.TryGetValue(key, out var bParam) || !FileMetadataEquals(baseFile, aFile) || !FileMetadataEquals(baseFile, bFile))
                {
                    AnalyzeOpaque(key, baseFile, aFile, bFile);
                    continue;
                }
                if (!ParamMetadataEquals(baseParam.Param, aParam.Param) || !ParamMetadataEquals(baseParam.Param, bParam.Param) || DuplicateIds(baseParam.Param) || DuplicateIds(aParam.Param) || DuplicateIds(bParam.Param) || !RowOrderEquals(baseParam.Param, aParam.Param) || !RowOrderEquals(baseParam.Param, bParam.Param))
                {
                    if (!ParamEquals(baseParam.Param, aParam.Param) || !ParamEquals(baseParam.Param, bParam.Param)) AddConflict("param", key, null, null, baseParam.Param, aParam.Param, bParam.Param);
                    continue;
                }
                AnalyzeParam(baseParam, aParam, bParam);
            }
        }

        private static bool DuplicateIds(Param param) => param.Rows.GroupBy(row => row.ID).Any(group => group.Count() > 1);
        private static bool RowOrderEquals(Param left, Param right)
        {
            var leftIds = left.Rows.Select(row => row.ID).ToHashSet();
            var rightIds = right.Rows.Select(row => row.ID).ToHashSet();
            var expected = left.Rows.Where(row => rightIds.Contains(row.ID)).Select(row => row.ID);
            var actual = right.Rows.Where(row => leftIds.Contains(row.ID)).Select(row => row.ID);
            return expected.SequenceEqual(actual);
        }
        private void AnalyzeOpaque(string key, BinderFile? baseFile, BinderFile? aFile, BinderFile? bFile)
        {
            if (SameFile(baseFile, aFile) && SameFile(baseFile, bFile)) return;
            if (SameFile(aFile, bFile)) { _actions.Add((_, result) => result.SetOpaque(key, aFile)); return; }
            if (SameFile(baseFile, aFile)) { _actions.Add((_, result) => result.SetOpaque(key, bFile)); return; }
            if (SameFile(baseFile, bFile)) { _actions.Add((_, result) => result.SetOpaque(key, aFile)); return; }
            AddConflict("entry", key, null, null, baseFile, aFile, bFile);
        }

        private static bool SameFile(BinderFile? left, BinderFile? right) => left is null || right is null ? left is null && right is null : FileEquals(left, right);

        private void AnalyzeParam(ParsedParam baseParam, ParsedParam aParam, ParsedParam bParam)
        {
            var scratch = new Param(baseParam.Param);
            var rows = baseParam.Param.Rows.ToDictionary(row => row.ID);
            var aRows = aParam.Param.Rows.ToDictionary(row => row.ID);
            var bRows = bParam.Param.Rows.ToDictionary(row => row.ID);
            foreach (var id in rows.Keys.Union(aRows.Keys).Union(bRows.Keys).Order()) AnalyzeRow(baseParam, aParam.Param, bParam.Param, scratch, id, rows.GetValueOrDefault(id), aRows.GetValueOrDefault(id), bRows.GetValueOrDefault(id));
        }

        private void AnalyzeRow(ParsedParam baseParam, Param aParam, Param bParam, Param scratch, int id, Param.Row? baseRow, Param.Row? aRow, Param.Row? bRow)
        {
            var target = baseParam.FileKey;
            if (baseRow is null)
            {
                if (aRow is null && bRow is null) return;
                if (aRow is not null && bRow is null) { _actions.Add((_, result) => result.AddRow(target, aRow, aParam)); return; }
                if (aRow is null && bRow is not null) { _actions.Add((_, result) => result.AddRow(target, bRow, bParam)); return; }
                if (aRow is not null && bRow is not null && RowEquals(aRow, bRow)) { _actions.Add((_, result) => result.AddRow(target, aRow, aParam)); return; }
                AddConflict("row-add", target, id, null, baseRow, aRow, bRow); return;
            }
            if (aRow is null || bRow is null)
            {
                if (aRow is null && bRow is null) { _actions.Add((_, result) => result.RemoveRow(target, id)); return; }
                var changed = aRow is null ? bRow : aRow;
                if (RowEquals(baseRow, changed)) { _actions.Add((_, result) => result.RemoveRow(target, id)); return; }
                AddConflict("row-presence", target, id, null, baseRow, aRow, bRow); return;
            }
            if (HasUnmodeledRawBytes(scratch, baseRow, aRow) || HasUnmodeledRawBytes(scratch, baseRow, bRow))
            {
                AddConflict("row-raw", target, id, null, baseRow, aRow, bRow);
                return;
            }
            MergeValue(target, id, "__name", baseRow.Name, aRow.Name, bRow.Name, (result, value) => result.FindRow(target, id).Name = (string?)value);
            foreach (var column in baseParam.Param.Columns)
            {
                var field = column.Def.InternalName;
                MergeValue(target, id, field, baseRow[column].Value, aRow[column].Value, bRow[column].Value, (result, value) =>
                {
                    var cell = result.FindRow(target, id)[field] ?? throw new InvalidDataException($"Field {field} is missing.");
                    cell.Value = value!;
                });
            }
        }

        private static bool HasUnmodeledRawBytes(Param scratch, Param.Row baseline, Param.Row branch)
        {
            if (baseline.DataEquals(branch)) return false;
            var row = new Param.Row(baseline, scratch);
            foreach (var column in scratch.Columns)
            {
                var cell = row[column];
                cell.Value = branch[column].Value;
            }
            return !row.DataEquals(branch);
        }

        private void MergeValue(string target, int id, string field, object? baseValue, object? aValue, object? bValue, Action<Materialized, object?> apply)
        {
            if (ValueEquals(aValue!, bValue!)) { if (!ValueEquals(baseValue!, aValue!)) _actions.Add((_, result) => apply(result, aValue)); return; }
            if (ValueEquals(baseValue!, aValue!)) { _actions.Add((_, result) => apply(result, bValue)); return; }
            if (ValueEquals(baseValue!, bValue!)) { _actions.Add((_, result) => apply(result, aValue)); return; }
            var key = ConflictKey("field", target, id, field);
            Conflicts.Add(new Conflict(key, "field", target, id, field, DisplayValue(baseValue), DisplayValue(aValue), DisplayValue(bValue)));
            _actions.Add((decisions, result) => apply(result, decisions[key] switch { Source.Base => baseValue, Source.A => aValue, Source.B => bValue, _ => throw new ConflictRequiredException($"Invalid decision for {key}.") }));
        }

        private void AddConflict(string kind, string target, int? rowId, string? field, object? baseValue, object? aValue, object? bValue)
        {
            var key = ConflictKey(kind, target, rowId, field);
            Conflicts.Add(new Conflict(key, kind, target, rowId, field, DisplayValue(baseValue), DisplayValue(aValue), DisplayValue(bValue)));
            _actions.Add((decisions, result) => result.ApplyConflict(kind, target, rowId, decisions[key], _base, _a, _b));
        }

        private static string ConflictKey(string kind, string target, int? rowId, string? field) => $"{kind}|{target}|{rowId?.ToString(CultureInfo.InvariantCulture) ?? ""}|{field ?? ""}";

        private Report MakeReport(string smithbox)
        {
            var defs = Path.Combine(smithbox, "Assets", "PARAM", "ER", "Defs");
            var dlls = new[] { "Andre.Core.dll", "Andre.Formats.dll", "Andre.SoulsFormats.dll" }.ToDictionary(name => name, name => HashFile(Path.Combine(smithbox, name)), StringComparer.Ordinal);
            var inputs = new InputHashes(_base.Hash, _a.Hash, _b.Hash);
            var fingerprint = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes($"{Schema}\n{HashDirectory(defs)}\n{string.Join("\n", dlls.OrderBy(pair => pair.Key).Select(pair => $"{pair.Key}:{pair.Value}"))}")));
            var warnings = _base.ParseWarnings.Concat(_a.ParseWarnings).Concat(_b.ParseWarnings).OrderBy(x => x, StringComparer.Ordinal).ToList();
            if (warnings.Count > 0) warnings.Add("Unparsed PARAM entries are opaque. Equal bytes are retained from base; differing bytes become entry conflicts.");
            return new Report { Schema = Schema, Fingerprint = fingerprint, Inputs = inputs, Versions = new Versions(_base.Binder.Version, _a.Binder.Version, _b.Binder.Version), Warnings = warnings, Conflicts = Conflicts.OrderBy(c => c.Key, StringComparer.Ordinal).ToList() };
        }

        public Materialized Materialize(Dictionary<string, string> decisions)
        {
            var result = new Materialized(_base.Binder, ulong.Parse(_base.Binder.Version, CultureInfo.InvariantCulture), _defs);
            foreach (var action in _actions) action(decisions, result);
            result.FinalizeParams();
            return result;
        }

        public void Dispose() { _base.Dispose(); _a.Dispose(); _b.Dispose(); }
    }

    private sealed class Materialized
    {
        private readonly BND4 _binder;
        private readonly Dictionary<string, Param> _params = new(StringComparer.Ordinal);
        private readonly Dictionary<string, BinderFile?> _opaque = new(StringComparer.Ordinal);
        public ulong BinderVersion { get; }
        public IReadOnlyDictionary<string, PARAMDEF> Defs { get; }
        public BND4 Binder => _binder;
        public IEnumerable<(string FileKey, string ParamName, Param Param)> Params => _params.Select(pair => (pair.Key, ParamName(FindFile(_binder, pair.Key)!), pair.Value));
        public IEnumerable<(string Key, BinderFile? File)> OpaqueFiles => _opaque.Select(pair => (pair.Key, pair.Value));
        public Materialized(BND4 baseBinder, ulong version, IReadOnlyDictionary<string, PARAMDEF> defs)
        {
            BinderVersion = version; Defs = defs;
            _binder = SFUtil.DecryptERRegulation(SFUtil.EncryptERRegulation(baseBinder));
        }
        public Param GetParam(string key)
        {
            if (_params.TryGetValue(key, out var result)) return result;
            var file = FindFile(_binder, key) ?? throw new InvalidDataException($"Base binder lacks {key}.");
            result = Param.Read(file.Bytes);
            ApplyDefinition(result, ParamName(file), BinderVersion, Defs);
            var clone = new Param(result);
            foreach (var row in result.Rows) clone.AddRow(new Param.Row(row, clone));
            _params[key] = clone;
            return clone;
        }
        public Param.Row FindRow(string key, int id) => GetParam(key)[id] ?? throw new InvalidDataException($"Merged row {id} is missing in {key}.");
        public void AddRow(string key, Param.Row row, Param source)
        {
            var target = GetParam(key);
            var next = source.Rows.Skip(source.IndexOfRow(row) + 1).FirstOrDefault(candidate => target.ContainsRow(candidate.ID));
            var index = next is null ? target.Rows.Count : target.IndexOfRow(target[next.ID]);
            target.InsertRow(index, new Param.Row(row, target));
        }
        public void RemoveRow(string key, int id) { var param = GetParam(key); var row = param[id] ?? throw new InvalidDataException($"Row {id} is missing."); param.RemoveRow(row); }
        public void SetOpaque(string key, BinderFile? source) => _opaque[key] = source is null ? null : CloneFile(source);
        public void ApplyConflict(string kind, string key, int? rowId, string source, RegulationSource @base, RegulationSource a, RegulationSource b)
        {
            var selected = source switch { Source.Base => @base, Source.A => a, Source.B => b, _ => throw new ConflictRequiredException($"Invalid decision source {source}.") };
            if (kind == "binder-meta") { CopyBinderMetadata(_binder, selected.Binder); return; }
            if (kind is "entry" or "param") { SetOpaque(key, selected.Files.GetValueOrDefault(key)); return; }
            var sourceParam = selected.Params.GetValueOrDefault(key) ?? throw new InvalidDataException($"Selected source has no parsed {key}.");
            if (kind == "row-add") { if (sourceParam.Param[rowId!.Value] is { } row) AddRow(key, row, sourceParam.Param); return; }
            if (kind == "row-presence") { var target = GetParam(key); if (sourceParam.Param[rowId!.Value] is { } row) { if (target[rowId.Value] is { } old) { var index = target.IndexOfRow(old); target.RemoveRow(old); target.InsertRow(index, new Param.Row(row, target)); } else target.AddRow(new Param.Row(row, target)); } else if (target[rowId.Value] is { } old) target.RemoveRow(old); return; }
            if (kind == "row-raw") { var target = GetParam(key); var sourceRow = sourceParam.Param[rowId!.Value] ?? throw new InvalidDataException($"Selected row is absent."); var old = target[rowId.Value] ?? throw new InvalidDataException($"Target row is absent."); var index = target.IndexOfRow(old); target.RemoveRow(old); target.InsertRow(index, new Param.Row(sourceRow, target)); return; }
            throw new InvalidDataException($"Unsupported conflict kind {kind}.");
        }
        private static void CopyBinderMetadata(BND4 target, BND4 source)
        {
            target.Format = source.Format; target.Unk04 = source.Unk04; target.Unk05 = source.Unk05; target.BigEndian = source.BigEndian;
            target.BitBigEndian = source.BitBigEndian; target.Unicode = source.Unicode; target.Extended = source.Extended;
        }
        public void FinalizeParams()
        {
            foreach (var (key, param) in _params) (FindFile(_binder, key) ?? throw new InvalidDataException($"Missing {key}.")).Bytes = param.Write();
            foreach (var (key, file) in _opaque)
            {
                var existing = FindFile(_binder, key);
                if (file is null) { if (existing is not null) _binder.Files.Remove(existing); }
                else if (existing is null) _binder.Files.Add(CloneFile(file));
                else { existing.Flags = file.Flags; existing.ID = file.ID; existing.Name = file.Name; existing.CompressionType = file.CompressionType; existing.Bytes = file.Bytes.ToArray(); }
            }
        }
    }

    private sealed class ConflictRequiredException(string message) : Exception(message) { }
    private sealed class Decisions
    {
        public required InputHashes Inputs { get; init; }
        public required Dictionary<string, string> Values { get; init; }
        public static Decisions Read(string? path, InputHashes expected)
        {
            if (path is null || !File.Exists(path)) throw new FileNotFoundException("Decisions file not found.", path);
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            var inputs = InputHashes.Read(root.GetProperty("inputs"));
            if (!inputs.Equals(expected)) throw new InvalidDataException("Decisions input hashes do not match the report.");
            var values = root.GetProperty("decisions").EnumerateObject().ToDictionary(property => property.Name, property => property.Value.GetString() ?? "", StringComparer.Ordinal);
            return new Decisions { Inputs = inputs, Values = values };
        }
    }
    private sealed class Report
    {
        public string Schema { get; init; } = "";
        public string Fingerprint { get; init; } = "";
        public InputHashes Inputs { get; init; } = new("", "", "");
        public Versions Versions { get; init; } = new("", "", "");
        public List<string> Warnings { get; init; } = [];
        public List<Conflict> Conflicts { get; init; } = [];
    }
    private sealed record InputHashes(string Base, string A, string B)
    {
        public static InputHashes Read(JsonElement element) => new(element.GetProperty("base").GetString() ?? "", element.GetProperty("a").GetString() ?? "", element.GetProperty("b").GetString() ?? "");
    }
    private sealed record Versions(string Base, string A, string B);
    private sealed record Conflict(string Key, string Kind, string Target, int? RowId, string? Field, object? Base, object? A, object? B);
    private sealed class Verification
    {
        public string Schema { get; init; } = "er-regulation-build-v1";
        public InputHashes Inputs { get; init; } = new("", "", "");
        public string Output { get; init; } = "";
        public string OutputSha256 { get; init; } = "";
        public string Fingerprint { get; init; } = "";
        public string Status { get; init; } = "";
    }
    private sealed record EntrySummary(int Id, string? Name, string Flags, string Compression, string BytesSha256);
    private sealed record ParamSummary(string ParamType, int RowCount, int RowSize, object Metadata);
    private sealed record RowSummary(int Id, string? Name, Dictionary<string, object?> Fields);
    private sealed record BinderSummary(string Version, string Format, bool Unk04, bool Unk05, bool BigEndian, bool BitBigEndian, bool Unicode, byte Extended);
}
