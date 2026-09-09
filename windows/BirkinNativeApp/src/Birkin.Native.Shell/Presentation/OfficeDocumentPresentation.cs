using System.IO;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Presentation;

public sealed record OfficeDocumentRowPresentation(
    string Id,
    string Name,
    string MediaType,
    string Kind);

public static class OfficeDocumentPresentationMapper
{
    public static OfficeDocumentRowPresentation? FromCanonical(NativeEnvelope envelope)
    {
        if (envelope.Kind != NativeMessageKind.Event
            || Text(envelope.Body, "type") != "office.updated"
            || Object(envelope.Body, "payload") is not { } payload
            || Object(payload, "result") is not { } result
            || Object(result, "artifact") is not { } artifact
            || Text(artifact, "artifact_id") is not { } artifactId)
        {
            return null;
        }

        var mediaType = Text(artifact, "media_type") ?? "office";
        var source = Text(artifact, "source_filename") ?? Text(artifact, "uri");
        var name = source is null ? artifactId : Path.GetFileName(source);
        return new OfficeDocumentRowPresentation(
            artifactId,
            string.IsNullOrWhiteSpace(name) ? artifactId : name,
            mediaType,
            "document");
    }

    public static OfficeDocumentRowPresentation FromProjected(PanelItemPresentation item) => new(
        item.Id ?? string.Empty,
        item.Summary ?? item.Id ?? "업무 문서",
        item.Kind ?? "office",
        item.Kind ?? "document");

    private static NativeJsonObject? Object(NativeJsonObject value, string key) =>
        value[key] as NativeJsonObject;

    private static string? Text(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text ? text.Value : null;
}
