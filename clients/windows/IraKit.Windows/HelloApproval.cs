using System.Security.Cryptography;
using System.Text;
using Windows.Security.Credentials;
using Windows.Security.Cryptography;
using Windows.Security.Cryptography.Core;

namespace IraKit;

/// <summary>
/// Confirming a Tier 3 action with Windows Hello instead of typing the PIN (docs/security.md,
/// Approvals). Windows Hello keeps an RSA key that only the person's face, finger or Hello PIN
/// unlocks; the server stored its public key once, with the Ira PIN, as RS256.
/// </summary>
public static class HelloApproval
{
    public const string Algorithm = "RS256";

    /// <summary>
    /// What the PC signs: the action's id, a hash of the summary the person was shown, and when
    /// it expires, so a signature is good for that one action only.
    /// </summary>
    public static byte[] Message(string actionId, string summary, long expiresAt)
    {
        var digest = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(summary)));
        return Encoding.UTF8.GetBytes($"ira-approve:1\n{actionId}\n{digest}\n{expiresAt}");
    }

    public static string Base64Url(byte[] data) =>
        Convert.ToBase64String(data).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}

/// <summary>The PC's Windows Hello key for approvals, kept by Windows for this Windows user.</summary>
public static class HelloKey
{
    private const string Name = "Ira approvals";

    public static async Task<bool> IsSupportedAsync() => await KeyCredentialManager.IsSupportedAsync();

    /// <summary>A new key (Windows asks for the person's face, finger or Hello PIN): its public key, base64 SubjectPublicKeyInfo.</summary>
    public static async Task<string> CreateAsync()
    {
        var made = await KeyCredentialManager.RequestCreateAsync(Name, KeyCredentialCreationOption.ReplaceExisting);
        if (made.Status != KeyCredentialStatus.Success) throw new IraError(Words(made.Status));
        var spki = made.Credential.RetrievePublicKey(CryptographicPublicKeyBlobType.X509SubjectPublicKeyInfo);
        CryptographicBuffer.CopyToByteArray(spki, out var bytes);
        return Convert.ToBase64String(bytes);
    }

    /// <summary>Signs [data] after Windows Hello's check: the signature, base64url.</summary>
    public static async Task<string> SignAsync(byte[] data)
    {
        var opened = await KeyCredentialManager.OpenAsync(Name);
        if (opened.Status != KeyCredentialStatus.Success) throw new IraError(Words(opened.Status));
        var signed = await opened.Credential.RequestSignAsync(CryptographicBuffer.CreateFromByteArray(data));
        if (signed.Status != KeyCredentialStatus.Success) throw new IraError(Words(signed.Status));
        CryptographicBuffer.CopyToByteArray(signed.Result, out var signature);
        return HelloApproval.Base64Url(signature);
    }

    public static async Task DeleteAsync()
    {
        try
        {
            await KeyCredentialManager.DeleteAsync(Name);
        }
        catch (Exception e) when (e is FileNotFoundException or ArgumentException or System.Runtime.InteropServices.COMException)
        {
            // none to delete
        }
    }

    private static string Words(KeyCredentialStatus status) => status switch
    {
        KeyCredentialStatus.UserCanceled => "Windows Hello was cancelled. Type your PIN instead.",
        KeyCredentialStatus.NotFound => "This PC has no Windows Hello key for Ira: set it up again in Settings.",
        KeyCredentialStatus.UserPrefersPassword => "Type your PIN instead.",
        KeyCredentialStatus.SecurityDeviceLocked => "Windows Hello is locked for now. Type your PIN instead.",
        _ => "Windows Hello did not work. Type your PIN instead.",
    };
}
