using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace IraKit;

/// <summary>
/// Keeps this PC's device key in Windows Credential Manager, for the signed-in Windows user
/// only and never in a file or a log, as Ira for Mac keeps it in the Keychain.
/// </summary>
public sealed class DeviceKeyStore(string target = DeviceKeyStore.DefaultTarget)
{
    public const string DefaultTarget = "Ira for Windows/device key";

    public void Save(string token)
    {
        var blob = Encoding.Unicode.GetBytes(token);
        var handle = GCHandle.Alloc(blob, GCHandleType.Pinned);
        try
        {
            var credential = new Native.CREDENTIAL
            {
                Type = Native.CRED_TYPE_GENERIC,
                TargetName = target,
                UserName = Environment.UserName,
                CredentialBlob = handle.AddrOfPinnedObject(),
                CredentialBlobSize = (uint)blob.Length,
                // This PC only: a key that roamed to another PC would speak for the wrong device.
                Persist = Native.CRED_PERSIST_LOCAL_MACHINE,
            };
            if (!Native.CredWrite(ref credential, 0))
                throw new IraError("Windows did not keep Ira's key.", new Win32Exception(Marshal.GetLastWin32Error()));
        }
        finally
        {
            handle.Free();
            Array.Clear(blob);
        }
    }

    public string? Load()
    {
        if (!Native.CredRead(target, Native.CRED_TYPE_GENERIC, 0, out var pointer))
        {
            var error = Marshal.GetLastWin32Error();
            if (error == Native.ERROR_NOT_FOUND) return null;
            throw new IraError("Windows did not give back Ira's key.", new Win32Exception(error));
        }
        try
        {
            var credential = Marshal.PtrToStructure<Native.CREDENTIAL>(pointer);
            return credential.CredentialBlobSize == 0
                ? null
                : Marshal.PtrToStringUni(credential.CredentialBlob, (int)credential.CredentialBlobSize / 2);
        }
        finally
        {
            Native.CredFree(pointer);
        }
    }

    public void Delete()
    {
        if (!Native.CredDelete(target, Native.CRED_TYPE_GENERIC, 0) && Marshal.GetLastWin32Error() != Native.ERROR_NOT_FOUND)
            throw new IraError("Windows did not remove Ira's key.", new Win32Exception(Marshal.GetLastWin32Error()));
    }

    private static class Native
    {
        public const uint CRED_TYPE_GENERIC = 1;
        public const uint CRED_PERSIST_LOCAL_MACHINE = 2;
        public const int ERROR_NOT_FOUND = 1168;

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct CREDENTIAL
        {
            public uint Flags;
            public uint Type;
            public string TargetName;
            public string? Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public uint CredentialBlobSize;
            public IntPtr CredentialBlob;
            public uint Persist;
            public uint AttributeCount;
            public IntPtr Attributes;
            public string? TargetAlias;
            public string UserName;
        }

        [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredWrite(ref CREDENTIAL credential, uint flags);

        [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);

        [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredDelete(string target, uint type, uint flags);

        [DllImport("advapi32.dll")]
        public static extern void CredFree(IntPtr buffer);
    }
}
