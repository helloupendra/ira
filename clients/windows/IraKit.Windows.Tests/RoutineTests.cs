using System.Text.Json.Nodes;
using IraKit;

namespace IraKit.Windows.Tests;

public class RoutineTests
{
    private sealed class Probe : IRoutineProbe
    {
        public bool? Lock = false;
        public double? IdleSeconds = 600;
        public (string, string)? Net = ("192.0.2.1", "02:00:5e:0a:0b:0c");
        public bool? Locked() => Lock;
        public double? Idle() => IdleSeconds;
        public (string Gateway, string Hardware)? Network() => Net;
    }

    private sealed class Clocks
    {
        public double Wall = 1_793_440_000, Mono = 5_000;

        public void Step(double seconds, bool asleep = false)
        {
            Wall += seconds;
            if (!asleep) Mono += seconds;
        }
    }

    [Fact]
    public void The_fingerprint_is_the_Macs()
    {
        // sha256("salt-a|192.0.2.1|02:00:5e:0a:0b:0c")[:24], as the Mac and the old companion make it.
        Assert.Equal("9d6089677f4930586828a6f3", Routine.Fingerprint("salt-a", "192.0.2.1", "02:00:5e:0a:0b:0c")); // pragma: allowlist secret
        Assert.NotEqual(Routine.Fingerprint("salt-a", "192.0.2.1", "02:00:5e:0a:0b:0c"), Routine.Fingerprint("salt-b", "192.0.2.1", "02:00:5e:0a:0b:0c"));
        Assert.Equal("02:00:5e:0a:0b:0c", Routine.Hardware([0x02, 0x00, 0x5e, 0x0a, 0x0b, 0x0c]));
    }

    [Fact]
    public void Lock_unlock_sleep_wake_network_and_first_activity()
    {
        var probe = new Probe();
        var clocks = new Clocks();
        var sent = new List<JsonObject>();
        var routine = new Routine("salt", sent.Add, probe, () => clocks.Wall, () => clocks.Mono);
        static List<string> Kinds(List<JsonObject> frames) => frames.Select(f => f["kind"]!.GetValue<string>()).ToList();

        Assert.Equal(["network"], Kinds(routine.Tick()));
        clocks.Step(30);
        probe.Lock = true;
        Assert.Equal(["lock"], Kinds(routine.Tick()));
        clocks.Step(3600, asleep: true);
        probe.Lock = false;
        probe.IdleSeconds = 3;
        var frames = routine.Tick();
        Assert.Equal(["sleep", "wake", "unlock", "first_activity"], Kinds(frames));
        Assert.Equal(clocks.Wall - 3600, frames[0]["at"]!.GetValue<double>());
        Assert.Equal(clocks.Wall - 3, frames[3]["at"]!.GetValue<double>());
        clocks.Step(30);
        Assert.Empty(routine.Tick()); // the first activity is once a day
        probe.Net = ("192.0.2.254", "02:00:5e:0a:0b:0d");
        clocks.Step(30);
        var moved = routine.Tick();
        Assert.Equal(["network"], Kinds(moved));
        Assert.NotEqual(sent[0]["network"]!.GetValue<string>(), moved[0]["network"]!.GetValue<string>());
        probe.Net = null;
        clocks.Step(30);
        Assert.Empty(routine.Tick());
        Assert.All(sent, f => Assert.Equal("observe", f["type"]!.GetValue<string>()));
        // Offline, a frame carries no network at all, never its name or address.
        probe.Lock = true;
        clocks.Step(30);
        Assert.Null(routine.Tick()[0]["network"]);
    }

    [Fact]
    public void A_salt_is_made_once_and_kept()
    {
        var first = new PcPreferences().WithSalt();
        Assert.Equal(32, first.NetworkSalt.Length);
        Assert.Same(first, first.WithSalt());
    }
}
