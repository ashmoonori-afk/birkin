using System.Security;

namespace Birkin.Native.App.Startup;

public sealed class ExecutablePathSettings
{
    public const string EnvironmentVariableName = "BIRKIN_EXECUTABLE";

    public bool TrySet(string executablePath)
    {
        if (string.IsNullOrWhiteSpace(executablePath)
            || !Path.IsPathFullyQualified(executablePath)
            || !File.Exists(executablePath))
        {
            return false;
        }

        try
        {
            Environment.SetEnvironmentVariable(
                EnvironmentVariableName,
                executablePath,
                EnvironmentVariableTarget.User);
            Environment.SetEnvironmentVariable(
                EnvironmentVariableName,
                executablePath,
                EnvironmentVariableTarget.Process);
            return true;
        }
        catch (Exception error)
            when (error is
                ArgumentException
                or SecurityException
                or UnauthorizedAccessException)
        {
            return false;
        }
    }
}
