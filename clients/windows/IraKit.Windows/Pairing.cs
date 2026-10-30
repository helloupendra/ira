using System.Net;
using System.Net.Http.Json;

namespace IraKit;

/// <summary>What the server gives a newly paired PC.</summary>
public sealed record PairResult(
    long DeviceId,
    string Token,
    string Kind,
    string Label,
    IReadOnlyList<string> Skills,
    string Name,
    string Websocket);

/// <summary>Trades a one-time pairing code for this PC's own device key.</summary>
public static class Pairing
{
    public const string Kind = "windows";

    public static async Task<PairResult> PairAsync(HttpClient http, ServerAddress server, string code, CancellationToken ct = default)
    {
        var normalized = PairingLink.NormalizeCode(code) ?? throw new IraError("A pairing code has 8 letters and digits, like ABCD-EFGH.");
        HttpResponseMessage response;
        try
        {
            response = await http.PostAsJsonAsync(server.Api("/v1/devices/pair"), new { code = normalized, kind = Kind }, Json.Options, ct);
        }
        catch (HttpRequestException e)
        {
            throw new IraError($"Can't reach your Ira at {server.Host}. Check the address and that it is running.", e);
        }

        if (response.IsSuccessStatusCode)
        {
            var result = await response.Content.ReadFromJsonAsync<PairResult>(Json.Options, ct)
                ?? throw new IraError("Your Ira's answer was empty.");
            if (!result.Token.StartsWith("irad_", StringComparison.Ordinal))
                throw new IraError("Your Ira answered with something that is not a device key.");
            return result;
        }

        var body = await response.Content.ReadAsStringAsync(ct);
        throw new IraError(response.StatusCode switch
        {
            HttpStatusCode.Gone => "This code was used, has expired, or is for another kind of device. Make a new one under Your devices, choosing Windows PC.",
            HttpStatusCode.TooManyRequests => "Too many wrong codes. Wait 15 minutes, then try again.",
            _ => Json.ErrorText(body, (int)response.StatusCode),
        })
        { Status = (int)response.StatusCode };
    }
}
