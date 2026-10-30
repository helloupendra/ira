using System.Text.Json.Nodes;

namespace IraKit.Tools;

/// <summary>JSON Schema pieces for the hello's tool parameters, as the Mac's ToolCatalog writes them.</summary>
internal static class Schema
{
    public static JsonObject Object(JsonObject? properties = null, params string[] required)
    {
        var schema = new JsonObject
        {
            ["type"] = "object",
            ["properties"] = properties ?? [],
            ["additionalProperties"] = false,
        };
        if (required.Length > 0) schema["required"] = new JsonArray(required.Select(r => (JsonNode)r).ToArray());
        return schema;
    }

    public static JsonObject Text(string description) => new() { ["type"] = "string", ["description"] = description };

    public static JsonObject Integer(string description, int min, int max) => new()
    {
        ["type"] = "integer",
        ["minimum"] = min,
        ["maximum"] = max,
        ["description"] = description,
    };

    public static JsonObject Flag(string description) => new() { ["type"] = "boolean", ["description"] = description };

    public static JsonObject OneOf(string description, IEnumerable<string> values) => new()
    {
        ["type"] = "string",
        ["enum"] = new JsonArray(values.Select(v => (JsonNode)v).ToArray()),
        ["description"] = description,
    };
}
