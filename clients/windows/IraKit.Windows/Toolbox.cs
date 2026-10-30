using System.Text.Json.Nodes;

namespace IraKit;

/// <summary>A tool failed in a way the model should hear, in plain words ("there is no file at that path").</summary>
public sealed class ToolFailure(string message) : Exception(message);

/// <summary>
/// One thing this PC can do for its person. The <see cref="Tier"/> is the PC's own word on how
/// careful Ira must be (0 reads, 1 small and undoable, 2 needs a yes, 3 needs the PIN); the
/// server takes it from the hello, never from the model.
/// </summary>
public sealed record DeviceTool(
    string Name,
    string Description,
    string Skill,
    int Tier,
    JsonObject Parameters,
    Func<JsonObject, CancellationToken, Task<JsonNode>> Run);

/// <summary>The tools this PC offers, and the one place a call is checked before it runs.</summary>
public sealed class Toolbox
{
    /// <summary>Under the server's 25 seconds, so a slow tool fails here and says so.</summary>
    public static readonly TimeSpan CallLimit = TimeSpan.FromSeconds(20);

    private readonly Dictionary<string, DeviceTool> _tools;

    public Toolbox(IEnumerable<DeviceTool> tools) =>
        _tools = tools.ToDictionary(t => t.Name, StringComparer.Ordinal);

    public IReadOnlyCollection<DeviceTool> Tools => _tools.Values;

    /// <summary>The tools as the hello lists them.</summary>
    public JsonArray HelloTools() => new(_tools.Values.Select(t => (JsonNode)new JsonObject
    {
        ["name"] = t.Name,
        ["description"] = t.Description,
        ["parameters"] = t.Parameters.DeepClone(),
        ["skill"] = t.Skill,
        ["tier"] = t.Tier,
    }).ToArray());

    /// <summary>
    /// Runs a call only if its skill is on both on the server and on this PC. The reply is the
    /// tool's content, or a sentence saying why it did not run.
    /// </summary>
    public async Task<(bool Ok, JsonNode? Content, string? Error)> CallAsync(
        string name, JsonObject args, IReadOnlySet<string> allowedSkills, CancellationToken ct)
    {
        if (!_tools.TryGetValue(name, out var tool)) return (false, null, $"this PC has no tool called {name}");
        if (!allowedSkills.Contains(tool.Skill))
            return (false, null, $"the {tool.Skill} skill is off on this PC; switch it on in Ira's settings on the PC");

        using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
        limit.CancelAfter(CallLimit);
        try
        {
            return (true, await tool.Run(args, limit.Token), null);
        }
        catch (ToolFailure failure)
        {
            return (false, null, failure.Message);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return (false, null, $"{name} took longer than {CallLimit.TotalSeconds:0} seconds and was stopped");
        }
        catch (Exception e) when (e is not OperationCanceledException)
        {
            // Never the exception's text: it can hold a path or data the model should not see.
            return (false, null, $"{name} failed on this PC ({e.GetType().Name})");
        }
    }
}
