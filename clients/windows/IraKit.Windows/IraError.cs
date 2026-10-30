namespace IraKit;

/// <summary>Something went wrong that a person can act on; <see cref="Exception.Message"/> says what to do.</summary>
public class IraError(string message, Exception? inner = null) : Exception(message, inner)
{
    /// <summary>The HTTP status, when the server answered with one.</summary>
    public int? Status { get; init; }
}

/// <summary>The server no longer accepts this PC's key: it was removed or revoked.</summary>
public sealed class DeviceRevokedError(string message) : IraError(message);
