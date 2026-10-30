using System.Text.Json;
using System.Text.Json.Serialization;

namespace IraKit;

/// <summary>Ira's JSON: snake_case on the wire, as the server writes it.</summary>
internal static class Json
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    /// <summary>The server's error text: <c>{"detail": "..."}</c>, or a <c>message</c>, else the status.</summary>
    public static string ErrorText(string body, int status)
    {
        try
        {
            using var doc = JsonDocument.Parse(body);
            foreach (var name in new[] { "detail", "message", "error" })
            {
                if (doc.RootElement.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String)
                    return value.GetString()!;
            }
        }
        catch (JsonException)
        {
        }
        return $"Your Ira answered {status}.";
    }
}
