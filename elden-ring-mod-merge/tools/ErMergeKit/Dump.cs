// Read-only dumps used for analysis and verification.
//   bnd-list   : one TSV line per binder entry (ID, name, flags, size, SHA-256), optional extraction
//   tae-dump   : one JSON line per TAE file and per animation; events carry raw parameter bytes ("raw", the
//                ground truth for equality) and, with a template, decoded values ("p", display only)
//   param-dump : one TSV per param (all fields after applying the paramdef) plus _meta.tsv
using System.Globalization;
using System.Text;
using System.Text.Json;
using Andre.Formats;
using SoulsFormats;

static class Dump
{
    public static int BndList(string path, string outTsv, string extractDir)
    {
        var bnd = Util.ReadBnd(path, out DCX.Type dcx);
        var sb = new StringBuilder();
        sb.AppendLine($"#dcx\t{dcx}\tversion\t{bnd.Version}\tfiles\t{bnd.Files.Count}");
        sb.AppendLine("ID\tName\tFlags\tSize\tSHA256");
        foreach (var f in bnd.Files.OrderBy(f => f.ID))
        {
            var bytes = f.Bytes.Span;
            sb.AppendLine($"{f.ID}\t{f.Name}\t{f.Flags}\t{bytes.Length}\t{Util.Sha(bytes)}");
            if (extractDir == null) continue;
            string rel = f.Name.Replace('\\', '/');
            int colon = rel.IndexOf(':');
            if (colon >= 0) rel = rel[(colon + 1)..];
            Util.Save(Path.Combine(extractDir, rel.TrimStart('/')), bytes.ToArray());
        }
        Util.Save(outTsv, new UTF8Encoding(false).GetBytes(sb.ToString()));
        Console.WriteLine($"{path}: {bnd.Files.Count} entries, dcx={dcx}");
        return 0;
    }

    static string Fmt(object v) => v switch
    {
        null => "",
        float f => f.ToString("R", CultureInfo.InvariantCulture),
        double d => d.ToString("R", CultureInfo.InvariantCulture),
        byte[] b => Convert.ToHexString(b),
        string s => s.Replace("\t", "\\t").Replace("\r", "\\r").Replace("\n", "\\n"),
        System.Collections.IEnumerable e => "[" + string.Join(",", e.Cast<object>().Select(Fmt)) + "]",
        _ => Convert.ToString(v, CultureInfo.InvariantCulture),
    };

    public static int TaeDump(string path, string outJsonl, string templatePath)
    {
        var bnd = Util.ReadBnd(path, out _);
        var bank = templatePath != null ? LoadBanklessTemplate(templatePath) : null;
        Directory.CreateDirectory(Path.GetDirectoryName(outJsonl));
        using var w = new StreamWriter(outJsonl, false, new UTF8Encoding(false));
        int taes = 0, anims = 0;
        foreach (var f in bnd.Files.Where(f => f.Name.EndsWith(".tae", StringComparison.OrdinalIgnoreCase)).OrderBy(f => f.ID))
        {
            var tae = TAE.Read(f.Bytes);
            var raw = new Dictionary<TAE.Event, string>(ReferenceEqualityComparer.Instance);
            foreach (var ev in tae.Animations.SelectMany(x => x.Events))
            {
                raw[ev] = Convert.ToHexString(ev.GetParameterBytes(tae.BigEndian));
                if (bank != null && bank.TryGetValue(ev.Type, out var t))
                    try { ev.ApplyTemplate(tae.BigEndian, t, lenientOnAssert: true); } catch { }
            }
            taes++;
            string entry = Util.ShortName(f.Name);
            w.WriteLine(JsonSerializer.Serialize(new
            {
                kind = "tae", entry, binderId = f.ID, taeId = tae.ID, format = tae.Format.ToString(), skeleton = tae.SkeletonName,
                sib = tae.SibName, eventBank = tae.EventBank, flags = Convert.ToHexString(tae.Flags ?? Array.Empty<byte>()),
                animCount = tae.Animations.Count, sha256 = Util.Sha(f.Bytes.Span),
            }));
            foreach (var anim in tae.Animations)
            {
                anims++;
                w.WriteLine(JsonSerializer.Serialize(new
                {
                    kind = "anim", entry, taeId = tae.ID, id = anim.ID, file = anim.AnimFileName, sig = TaeMerge.Sig(anim, tae.BigEndian),
                    header = TaeMerge.HeaderText(anim.MiniHeader),
                    groups = anim.EventGroups?.Select(g => g.GroupType).ToList(),
                    events = anim.Events.Select(ev => new
                    {
                        type = ev.Type, name = ev.Template != null ? ev.TypeName : null, start = ev.StartTime, end = ev.EndTime,
                        group = ev.Group?.GroupType, raw = raw[ev],
                        p = ev.Template != null ? ev.Parameters?.Values.ToDictionary(kv => kv.Key, kv => Fmt(kv.Value)) : null,
                    }).ToList(),
                }));
            }
        }
        Console.WriteLine($"{path}: {taes} tae, {anims} animations");
        return 0;
    }

    // Smithbox's TAE.Template.ER.xml has no <bank> level and repeats enum names; wrap the events in bank -1
    // (the EventBank ER TAEs carry) and de-duplicate names so SoulsFormats accepts it.
    static TAE.Template.BankTemplate LoadBanklessTemplate(string path)
    {
        var doc = new System.Xml.XmlDocument();
        doc.Load(path);
        var root = doc.SelectSingleNode("event_template");
        if (root.SelectNodes("bank").Count == 0)
        {
            var bankNode = doc.CreateElement("bank");
            bankNode.SetAttribute("id", "-1");
            bankNode.SetAttribute("name", "ER");
            foreach (var ev in root.SelectNodes("event").Cast<System.Xml.XmlNode>().ToList()) bankNode.AppendChild(root.RemoveChild(ev));
            root.AppendChild(bankNode);
        }
        foreach (var param in doc.SelectNodes("//event/*").Cast<System.Xml.XmlNode>())
        {
            var seen = new HashSet<string>();
            foreach (var e in param.SelectNodes("entry").Cast<System.Xml.XmlElement>())
                if (!seen.Add(e.GetAttribute("name"))) e.SetAttribute("name", $"{e.GetAttribute("name")} #{e.GetAttribute("value")}");
        }
        return TAE.Template.ReadXMLDoc(doc)[-1];
    }

    public static Dictionary<string, PARAMDEF> LoadDefs(string defsDir) =>
        Directory.GetFiles(defsDir, "*.xml").Select(x => PARAMDEF.XmlDeserialize(x, true))
            .GroupBy(d => d.ParamType).ToDictionary(g => g.Key, g => g.First());

    public static Param LoadParam(BinderFile f, Dictionary<string, PARAMDEF> defs, ulong version)
    {
        var p = Param.ReadIgnoreCompression(f.Bytes);
        if (p.ParamType == null || !defs.TryGetValue(p.ParamType, out var d)) return null;
        p.ApplyParamdef(d, version, Path.GetFileNameWithoutExtension(f.Name.Replace('\\', '/')));
        return p;
    }

    public static int ParamDump(string regPath, string defsDir, string outDir)
    {
        Directory.CreateDirectory(outDir);
        var bnd = SFUtil.DecryptERRegulation(regPath);
        ulong version = ulong.Parse(bnd.Version);
        var defs = LoadDefs(defsDir);
        var meta = new StringBuilder($"#regulationVersion\t{bnd.Version}\tfiles\t{bnd.Files.Count}\tcompression\t{bnd.Compression}\n");
        meta.AppendLine("Param\tParamType\tRows\tDefApplied");
        int missing = 0;
        foreach (var f in bnd.Files.OrderBy(f => f.ID).Where(f => f.Name.EndsWith(".param", StringComparison.OrdinalIgnoreCase)))
        {
            string name = Path.GetFileNameWithoutExtension(f.Name.Replace('\\', '/'));
            Param p = null;
            try { p = LoadParam(f, defs, version); } catch { }
            using var w = new StreamWriter(Path.Combine(outDir, name + ".tsv"), false, new UTF8Encoding(false));
            if (p == null)
            {
                missing++;
                var raw = Param.ReadIgnoreCompression(f.Bytes);
                meta.AppendLine($"{name}\t{raw.ParamType}\t{raw.Rows.Count}\tfalse");
                w.WriteLine("ID\tName");
                foreach (var r in raw.Rows) w.WriteLine($"{r.ID}\t{Fmt(r.Name ?? "")}");
                continue;
            }
            meta.AppendLine($"{name}\t{p.ParamType}\t{p.Rows.Count}\ttrue");
            var cols = p.Columns.ToList();
            w.WriteLine("ID\tName\t" + string.Join("\t", cols.Select(c => c.Def.InternalName)));
            foreach (var r in p.Rows) w.WriteLine($"{r.ID}\t{Fmt(r.Name ?? "")}\t" + string.Join("\t", cols.Select(c => Fmt(c.GetValue(r)))));
        }
        File.WriteAllText(Path.Combine(outDir, "_meta.tsv"), meta.ToString(), new UTF8Encoding(false));
        Console.WriteLine($"{regPath}: version {bnd.Version}, {bnd.Files.Count} files, {missing} params without paramdef");
        return 0;
    }
}
