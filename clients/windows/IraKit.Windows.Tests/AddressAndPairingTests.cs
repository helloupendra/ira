using IraKit;

namespace IraKit.Windows.Tests;

public class AddressAndPairingTests
{
    [Theory]
    [InlineData("https://ira.example.com", "https://ira.example.com")]
    [InlineData("ira.example.com", "https://ira.example.com")]
    [InlineData("https://ira.example.com/", "https://ira.example.com")]
    [InlineData("https://example.com/ira/", "https://example.com/ira")]
    [InlineData("http://127.0.0.1:8765", "http://127.0.0.1:8765")]
    [InlineData("http://localhost:8765", "http://localhost:8765")]
    public void Good_addresses_are_kept_plain(string typed, string expected) =>
        Assert.Equal(expected, ServerAddress.Parse(typed).ToString());

    [Theory]
    [InlineData("http://ira.example.com")] // a device key must never cross a network in the clear
    [InlineData("ftp://ira.example.com")]
    [InlineData("https://user:pass@ira.example.com")] // pragma: allowlist secret
    [InlineData("https://ira.example.com/?next=x")]
    [InlineData("")]
    public void Unsafe_or_odd_addresses_are_refused(string typed) =>
        Assert.False(ServerAddress.TryParse(typed, out _, out var problem) || problem.Length == 0);

    [Fact]
    public void Routes_and_websockets_follow_the_address()
    {
        var local = ServerAddress.Parse("http://127.0.0.1:8765");
        Assert.Equal("ws://127.0.0.1:8765/v1/devices/ws", local.WebSocket("/v1/devices/ws").AbsoluteUri);
        var remote = ServerAddress.Parse("https://example.com/ira");
        Assert.Equal("https://example.com/ira/v1/devices/pair", remote.Api("/v1/devices/pair").AbsoluteUri);
        Assert.Equal("wss://example.com/ira/v1/devices/ws", remote.WebSocket("/v1/devices/ws").AbsoluteUri);
        Assert.Equal("example.com", remote.Host);
    }

    [Fact]
    public void A_pairing_link_is_found_in_whatever_was_copied()
    {
        var copied = "Pairing code for me (windows): ABCD-EFGH\nOr the link: http://127.0.0.1:8811/pair#code=ABCD-EFGH\n";
        var link = PairingLink.Find(copied);
        Assert.NotNull(link);
        Assert.Equal("http://127.0.0.1:8811", link!.Server!.ToString());
        Assert.Equal("ABCD-EFGH", link.Code);
    }

    [Theory]
    [InlineData("abcd-efgh", "ABCD-EFGH")]
    [InlineData("ABCDEFGH", "ABCD-EFGH")]
    [InlineData(" abcd efgh ", "ABCD-EFGH")]
    public void A_bare_code_is_accepted_and_tidied(string typed, string code)
    {
        var link = PairingLink.Find(typed);
        Assert.Equal(code, link!.Code);
        Assert.Null(link.Server);
    }

    [Theory]
    [InlineData("hello")]
    [InlineData("ABCD-EFG")]
    [InlineData("https://ira.example.com/pair")]
    public void Anything_else_is_not_a_pairing(string text) => Assert.Null(PairingLink.Find(text));
}
