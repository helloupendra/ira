using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace IraKit;

/// <summary>What a routine reading needs from the PC (a fake one in tests).</summary>
public interface IRoutineProbe
{
    /// <summary>Whether the session is locked; null when Windows did not say.</summary>
    bool? Locked();

    /// <summary>Seconds since the last keyboard or mouse input; null when unknown.</summary>
    double? Idle();

    /// <summary>The default gateway and its hardware address, or null when offline.</summary>
    (string Gateway, string Hardware)? Network();
}

/// <summary>
/// The routine skill on this PC, as on the Mac: when it locks, sleeps and wakes, its first
/// activity of the day, and which network it is on (docs/learning.md). Only while the person
/// switched the <c>routine</c> skill on for this PC and allowed it here. Every 30 seconds it reads
/// the session's lock, the time since the last input, and the network as a hash of the default
/// gateway's hardware address with a salt kept on this PC; neither the network's name nor its
/// addresses leave the PC. It never reads the screen, which apps run, or any file. The frames
/// and the fingerprint are the Mac's, so the server treats both alike.
/// </summary>
public sealed class Routine(string salt, Action<JsonObject> send, IRoutineProbe? probe = null,
    Func<double>? clock = null, Func<double>? mono = null)
{
    public static readonly TimeSpan Interval = TimeSpan.FromSeconds(30);
    private const double SleepGap = 90, ActiveIdle = 120;

    private readonly IRoutineProbe _probe = probe ?? new WindowsProbe();
    private readonly Func<double> _clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
    private readonly Func<double> _mono = mono ?? WindowsProbe.AwakeSeconds;
    private readonly Lock _lock = new();
    private double? _wall, _monoAt;
    private bool? _wasLocked;
    private string? _network;
    private bool _seenNetwork;
    private string? _activeDay;

    /// <summary>A network's identity: salted, so the server can only tell networks apart.</summary>
    public static string Fingerprint(string salt, string gateway, string hardware) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes($"{salt}|{gateway}|{hardware}")))[..24];

    /// <summary>Forget the last reading (the skill went off): the next one starts afresh.</summary>
    public void Reset()
    {
        lock (_lock)
        {
            _wall = _monoAt = null;
            _wasLocked = null;
            _network = null;
            _seenNetwork = false;
        }
    }

    /// <summary>Read once; returns the observations sent.</summary>
    public List<JsonObject> Tick()
    {
        double now = _clock(), monoNow = _mono();
        var reading = _probe.Network();
        var locked = _probe.Locked();
        var idle = _probe.Idle();
        lock (_lock)
        {
            var sent = new List<JsonObject>();
            void Emit(string kind, double at)
            {
                var frame = new JsonObject
                {
                    ["type"] = "observe",
                    ["kind"] = kind,
                    ["at"] = Math.Round(at * 1000) / 1000,
                    ["network"] = _network,
                };
                send(frame);
                sent.Add(frame);
            }

            if (_wall is { } wall && _monoAt is { } monoAt && (now - wall) - (monoNow - monoAt) > SleepGap)
            {
                Emit("sleep", wall);
                Emit("wake", now);
            }
            _wall = now;
            _monoAt = monoNow;

            var current = reading is { } net ? Fingerprint(salt, net.Gateway, net.Hardware) : null;
            if (current != _network || !_seenNetwork)
            {
                _network = current;
                _seenNetwork = true;
                if (current is not null) Emit("network", now);
            }

            if (locked is { } isLocked && _wasLocked is { } before && isLocked != before)
                Emit(isLocked ? "lock" : "unlock", now);
            if (locked is not null) _wasLocked = locked;

            var today = DateTimeOffset.FromUnixTimeMilliseconds((long)(now * 1000)).ToLocalTime().ToString("yyyy-MM-dd");
            if (idle is { } quiet && quiet < ActiveIdle && locked != true && _activeDay != today)
            {
                _activeDay = today;
                Emit("first_activity", now - quiet);
            }
            return sent;
        }
    }

    /// <summary>A MAC address as the Mac writes it: lower case, two digits, colons.</summary>
    public static string Hardware(ReadOnlySpan<byte> address) =>
        string.Join(":", address.ToArray().Select(b => b.ToString("x2")));
}

/// <summary>Reads the real PC with what Windows ships: the session's lock, the last input, the ARP table.</summary>
public sealed class WindowsProbe : IRoutineProbe
{
    public bool? Locked()
    {
        if (!WTSQuerySessionInformationW(IntPtr.Zero, WTS_CURRENT_SESSION, WTSSessionInfoEx, out var buffer, out var bytes))
            return null;
        try
        {
            if (bytes < 16) return null;
            // WTSINFOEXW: Level (4), then WTSINFOEX_LEVEL1_W, whose SessionId, SessionState and SessionFlags
            // come first. Since Windows 10 SessionFlags is 0 when locked and 1 when unlocked.
            var flags = Marshal.ReadInt32(buffer, 12);
            return flags switch
            {
                WTS_SESSIONSTATE_LOCK => true,
                WTS_SESSIONSTATE_UNLOCK => false,
                _ => null,
            };
        }
        finally
        {
            WTSFreeMemory(buffer);
        }
    }

    public double? Idle()
    {
        var info = new LASTINPUTINFO { cbSize = (uint)Marshal.SizeOf<LASTINPUTINFO>() };
        if (!GetLastInputInfo(ref info)) return null;
        return unchecked((uint)Environment.TickCount - info.dwTime) / 1000.0;
    }

    public (string Gateway, string Hardware)? Network()
    {
        var gateway = NetworkInterface.GetAllNetworkInterfaces()
            .Where(n => n.OperationalStatus == OperationalStatus.Up && n.NetworkInterfaceType != NetworkInterfaceType.Loopback)
            .SelectMany(n => n.GetIPProperties().GatewayAddresses)
            .Select(g => g.Address)
            .FirstOrDefault(a => a.AddressFamily == AddressFamily.InterNetwork && !a.Equals(IPAddress.Any));
        if (gateway is null) return null;
        var mac = new byte[6];
        var length = (uint)mac.Length;
        if (SendARP(BitConverter.ToUInt32(gateway.GetAddressBytes(), 0), 0, mac, ref length) != 0 || length != 6) return null;
        return (gateway.ToString(), Routine.Hardware(mac));
    }

    /// <summary>Seconds the PC has been awake: Windows' interrupt time without sleep and hibernation.</summary>
    public static double AwakeSeconds()
    {
        QueryUnbiasedInterruptTime(out var hundredNanoseconds);
        return hundredNanoseconds / 10_000_000.0;
    }

    private const uint WTS_CURRENT_SESSION = 0xFFFFFFFF;
    private const int WTSSessionInfoEx = 25, WTS_SESSIONSTATE_LOCK = 0, WTS_SESSIONSTATE_UNLOCK = 1;

    [StructLayout(LayoutKind.Sequential)]
    private struct LASTINPUTINFO
    {
        public uint cbSize;
        public uint dwTime;
    }

    [DllImport("wtsapi32.dll", SetLastError = true)]
    private static extern bool WTSQuerySessionInformationW(IntPtr server, uint sessionId, int infoClass, out IntPtr buffer, out uint bytes);

    [DllImport("wtsapi32.dll")]
    private static extern void WTSFreeMemory(IntPtr memory);

    [DllImport("user32.dll")]
    private static extern bool GetLastInputInfo(ref LASTINPUTINFO info);

    [DllImport("iphlpapi.dll")]
    private static extern int SendARP(uint destination, uint source, byte[] macAddress, ref uint length);

    [DllImport("kernel32.dll")]
    private static extern bool QueryUnbiasedInterruptTime(out ulong unbiasedTime);
}
