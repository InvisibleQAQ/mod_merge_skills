// Havok behavior graph (hk2018 tagfile) loaded with HKLib and keyed for cross-file comparison.
// Key = "Type:m_name" for named hkReferencedObjects (plus a few singletons), disambiguated by the discovering
// parent and a counter. Discovery is breadth-first in field order, so equal structures get equal keys and
// objects a mod only appended keep the keys of the base. Unnamed objects are serialised inline.
using System.Collections;
using System.Globalization;
using System.Numerics;
using System.Reflection;
using System.Text.Json.Nodes;
using HKLib.hk2018;
using HKLib.Serialization.hk2018.Binary;
using SoulsFormats;

static class R
{
    static readonly Dictionary<Type, FieldInfo[]> Cache = new();

    public static string TypeName(Type t) => t.DeclaringType != null ? TypeName(t.DeclaringType) + "." + t.Name : t.Name;

    public static FieldInfo[] Fields(Type t)
    {
        if (!Cache.TryGetValue(t, out var f))
        {
            var chain = new List<Type>();
            for (var cur = t; cur != null && cur != typeof(object) && cur != typeof(ValueType); cur = cur.BaseType) chain.Insert(0, cur);
            f = chain.SelectMany(c => c.GetFields(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly).OrderBy(x => x.MetadataToken))
                .Where(x => x.Name != "m_propertyBag").ToArray();
            Cache[t] = f;
        }
        return f;
    }

    public static string NameOf(object o)
    {
        var f = o.GetType().GetField("m_name", BindingFlags.Public | BindingFlags.Instance);
        return f?.FieldType == typeof(string) ? f.GetValue(o) as string : null;
    }

    public static bool IsScalar(object v) => v == null || v is string || v.GetType().IsPrimitive || v.GetType().IsEnum
        || v is Vector4 or Quaternion or Matrix4x4 or Vector3;
    public static bool IsRefObject(object v) => v is IHavokObject && !v.GetType().IsValueType;
    public static bool IsStruct(object v) => v != null && v.GetType().IsValueType && !IsScalar(v);
}

sealed class Graph
{
    static readonly HashSet<string> Singletons = new() { "hkbBehaviorGraphData", "hkbBehaviorGraphStringData", "hkbVariableValueSet", "hkRootLevelContainer" };
    public readonly IHavokObject Root;
    public readonly Dictionary<object, string> Keys = new(ReferenceEqualityComparer.Instance);
    public readonly Dictionary<object, string> Parents = new(ReferenceEqualityComparer.Instance);
    public readonly Dictionary<string, object> ByKey = new();
    public readonly List<object> Order = new();

    public Graph(byte[] hkx)
    {
        using (var ms = new MemoryStream(hkx)) Root = new HavokBinarySerializer().Read(ms);
        Discover();
    }

    public static byte[] Write(IHavokObject root)
    {
        using var ms = new MemoryStream();
        new HavokBinarySerializer().Write(root, ms);
        return ms.ToArray();
    }

    // Accepts a behbnd (returns its single Behaviors\*.hkx entry) or a bare .hkx file.
    public static byte[] LoadBehaviorHkx(string path, out BND4 bnd, out DCX.Type dcx, out BinderFile entry)
    {
        bnd = null; dcx = DCX.Type.None; entry = null;
        byte[] raw = File.ReadAllBytes(path);
        byte[] data = DCX.Is(raw) ? DCX.Decompress(raw, out dcx) : raw;
        if (!BND4.Is(data)) return raw;
        bnd = BND4.Read(data);
        var hits = bnd.Files.Where(f => f.Name.Replace('/', '\\').Contains(@"\Behaviors\", StringComparison.OrdinalIgnoreCase)).ToList();
        if (hits.Count != 1) throw new InvalidDataException($"{path}: expected exactly one Behaviors\\*.hkx entry, found {hits.Count}");
        entry = hits[0];
        return entry.Bytes.ToArray();
    }

    void Assign(object o, string parentKey)
    {
        string type = R.TypeName(o.GetType()), name = R.NameOf(o), key;
        if (!string.IsNullOrEmpty(name)) key = $"{type}:{name}";
        else if (Singletons.Contains(type)) key = type;
        else return;
        if (ByKey.ContainsKey(key)) key = $"{key}@{parentKey}";
        string baseKey = key;
        for (int n = 2; ByKey.ContainsKey(key); n++) key = $"{baseKey}#{n}";
        ByKey[key] = o; Keys[o] = key; Parents[o] = parentKey; Order.Add(o);
    }

    void Discover()
    {
        var seen = new HashSet<object>(ReferenceEqualityComparer.Instance) { Root };
        var q = new Queue<(object, string)>();
        q.Enqueue((Root, null));
        Assign(Root, null);
        while (q.Count > 0)
        {
            var (o, parent) = q.Dequeue();
            string own = Keys.TryGetValue(o, out var k) ? k : parent;
            foreach (var f in R.Fields(o.GetType()))
                foreach (var c in Expand(f.GetValue(o)))
                {
                    if (!seen.Add(c)) continue;
                    if (c is hkReferencedObject) Assign(c, own);
                    q.Enqueue((c, own));
                }
        }
    }

    static IEnumerable<object> Expand(object v)
    {
        if (v == null || v is string || v.GetType().IsPrimitive || v.GetType().IsEnum || v.GetType().IsValueType) yield break;
        if (v is IList list) { foreach (var i in list) foreach (var c in Expand(i)) yield return c; yield break; }
        if (v is IHavokObject) yield return v;
    }

    // Structural JSON; keyed references become "@key" so the text is comparable across graphs.
    public JsonNode Ser(object v) => Ser(v, new HashSet<object>(ReferenceEqualityComparer.Instance));

    JsonNode Ser(object v, HashSet<object> path)
    {
        switch (v)
        {
            case null: return null;
            case string s: return JsonValue.Create(s);
            case bool b: return JsonValue.Create(b);
            case float f: return float.IsFinite(f) ? JsonValue.Create(f) : JsonValue.Create(f.ToString("R", CultureInfo.InvariantCulture));
            case double d: return double.IsFinite(d) ? JsonValue.Create(d) : JsonValue.Create(d.ToString("R", CultureInfo.InvariantCulture));
            case Enum e: return JsonValue.Create(e.ToString());
            case Vector4 or Quaternion or Matrix4x4 or Vector3: return JsonValue.Create(Convert.ToString(v, CultureInfo.InvariantCulture));
        }
        var t = v.GetType();
        if (t.IsPrimitive) return JsonValue.Create(Convert.ToDecimal(v));
        if (v is IList list) { var a = new JsonArray(); foreach (var i in list) a.Add(Ser(i, path)); return a; }
        if (Keys.TryGetValue(v, out var key)) return JsonValue.Create("@" + key);
        if (!t.IsValueType && !path.Add(v)) return JsonValue.Create("@cycle");
        var o = new JsonObject { ["$type"] = R.TypeName(t) };
        foreach (var f in R.Fields(t)) o[f.Name] = Ser(f.GetValue(v), path);
        if (!t.IsValueType) path.Remove(v);
        return o;
    }

    public string Sig(object v) => Ser(v)?.ToJsonString() ?? "null";

    public JsonObject FieldsJson(object o)
    {
        var path = new HashSet<object>(ReferenceEqualityComparer.Instance) { o };
        var j = new JsonObject();
        foreach (var f in R.Fields(o.GetType())) j[f.Name] = Ser(f.GetValue(o), path);
        return j;
    }

    public string SigFields(object o) => FieldsJson(o).ToJsonString();

    public object StringData => ByKey["hkbBehaviorGraphStringData"];
    public int TableCount(string field) => ((IList)StringData.GetType().GetField(field).GetValue(StringData)).Count;
}
