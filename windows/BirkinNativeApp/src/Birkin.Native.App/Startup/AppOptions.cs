using System.IO;

namespace Birkin.Native.App.Startup;

public sealed record AppOptions(string BridgeAnnouncementJson)
{
    private const string AnnouncementFileOption = "--bridge-announcement-file";

    public bool IsAttached => BridgeAnnouncementJson.Length != 0;

    public static AppOptions Parse(IReadOnlyList<string> arguments)
    {
        if (arguments.Count == 0)
        {
            return new AppOptions(string.Empty);
        }

        if (arguments.Count != 2
            || !string.Equals(arguments[0], AnnouncementFileOption, StringComparison.Ordinal)
            || !Path.IsPathFullyQualified(arguments[1])
            || !File.Exists(arguments[1]))
        {
            throw new ArgumentException(
                $"Expected {AnnouncementFileOption} followed by one absolute existing file.",
                nameof(arguments));
        }

        string[] lines;
        try
        {
            lines = File.ReadAllLines(arguments[1]);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw new ArgumentException("The bridge announcement file could not be read.", nameof(arguments), error);
        }

        var announcements = lines.Where(line => !string.IsNullOrWhiteSpace(line)).ToArray();
        if (announcements.Length != 1)
        {
            throw new ArgumentException(
                "The bridge announcement file must contain exactly one nonblank JSON line.",
                nameof(arguments));
        }
        return new AppOptions(announcements[0]);
    }
}
