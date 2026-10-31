using IraKit;
using Microsoft.UI.Dispatching;

namespace Ira;

/// <summary>
/// The app's one view of its pairing and connection: the device key, the PC's settings, the
/// live device connection, and asking. Everything it raises arrives on the UI thread.
/// </summary>
public sealed class IraController
{
    public const string Version = "0.1.0";

    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(120) };
    private readonly DeviceKeyStore _keys = new();
    private DispatcherQueue? _ui;
    private DeviceSettings? _settings;
    private string? _token;
    private CancellationTokenSource? _running;

    /// <summary>Paired or not, connected or not: redraw.</summary>
    public event Action? Changed;

    /// <summary>The server has skills on for this PC that the person has not allowed here yet.</summary>
    public event Action<IReadOnlyList<string>>? SkillsToAllow;

    public event Action<DeviceEvent>? EventReceived;

    /// <summary>Something new in the Drop from another device, or an item deleted.</summary>
    public event Action<DropFrame>? DropChanged;

    /// <summary>The connection is (back) up: catch up on what arrived meanwhile.</summary>
    public event Action? Connected;

    /// <summary>What Ira used on this PC since it started, for "What I read".</summary>
    public ReadLog Log { get; } = new();

    /// <summary>The shortcut and the folders Ira may use, chosen in Settings.</summary>
    public PcPreferences Preferences { get; private set; } = PcPreferences.Load();

    /// <summary>The skills Ira has on for this PC, as the server last said.</summary>
    public IReadOnlyList<string> ServerSkills { get; private set; } = [];

    public ConnectionState State { get; private set; } = ConnectionState.Stopped;
    public string? StateDetail { get; private set; }

    /// <summary>Why the pairing ended, shown on the pairing page ("Ira removed this PC").</summary>
    public string? Notice { get; private set; }
    public DeviceSettings? Settings => _settings;
    public bool IsPaired => _settings is not null && _token is not null;
    public ServerAddress? Server => _settings is null ? null : ServerAddress.Parse(_settings.Server);

    public AskClient? Ask => IsPaired ? new AskClient(_http, Server!, _token!) : null;

    public DropClient? Drop => IsPaired ? new DropClient(_http, Server!, _token!) : null;

    public void Start(DispatcherQueue ui)
    {
        _ui = ui;
        _settings = DeviceSettings.Load();
        _token = _settings is null ? null : _keys.Load();
        if (_settings is not null && _token is null) _settings = null; // a key that went missing: pair again
        Connect();
    }

    /// <summary>Pairs this PC. The skills chosen in Ira (with the PIN) are allowed here by pressing Pair.</summary>
    public async Task<PairResult> PairAsync(ServerAddress server, string code, CancellationToken ct = default)
    {
        var result = await Pairing.PairAsync(_http, server, code, ct);
        Stop();
        _keys.Save(result.Token);
        _settings = new DeviceSettings
        {
            Server = server.ToString(),
            DeviceId = result.DeviceId,
            Label = result.Label,
            Assistant = result.Name,
            Websocket = result.Websocket,
            AllowedSkills = result.Skills,
        };
        _settings.Save();
        _token = result.Token;
        Notice = null;
        Connect();
        Raise();
        return result;
    }

    /// <summary>Forgets the pairing on this PC: the key, the settings and the connection.</summary>
    public void Unpair(string? notice = null)
    {
        Stop();
        _keys.Delete();
        DeviceSettings.Delete();
        _settings = null;
        _token = null;
        State = ConnectionState.Stopped;
        Notice = notice;
        Raise();
    }

    /// <summary>Allows skills on this PC, after the person said yes here.</summary>
    public void Allow(IEnumerable<string> skills)
    {
        if (_settings is null) return;
        _settings = _settings with { AllowedSkills = _settings.AllowedSkills.Union(skills).Order().ToList() };
        _settings.Save();
        Raise();
    }

    /// <summary>Allows or stops one skill on this PC, from Settings.</summary>
    public void SetAllowed(string skill, bool allowed)
    {
        if (_settings is null) return;
        var skills = allowed ? _settings.AllowedSkills.Append(skill) : _settings.AllowedSkills.Where(s => s != skill);
        _settings = _settings with { AllowedSkills = skills.Distinct().Order().ToList() };
        _settings.Save();
        Raise();
    }

    public void SavePreferences(PcPreferences preferences)
    {
        Preferences = preferences;
        preferences.Save();
        Raise();
    }

    public void Stop()
    {
        _running?.Cancel();
        _running = null;
    }

    private void Connect()
    {
        Stop();
        if (!IsPaired) return;
        var connection = new DeviceConnection(Server!, _token!, _settings!.Label, Version, Tools.Create(() => Preferences.Policy(), Log),
            () => _settings?.AllowedSkills.ToHashSet() ?? [])
        {
            WebsocketPath = _settings.Websocket,
        };
        connection.StateChanged += (state, detail) => OnUi(() =>
        {
            State = state;
            StateDetail = detail;
            if (state == ConnectionState.Revoked) Unpair("Ira removed this PC. Pair it again to use it.");
            else Raise();
        });
        connection.Welcomed += welcome => OnUi(() =>
        {
            AskToAllow(welcome.Skills);
            Connected?.Invoke();
        });
        connection.ServerSkillsChanged += skills => OnUi(() => AskToAllow(skills));
        connection.EventReceived += e => OnUi(() => EventReceived?.Invoke(e));
        connection.DropChanged += frame => OnUi(() => DropChanged?.Invoke(frame));
        _running = new CancellationTokenSource();
        _ = connection.RunAsync(_running.Token);
    }

    private void AskToAllow(IReadOnlyList<string> serverSkills)
    {
        ServerSkills = serverSkills;
        Raise();
        var missing = serverSkills.Except(_settings?.AllowedSkills ?? []).ToList();
        if (missing.Count > 0) SkillsToAllow?.Invoke(missing);
    }

    private void Raise() => Changed?.Invoke();

    private void OnUi(Action action)
    {
        if (_ui is null || _ui.HasThreadAccess) action();
        else _ui.TryEnqueue(() => action());
    }
}
