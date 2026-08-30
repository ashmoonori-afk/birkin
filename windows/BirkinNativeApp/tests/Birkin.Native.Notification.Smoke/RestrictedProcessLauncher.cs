using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

internal static class RestrictedProcessLauncher
{
    private const uint MediumIntegrityRid = 0x2000;
    private const uint WaitObject0 = 0x00000000;
    private const uint WaitTimeout = 0x00000102;
    private const uint WaitFailed = 0xFFFFFFFF;
    private const uint ChildTimeoutMilliseconds = 45_000;
    private const uint TerminationTimeoutMilliseconds = 5_000;
    private const uint SeGroupIntegrity = 0x00000020;
    private const string MediumIntegritySid = "S-1-16-8192";

    public static uint GetCurrentIntegrityRid()
    {
        using var identity = WindowsIdentity.GetCurrent();
        _ = GetTokenInformation(
            identity.AccessToken,
            TokenInformationClass.TokenIntegrityLevel,
            IntPtr.Zero,
            0,
            out var bufferLength);
        if (bufferLength == 0)
        {
            throw LastError("GetTokenInformation size query");
        }

        var buffer = Marshal.AllocHGlobal(bufferLength);
        try
        {
            if (!GetTokenInformation(
                    identity.AccessToken,
                    TokenInformationClass.TokenIntegrityLevel,
                    buffer,
                    bufferLength,
                    out _))
            {
                throw LastError("GetTokenInformation");
            }

            var label = Marshal.PtrToStructure<TokenMandatoryLabel>(buffer);
            var countPointer = GetSidSubAuthorityCount(label.Label.Sid);
            var count = Marshal.ReadByte(countPointer);
            var ridPointer = GetSidSubAuthority(label.Label.Sid, (uint)(count - 1));
            return unchecked((uint)Marshal.ReadInt32(ridPointer));
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    public static int RunCurrentExecutable()
    {
        var executable = Environment.ProcessPath
            ?? throw new InvalidOperationException("The smoke executable path is unavailable.");
        var outputPath = Path.Combine(
            Path.GetTempPath(),
            $"birkin-toast-{Guid.NewGuid():N}.log");
        try
        {
            try
            {
                return RunRestrictedProcess(executable, outputPath);
            }
            finally
            {
                if (File.Exists(outputPath))
                {
                    Console.Write(File.ReadAllText(outputPath));
                }
            }
        }
        finally
        {
            File.Delete(outputPath);
        }
    }

    public static bool IsMediumIntegrity(uint rid) => rid == MediumIntegrityRid;

    private static int RunRestrictedProcess(string executable, string outputPath)
    {
        using var currentToken = OpenCurrentProcessToken();
        using var restrictedToken = CreateLuaToken(currentToken);
        SetMediumIntegrity(restrictedToken);
        var startupInfo = new StartupInfo
        {
            Size = Marshal.SizeOf<StartupInfo>(),
        };
        var commandLine = new StringBuilder(
            $"\"{executable}\" --medium-child --result \"{outputPath}\"");
        if (!CreateProcessAsUserW(
                restrictedToken,
                executable,
                commandLine,
                processAttributes: IntPtr.Zero,
                threadAttributes: IntPtr.Zero,
                inheritHandles: false,
                creationFlags: 0,
                environment: IntPtr.Zero,
                currentDirectory: AppContext.BaseDirectory,
                startupInfo: ref startupInfo,
                processInformation: out var processInformation))
        {
            throw LastError("CreateProcessAsUser");
        }

        using var process = new SafeProcessHandle(processInformation.Process, ownsHandle: true);
        using var thread = new SafeWaitHandle(processInformation.Thread, ownsHandle: true);
        var waitResult = WaitForSingleObject(process, ChildTimeoutMilliseconds);
        if (waitResult == WaitTimeout)
        {
            if (!TerminateProcess(process, 124))
            {
                throw LastError("TerminateProcess");
            }

            _ = WaitForSingleObject(process, TerminationTimeoutMilliseconds);
            throw new TimeoutException("The restricted notification smoke exceeded 45 seconds.");
        }

        if (waitResult == WaitFailed)
        {
            throw LastError("WaitForSingleObject");
        }

        if (waitResult != WaitObject0)
        {
            throw new InvalidOperationException($"Unexpected process wait result: 0x{waitResult:x8}.");
        }

        if (!GetExitCodeProcess(process, out var exitCode))
        {
            throw LastError("GetExitCodeProcess");
        }

        return unchecked((int)exitCode);
    }

    private static SafeAccessTokenHandle OpenCurrentProcessToken()
    {
        var access = TokenAccessLevels.AdjustDefault |
            TokenAccessLevels.AssignPrimary |
            TokenAccessLevels.Duplicate |
            TokenAccessLevels.Query;
        if (!OpenProcessToken(GetCurrentProcess(), access, out var token))
        {
            throw LastError("OpenProcessToken");
        }

        return token;
    }

    private static SafeAccessTokenHandle CreateLuaToken(SafeAccessTokenHandle currentToken)
    {
        var flags = RestrictedTokenFlags.DisableMaxPrivilege |
            RestrictedTokenFlags.LuaToken;
        if (!CreateRestrictedToken(
                currentToken,
                flags,
                0,
                IntPtr.Zero,
                0,
                IntPtr.Zero,
                0,
                IntPtr.Zero,
                out var restrictedToken))
        {
            throw LastError("CreateRestrictedToken");
        }

        return restrictedToken;
    }

    private static void SetMediumIntegrity(SafeAccessTokenHandle token)
    {
        if (!ConvertStringSidToSidW(MediumIntegritySid, out var sid))
        {
            throw LastError("ConvertStringSidToSid");
        }

        try
        {
            var sidLength = GetLengthSid(sid);
            if (sidLength == 0)
            {
                throw LastError("GetLengthSid");
            }

            var label = new TokenMandatoryLabel
            {
                Label = new SidAndAttributes
                {
                    Sid = sid,
                    Attributes = SeGroupIntegrity,
                },
            };
            var labelSize = Marshal.SizeOf<TokenMandatoryLabel>();
            var labelBuffer = Marshal.AllocHGlobal(labelSize);
            try
            {
                Marshal.StructureToPtr(label, labelBuffer, fDeleteOld: false);
                var informationLength = checked(labelSize + (int)sidLength);
                if (!SetTokenInformation(
                        token,
                        TokenInformationClass.TokenIntegrityLevel,
                        labelBuffer,
                        informationLength))
                {
                    throw LastError("SetTokenInformation");
                }
            }
            finally
            {
                Marshal.FreeHGlobal(labelBuffer);
            }
        }
        finally
        {
            _ = LocalFree(sid);
        }
    }

    private static Win32Exception LastError(string operation) =>
        new(Marshal.GetLastWin32Error(), $"{operation} failed.");

    [Flags]
    private enum RestrictedTokenFlags : uint
    {
        DisableMaxPrivilege = 0x00000001,
        LuaToken = 0x00000004,
    }

    private enum TokenInformationClass
    {
        TokenIntegrityLevel = 25,
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes
    {
        public IntPtr Sid;
        public uint Attributes;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct TokenMandatoryLabel
    {
        public SidAndAttributes Label;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int Size;
        public string? Reserved;
        public string? Desktop;
        public string? Title;
        public uint X;
        public uint Y;
        public uint XSize;
        public uint YSize;
        public uint XCountChars;
        public uint YCountChars;
        public uint FillAttribute;
        public uint Flags;
        public ushort ShowWindow;
        public ushort Reserved2Size;
        public IntPtr Reserved2;
        public IntPtr StandardInput;
        public IntPtr StandardOutput;
        public IntPtr StandardError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation
    {
        public IntPtr Process;
        public IntPtr Thread;
        public uint ProcessId;
        public uint ThreadId;
    }

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(
        IntPtr processHandle,
        TokenAccessLevels desiredAccess,
        out SafeAccessTokenHandle tokenHandle);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateRestrictedToken(
        SafeAccessTokenHandle existingTokenHandle,
        RestrictedTokenFlags flags,
        uint disableSidCount,
        IntPtr sidsToDisable,
        uint deletePrivilegeCount,
        IntPtr privilegesToDelete,
        uint restrictedSidCount,
        IntPtr sidsToRestrict,
        out SafeAccessTokenHandle newTokenHandle);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSidToSidW(
        string stringSid,
        out IntPtr sid);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessAsUserW(
        SafeAccessTokenHandle token,
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref StartupInfo startupInfo,
        out ProcessInformation processInformation);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetTokenInformation(
        SafeAccessTokenHandle tokenHandle,
        TokenInformationClass tokenInformationClass,
        IntPtr tokenInformation,
        int tokenInformationLength,
        out int returnLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint GetLengthSid(IntPtr sid);

    [DllImport("advapi32.dll")]
    private static extern IntPtr GetSidSubAuthorityCount(IntPtr sid);

    [DllImport("advapi32.dll")]
    private static extern IntPtr GetSidSubAuthority(IntPtr sid, uint subAuthority);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr LocalFree(IntPtr memory);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetTokenInformation(
        SafeAccessTokenHandle tokenHandle,
        TokenInformationClass tokenInformationClass,
        IntPtr tokenInformation,
        int tokenInformationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(
        SafeProcessHandle process,
        uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(
        SafeProcessHandle process,
        out uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(
        SafeProcessHandle process,
        uint exitCode);
}
