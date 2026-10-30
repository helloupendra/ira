using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text.Json;
using Microsoft.UI.Dispatching;

namespace Ira;

/// <summary>
/// What a second start of Ira hands to the one already running: files from File Explorer's
/// Send to, or just "show the panel". Through a pipe only this Windows account can open.
/// </summary>
internal sealed class Inbox : IDisposable
{
    public sealed record Message(bool Show, string[] Files);

    private static readonly string PipeName = $"IraForWindows-{WindowsIdentity.GetCurrent().User?.Value}";
    private readonly CancellationTokenSource _stop = new();

    public event Action<Message>? Received;

    /// <summary>The files Ira was started with by Send to ("Ira.exe --drop a.pdf b.jpg"), if any.</summary>
    public static string[] DroppedFiles(string[] args)
    {
        var at = Array.IndexOf(args, "--drop");
        return at < 0 ? [] : args[(at + 1)..].Where(a => a.Length > 0).ToArray();
    }

    /// <summary>Hands a message to the running Ira; false when none answers.</summary>
    public static bool Send(Message message)
    {
        try
        {
            using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.Out, PipeOptions.CurrentUserOnly);
            pipe.Connect(2000);
            JsonSerializer.Serialize(pipe, message);
            return true;
        }
        catch (Exception e) when (e is IOException or TimeoutException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    /// <summary>Listens until disposed; messages arrive on the UI thread.</summary>
    public void Start(DispatcherQueue ui) => _ = Task.Run(async () =>
    {
        while (!_stop.IsCancellationRequested)
        {
            try
            {
                await using var pipe = new NamedPipeServerStream(PipeName, PipeDirection.In, 1, PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await pipe.WaitForConnectionAsync(_stop.Token);
                using var reader = new StreamReader(pipe);
                var text = await reader.ReadToEndAsync(_stop.Token);
                if (text.Length > 1_000_000) continue;
                var message = JsonSerializer.Deserialize<Message>(text);
                if (message is not null) ui.TryEnqueue(() => Received?.Invoke(message));
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException)
            {
                await Task.Delay(500); // a bad message or a broken pipe: listen again
            }
        }
    });

    public void Dispose() => _stop.Cancel();
}

/// <summary>File Explorer's "Send to" menu: a shortcut there sends the chosen files with Ira.</summary>
internal static class SendTo
{
    public const string LinkName = "Ira (your devices).lnk";

    /// <summary>Adds the shortcut, or points it at this copy of Ira if it moved.</summary>
    public static void Install()
    {
        var exe = Environment.ProcessPath;
        var shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (exe is null || shellType is null) return;
        var link = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.SendTo), LinkName);
        dynamic? shell = Activator.CreateInstance(shellType);
        if (shell is null) return;
        try
        {
            dynamic shortcut = shell.CreateShortcut(link);
            if (File.Exists(link) && string.Equals((string)shortcut.TargetPath, exe, StringComparison.OrdinalIgnoreCase)) return;
            shortcut.TargetPath = exe;
            shortcut.Arguments = "--drop";
            shortcut.Description = "Send to your other devices with Ira";
            shortcut.IconLocation = exe + ",0";
            shortcut.Save();
        }
        catch (COMException)
        {
            // Send to is a convenience: Ira works without it.
        }
        finally
        {
            Marshal.FinalReleaseComObject(shell);
        }
    }
}
