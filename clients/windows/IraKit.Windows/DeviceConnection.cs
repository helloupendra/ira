using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace IraKit;

public enum ConnectionState { Connecting, Connected, Waiting, Revoked, Stopped }

/// <summary>What the server said in its welcome.</summary>
public sealed record Welcome(long DeviceId, string Label, IReadOnlyList<string> Skills, string Assistant, string? WakePhrase);

/// <summary>An event for this PC's person, shown as a notification ("the coding task is done").</summary>
public sealed record DeviceEvent(string Event, string Title, string Text);

/// <summary>
/// This PC's one live connection to its Ira (<c>docs/devices.md</c>): the hello with its tools,
/// then calls answered, pings, skill changes and events, reconnecting with a growing delay
/// whenever the line drops. A revoked key stops it for good.
/// </summary>
public sealed class DeviceConnection(
    ServerAddress server,
    string token,
    string label,
    string version,
    Toolbox toolbox,
    Func<IReadOnlySet<string>> localSkills)
{
    public const string Kind = "windows";
    private const int MaxFrameBytes = 1024 * 1024;
    private static readonly TimeSpan HelloLimit = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan PingEvery = TimeSpan.FromSeconds(30);

    private IReadOnlySet<string> _serverSkills = new HashSet<string>();
    private readonly SemaphoreSlim _sendLock = new(1, 1);

    public event Action<ConnectionState, string?>? StateChanged;
    public event Action<Welcome>? Welcomed;
    public event Action<IReadOnlyList<string>>? ServerSkillsChanged;
    public event Action<DeviceEvent>? EventReceived;

    /// <summary>Something new in the person's Drop from another device, or an item deleted.</summary>
    public event Action<DropFrame>? DropChanged;

    /// <summary>Skills the server has on and this PC allows: the only ones a call may use.</summary>
    public IReadOnlySet<string> EffectiveSkills => _serverSkills.Intersect(localSkills()).ToHashSet();

    public string WebsocketPath { get; init; } = "/v1/devices/ws";

    /// <summary>Runs until <paramref name="ct"/> is cancelled or the key is revoked.</summary>
    public async Task RunAsync(CancellationToken ct)
    {
        var delay = TimeSpan.FromSeconds(1);
        while (!ct.IsCancellationRequested)
        {
            StateChanged?.Invoke(ConnectionState.Connecting, null);
            var connectedAt = DateTime.UtcNow;
            string reason;
            try
            {
                reason = await SessionAsync(ct);
            }
            catch (DeviceRevokedError e)
            {
                StateChanged?.Invoke(ConnectionState.Revoked, e.Message);
                return;
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception e) when (e is WebSocketException or HttpRequestException or IOException or IraError or JsonException)
            {
                reason = e is IraError ? e.Message : $"can't reach {server.Host}";
            }

            // A connection that held for a minute was healthy: start the next wait small again.
            if (DateTime.UtcNow - connectedAt > TimeSpan.FromMinutes(1)) delay = TimeSpan.FromSeconds(1);
            var wait = delay + TimeSpan.FromMilliseconds(Random.Shared.Next(0, 1000));
            StateChanged?.Invoke(ConnectionState.Waiting, $"{reason}; trying again in {wait.TotalSeconds:0} s");
            try
            {
                await Task.Delay(wait, ct);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            delay = TimeSpan.FromSeconds(Math.Min(delay.TotalSeconds * 2, 60));
        }
        StateChanged?.Invoke(ConnectionState.Stopped, null);
    }

    /// <summary>One connection, from hello to close. Returns why it ended.</summary>
    private async Task<string> SessionAsync(CancellationToken ct)
    {
        using var socket = new ClientWebSocket();
        socket.Options.SetRequestHeader("Authorization", $"Bearer {token}");
        socket.Options.SetRequestHeader("User-Agent", $"ira-windows/{version}");
        socket.Options.KeepAliveInterval = TimeSpan.Zero; // Ira's own ping, below
        await socket.ConnectAsync(server.WebSocket(WebsocketPath), ct);

        await SendAsync(socket, new JsonObject
        {
            ["type"] = "hello",
            ["kind"] = Kind,
            ["label"] = label,
            ["version"] = version,
            ["tools"] = toolbox.HelloTools(),
        }, ct);

        using var helloLimit = CancellationTokenSource.CreateLinkedTokenSource(ct);
        helloLimit.CancelAfter(HelloLimit);
        var first = await ReceiveAsync(socket, helloLimit.Token);
        if (first is null) return CloseReason(socket);
        if (Type(first) == "error") throw new IraError($"Your Ira refused this PC: {first["error"]}");
        if (Type(first) != "welcome") return "your Ira did not welcome this PC";

        var welcome = new Welcome(
            first["deviceId"]?.GetValue<long>() ?? 0,
            first["label"]?.GetValue<string>() ?? label,
            Strings(first["skills"]),
            first["assistant"]?.GetValue<string>() ?? "Ira",
            first["wakePhrase"]?.GetValue<string>());
        _serverSkills = welcome.Skills.ToHashSet();
        StateChanged?.Invoke(ConnectionState.Connected, null);
        Welcomed?.Invoke(welcome);

        using var session = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var pinger = PingAsync(socket, session.Token);
        var calls = new List<Task>();
        try
        {
            while (true)
            {
                var frame = await ReceiveAsync(socket, session.Token);
                if (frame is null) return CloseReason(socket);
                switch (Type(frame))
                {
                    case "call":
                        calls.RemoveAll(t => t.IsCompleted);
                        calls.Add(AnswerAsync(socket, frame, session.Token));
                        break;
                    case "ping":
                        await SendAsync(socket, new JsonObject { ["type"] = "pong" }, session.Token);
                        break;
                    case "skills":
                        _serverSkills = Strings(frame["skills"]).ToHashSet();
                        ServerSkillsChanged?.Invoke(_serverSkills.ToList());
                        break;
                    case "event":
                        EventReceived?.Invoke(new DeviceEvent(
                            frame["event"]?.GetValue<string>() ?? "",
                            frame["title"]?.GetValue<string>() ?? "",
                            frame["text"]?.GetValue<string>() ?? ""));
                        break;
                    case "drop":
                        if (DropFrame.From(frame) is { } drop) DropChanged?.Invoke(drop);
                        break;
                    // "pong", "error" (a refused event, say) and frames from newer servers: nothing to do.
                }
            }
        }
        finally
        {
            await session.CancelAsync();
            try
            {
                await Task.WhenAll(calls.Append(pinger));
            }
            catch (OperationCanceledException)
            {
            }
        }
    }

    private async Task AnswerAsync(ClientWebSocket socket, JsonNode frame, CancellationToken ct)
    {
        var id = frame["id"]?.GetValue<string>() ?? "";
        var tool = frame["tool"]?.GetValue<string>() ?? "";
        var args = frame["args"] as JsonObject ?? [];
        var (ok, content, error) = await toolbox.CallAsync(tool, args, EffectiveSkills, ct);
        var reply = new JsonObject { ["type"] = "result", ["id"] = id, ["ok"] = ok };
        if (ok) reply["content"] = content;
        else reply["error"] = error;
        await SendAsync(socket, reply, ct);
    }

    private async Task PingAsync(ClientWebSocket socket, CancellationToken ct)
    {
        using var timer = new PeriodicTimer(PingEvery);
        while (await timer.WaitForNextTickAsync(ct))
            await SendAsync(socket, new JsonObject { ["type"] = "ping" }, ct);
    }

    private async Task SendAsync(ClientWebSocket socket, JsonObject frame, CancellationToken ct)
    {
        var bytes = Encoding.UTF8.GetBytes(frame.ToJsonString());
        if (bytes.Length > MaxFrameBytes)
        {
            // Too big for the server: say so instead, so the model hears why.
            bytes = Encoding.UTF8.GetBytes(new JsonObject
            {
                ["type"] = "result",
                ["id"] = frame["id"]?.GetValue<string>(),
                ["ok"] = false,
                ["error"] = "the answer was larger than 1 MB",
            }.ToJsonString());
        }
        await _sendLock.WaitAsync(ct);
        try
        {
            await socket.SendAsync(bytes, WebSocketMessageType.Text, endOfMessage: true, ct);
        }
        finally
        {
            _sendLock.Release();
        }
    }

    /// <summary>The next frame, or null when the server closed the connection.</summary>
    private static async Task<JsonNode?> ReceiveAsync(ClientWebSocket socket, CancellationToken ct)
    {
        var buffer = new byte[16 * 1024];
        using var message = new MemoryStream();
        while (true)
        {
            var part = await socket.ReceiveAsync(buffer, ct);
            if (part.MessageType == WebSocketMessageType.Close) return null;
            if (message.Length + part.Count > MaxFrameBytes) throw new IraError("your Ira sent a frame larger than 1 MB");
            message.Write(buffer, 0, part.Count);
            if (part.EndOfMessage) break;
        }
        return JsonNode.Parse(message.ToArray());
    }

    private static string CloseReason(ClientWebSocket socket) => (int?)socket.CloseStatus switch
    {
        4401 or 4403 => throw new DeviceRevokedError("This PC was removed from your Ira. Pair it again to use it."),
        4400 => throw new IraError($"Your Ira refused this PC's hello: {socket.CloseStatusDescription}"),
        4000 => "another copy of Ira on this PC took over the connection",
        4408 => "the connection went quiet",
        1001 => "your Ira is restarting",
        _ => "the connection closed",
    };

    private static string? Type(JsonNode frame) => frame["type"]?.GetValue<string>();

    private static List<string> Strings(JsonNode? node) =>
        node is JsonArray array ? array.Select(n => n?.GetValue<string>()).OfType<string>().ToList() : [];
}
