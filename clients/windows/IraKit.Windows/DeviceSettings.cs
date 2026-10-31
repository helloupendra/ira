using System.Text.Json;

namespace IraKit;

/// <summary>
/// What this PC remembers about its pairing, beside the key (which is in Credential Manager):
/// which Ira, its name there, and the skills the person allowed <b>on this PC</b>. A skill the
/// server switches on is used only after the person allows it here too, so a server can
/// never widen what this PC does on its own.
/// </summary>
public sealed record DeviceSettings
{
    public required string Server { get; init; }
    public required long DeviceId { get; init; }
    public required string Label { get; init; }
    public string Assistant { get; init; } = "Ira";
    public string Websocket { get; init; } = "/v1/devices/ws";
    public IReadOnlyList<string> AllowedSkills { get; init; } = [];

    /// <summary>A Tier 3 action can be confirmed here with Windows Hello (its key is enrolled).</summary>
    public bool HelloApprovals { get; init; }

    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Ira", "device.json");

    public static DeviceSettings? Load(string? path = null)
    {
        path ??= DefaultPath;
        if (!File.Exists(path)) return null;
        try
        {
            return JsonSerializer.Deserialize<DeviceSettings>(File.ReadAllText(path), Json.Options);
        }
        catch (JsonException)
        {
            return null; // a damaged file: the PC is treated as not paired
        }
    }

    public void Save(string? path = null)
    {
        path ??= DefaultPath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temp = path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(this, Json.Options));
        File.Move(temp, path, overwrite: true);
    }

    public static void Delete(string? path = null)
    {
        path ??= DefaultPath;
        if (File.Exists(path)) File.Delete(path);
    }
}
