using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace IraKit.Tools;

/// <summary>
/// A tool's arguments, checked: only the names the tool knows, text that is text, numbers kept
/// in range. Anything else is refused in words the model can act on.
/// </summary>
internal sealed class ToolArgs
{
    private readonly JsonObject _args;

    public ToolArgs(JsonObject args, params string[] allowed)
    {
        var unknown = args.Select(p => p.Key).Except(allowed, StringComparer.Ordinal).Order().ToList();
        if (unknown.Count > 0) throw new ToolFailure($"unknown argument(s): {string.Join(", ", unknown)}");
        _args = args;
    }

    /// <summary>Trimmed text cut to <paramref name="limit"/> characters; null when absent or empty.</summary>
    public string? Text(string name, int limit = 500)
    {
        if (!_args.TryGetPropertyValue(name, out var node) || node is null) return null;
        if (node.GetValueKind() != JsonValueKind.String) throw new ToolFailure($"{name} must be text");
        var text = node.GetValue<string>().Trim();
        return text.Length == 0 ? null : text[..Math.Min(text.Length, limit)];
    }

    public string Required(string name, int limit, string what) =>
        Text(name, limit) ?? throw new ToolFailure($"say {what}");

    /// <summary>A whole number held to the range; null when absent.</summary>
    public int? Number(string name, int min, int max)
    {
        if (!_args.TryGetPropertyValue(name, out var node) || node is null) return null;
        if (node.GetValueKind() != JsonValueKind.Number) throw new ToolFailure($"{name} must be a number");
        // As written, so a number parsed from the server and one built in code read the same.
        if (!double.TryParse(node.ToJsonString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
            || !double.IsFinite(value))
        {
            throw new ToolFailure($"{name} must be a number");
        }
        return (int)Math.Clamp(Math.Truncate(value), min, max);
    }

    public bool? Flag(string name)
    {
        if (!_args.TryGetPropertyValue(name, out var node) || node is null) return null;
        return node.GetValueKind() switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new ToolFailure($"{name} must be true or false"),
        };
    }
}
