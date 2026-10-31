using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace IraKit;

/// <summary>An action Ira proposed, shown with Yes/No or a PIN box (<c>ActionView</c> in the API).</summary>
public sealed record ProposedAction(
    string Id,
    string Tool,
    string Summary,
    string Status,
    int Tier,
    int ExpiresIn,
    bool CanApprove,
    bool CanConfirm,
    long ExpiresAt = 0);

/// <summary>One server-sent event of a streamed answer (<c>docs/api.md</c>, Streaming).</summary>
public abstract record AskEvent
{
    public sealed record Started(string ConversationId) : AskEvent;
    public sealed record ToolCalled(string Id, string Name) : AskEvent;
    public sealed record ToolFinished(string Id, string Name, bool Ok) : AskEvent;
    public sealed record Proposed(ProposedAction Action) : AskEvent;
    public sealed record Delta(string Text) : AskEvent;
    public sealed record Failed(string Message) : AskEvent;
    public sealed record Done(string Text, string? Model, string ConversationId) : AskEvent;
}

/// <summary>What happened to an action after Yes, No or the PIN (<c>ActionOutcome</c>).</summary>
public sealed record ActionOutcome(string Status, string? Message, string? Reply, int? AttemptsLeft, int? LockedSeconds);

/// <summary>Asking Ira and answering its proposals, with this PC's device key.</summary>
public sealed class AskClient(HttpClient http, ServerAddress server, string token)
{
    public async IAsyncEnumerable<AskEvent> AskAsync(
        string text, string? conversationId, [EnumeratorCancellation] CancellationToken ct = default)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, server.Api("/v1/ask/stream"))
        {
            Content = JsonContent.Create(new { text, conversation_id = conversationId }),
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));

        using var response = await Send(request, HttpCompletionOption.ResponseHeadersRead, ct);
        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var reader = new StreamReader(stream);
        while (await reader.ReadLineAsync(ct) is { } line)
        {
            if (!line.StartsWith("data:", StringComparison.Ordinal)) continue;
            var parsed = Parse(line[5..].Trim());
            if (parsed is null) continue;
            yield return parsed;
            if (parsed is AskEvent.Done) yield break;
        }
    }

    /// <summary>A Tier 2 "yes", by the action's id (never by sending the word "yes").</summary>
    public Task<ActionOutcome> ApproveAsync(string actionId, CancellationToken ct = default) =>
        ActAsync($"/v1/actions/{Uri.EscapeDataString(actionId)}/approve", null, ct);

    /// <summary>A Tier 3 confirmation with the person's PIN; the PIN goes only here.</summary>
    public Task<ActionOutcome> ConfirmAsync(string actionId, string pin, CancellationToken ct = default) =>
        ActAsync($"/v1/actions/{Uri.EscapeDataString(actionId)}/confirm", new { pin }, ct);

    /// <summary>A Tier 3 confirmation with this PC's Windows Hello signature in place of the PIN.</summary>
    public Task<ActionOutcome> ConfirmWithHelloAsync(string actionId, long deviceId, string signature, CancellationToken ct = default) =>
        ActAsync($"/v1/actions/{Uri.EscapeDataString(actionId)}/confirm", new { device_id = deviceId, signature }, ct);

    /// <summary>Stores this PC's Windows Hello public key on the server, with the person's Ira PIN.</summary>
    public async Task EnrolHelloAsync(string publicKey, string pin, CancellationToken ct = default)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, server.Api("/v1/me/approval-keys"))
        {
            Content = JsonContent.Create(new { public_key = publicKey, algorithm = HelloApproval.Algorithm, pin }),
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var response = await Send(request, HttpCompletionOption.ResponseContentRead, ct);
    }

    public Task<ActionOutcome> CancelAsync(string actionId, CancellationToken ct = default) =>
        ActAsync($"/v1/actions/{Uri.EscapeDataString(actionId)}/cancel", null, ct);

    private async Task<ActionOutcome> ActAsync(string route, object? body, CancellationToken ct)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, server.Api(route))
        {
            Content = body is null ? null : JsonContent.Create(body),
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        HttpResponseMessage response;
        try
        {
            response = await http.SendAsync(request, ct);
        }
        catch (HttpRequestException e)
        {
            throw new IraError($"Can't reach your Ira at {server.Host}.", e);
        }
        using (response)
        {
            var text = await response.Content.ReadAsStringAsync(ct);
            if (response.StatusCode == HttpStatusCode.Unauthorized) throw Revoked();
            try
            {
                var outcome = JsonSerializer.Deserialize<ActionOutcome>(text, Json.Options);
                if (outcome?.Status is not null) return outcome;
            }
            catch (JsonException)
            {
            }
            throw new IraError(Json.ErrorText(text, (int)response.StatusCode)) { Status = (int)response.StatusCode };
        }
    }

    private async Task<HttpResponseMessage> Send(HttpRequestMessage request, HttpCompletionOption option, CancellationToken ct)
    {
        HttpResponseMessage response;
        try
        {
            response = await http.SendAsync(request, option, ct);
        }
        catch (HttpRequestException e)
        {
            throw new IraError($"Can't reach your Ira at {server.Host}.", e);
        }
        if (response.IsSuccessStatusCode) return response;
        using (response)
        {
            if (response.StatusCode == HttpStatusCode.Unauthorized) throw Revoked();
            var text = await response.Content.ReadAsStringAsync(ct);
            throw new IraError(Json.ErrorText(text, (int)response.StatusCode)) { Status = (int)response.StatusCode };
        }
    }

    private static DeviceRevokedError Revoked() => new("This PC was removed from your Ira. Pair it again to use it.");

    internal static AskEvent? Parse(string data)
    {
        JsonNode? node;
        try
        {
            node = JsonNode.Parse(data);
        }
        catch (JsonException)
        {
            return null;
        }
        if (node is not JsonObject e) return null;
        string S(string name) => e[name]?.GetValue<string>() ?? "";
        return e["type"]?.GetValue<string>() switch
        {
            "start" => new AskEvent.Started(S("conversation_id")),
            "tool" => new AskEvent.ToolCalled(S("id"), S("name")),
            "tool_result" => new AskEvent.ToolFinished(S("id"), S("name"), e["ok"]?.GetValue<bool>() ?? false),
            "action" when e["action"] is JsonObject a => new AskEvent.Proposed(new ProposedAction(
                a["id"]?.GetValue<string>() ?? "",
                a["tool"]?.GetValue<string>() ?? "",
                a["summary"]?.GetValue<string>() ?? "",
                a["status"]?.GetValue<string>() ?? "pending",
                a["tier"]?.GetValue<int>() ?? 3,
                a["expires_in"]?.GetValue<int>() ?? 0,
                a["can_approve"]?.GetValue<bool>() ?? false,
                a["can_confirm"]?.GetValue<bool>() ?? false,
                a["expires_at"] is JsonValue at && at.TryGetValue(out long seconds) ? seconds : 0)),
            "delta" => new AskEvent.Delta(S("text")),
            "error" => new AskEvent.Failed(S("message")),
            "done" => new AskEvent.Done(S("text"), e["model"]?.GetValue<string>(), S("conversation_id")),
            _ => null,
        };
    }
}
