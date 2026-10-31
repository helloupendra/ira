using System.Text;
using IraKit;

namespace IraKit.Windows.Tests;

public class HelloApprovalTests
{
    [Fact]
    public void The_PC_signs_what_the_server_checks()
    {
        // As src/ira/approval_keys.py builds it: the id, the summary's SHA-256 in hex, whole seconds.
        var signed = Encoding.UTF8.GetString(HelloApproval.Message("act_1", "Refund 5 to order A1", 1793434000));
        Assert.Equal("ira-approve:1\nact_1\n772ce40b6e80b50cb2cdb0a11e8bbc7bd1dd62ba7749579128fbb800fad4520a\n1793434000", signed);
        Assert.Equal("-_8", HelloApproval.Base64Url([0xfb, 0xff]));
    }

    [Fact]
    public void An_action_carries_when_it_expires()
    {
        var parsed = AskClient.Parse("""{"type": "action", "action": {"id": "act_1", "tool": "refund", "summary": "Refund", "tier": 3, "expires_in": 120, "expires_at": 1793434000, "can_confirm": true}}""");
        var action = Assert.IsType<AskEvent.Proposed>(parsed).Action;
        Assert.Equal(1793434000, action.ExpiresAt);
    }
}
