using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Commands;

public sealed record FileImportIntent
{
    public FileImportIntent(string sourcePath)
    {
        if (string.IsNullOrEmpty(sourcePath))
        {
            throw new ArgumentException("Import source path is required.", nameof(sourcePath));
        }

        SourcePath = sourcePath;
    }

    public string SourcePath { get; }
}

public static class ImportCommands
{
    public const string CommandType = "file.import";

    public static NativeCommandRequest Import(FileImportIntent intent, CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(
                CommandType,
                new NativeJsonObject([
                    new("source_path", new NativeJsonString(intent.SourcePath)),
                ])),
            context.ViewId);
}
