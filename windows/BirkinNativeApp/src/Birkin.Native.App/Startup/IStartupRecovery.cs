using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Startup;

public interface IStartupRecovery
{
    Task<StartupFailurePresentation?> RetryAsync();

    Task<StartupFailurePresentation?> ConfigureExecutableAndRetryAsync(
        string executablePath);
}
