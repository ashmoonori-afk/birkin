using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Commands;

public sealed record OfficeDocumentContent(IReadOnlyList<string> Paragraphs);

public sealed record OfficeArtifact(
    string ArtifactId,
    string ContentHash,
    string MediaType,
    string Uri,
    string Sensitivity,
    string AclFingerprint);

public sealed record OfficeLossBudget
{
    public static OfficeLossBudget Zero { get; } = new();

    public long Structure { get; init; }
    public long StyleLayout { get; init; }
    public long FormulaCache { get; init; }
    public long ChartMedia { get; init; }
    public long MacroActiveContent { get; init; }
    public long TrackedChangesComments { get; init; }
    public long FormField { get; init; }
    public long Metadata { get; init; }
    public long SignatureEncryption { get; init; }
    public long Accessibility { get; init; }
}

public sealed record OfficeCreateIntent(string Format, OfficeDocumentContent Content, string OutputName);

public sealed record OfficeSelectIntent(string ArtifactId);

public sealed record OfficeOpenIntent(OfficeArtifact Artifact);

public sealed record OfficeCompareIntent(
    string LeftArtifactId,
    string RightArtifactId);

public sealed record OfficeDraftIntent(string TemplateArtifactId, string DiffId, string OutputName);

public sealed record OfficeConvertIntent(
    OfficeArtifact Artifact,
    string TargetFormat,
    string OutputName,
    OfficeLossBudget LossBudget);

public sealed record OfficeRollbackRequestIntent(string ReceiptRef);

public static class OfficeCommands
{
    public const string CreateCommandType = "office.create";
    public const string SelectCommandType = "office.select";
    public const string OpenCommandType = "office.open";
    public const string CompareCommandType = "office.compare";
    public const string DraftCommandType = "office.draft";
    public const string ConvertCommandType = "office.convert";
    public const string RollbackRequestCommandType = "office.rollback_request";

    public static NativeCommandRequest Create(OfficeCreateIntent intent, CommandRequestContext context) =>
        Request(new NativeCommandIntent(CreateCommandType, new NativeJsonObject([
            new("format", new NativeJsonString(intent.Format)),
            new("content", new NativeJsonObject([
                new("paragraphs", new NativeJsonArray(intent.Content.Paragraphs.Select(
                    paragraph => (NativeJsonValue)new NativeJsonString(paragraph)))),
            ])),
            new("output_name", new NativeJsonString(intent.OutputName)),
        ])), context);

    public static NativeCommandRequest Select(OfficeSelectIntent intent, CommandRequestContext context) =>
        Request(new NativeCommandIntent(SelectCommandType, new NativeJsonObject([
            new("artifact_id", new NativeJsonString(intent.ArtifactId)),
        ])), context);

    public static NativeCommandRequest Open(OfficeOpenIntent intent, CommandRequestContext context) =>
        Request(new NativeCommandIntent(OpenCommandType, new NativeJsonObject([
            new("artifact", Artifact(intent.Artifact)),
        ])), context);

    public static NativeCommandRequest Compare(OfficeCompareIntent intent, CommandRequestContext context) =>
        Request(new NativeCommandIntent(CompareCommandType, new NativeJsonObject([
            new("left_artifact_id", new NativeJsonString(intent.LeftArtifactId)),
            new("right_artifact_id", new NativeJsonString(intent.RightArtifactId)),
        ])), context);

    public static NativeCommandRequest Draft(OfficeDraftIntent intent, CommandRequestContext context) =>
        Request(new NativeCommandIntent(DraftCommandType, new NativeJsonObject([
            new("template_artifact_id", new NativeJsonString(intent.TemplateArtifactId)),
            new("diff_id", new NativeJsonString(intent.DiffId)),
            new("output_name", new NativeJsonString(intent.OutputName)),
        ])), context);

    public static NativeCommandRequest Convert(OfficeConvertIntent intent, CommandRequestContext context) =>
        Request(new NativeCommandIntent(ConvertCommandType, new NativeJsonObject([
            new("artifact", Artifact(intent.Artifact)),
            new("target_format", new NativeJsonString(intent.TargetFormat)),
            new("output_name", new NativeJsonString(intent.OutputName)),
            new("loss_budget", Budget(intent.LossBudget)),
        ])), context);

    public static NativeCommandRequest RollbackRequest(
        OfficeRollbackRequestIntent intent,
        CommandRequestContext context) =>
        Request(new NativeCommandIntent(
            RollbackRequestCommandType,
            new NativeJsonObject([
                new("receipt_ref", new NativeJsonString(intent.ReceiptRef)),
            ])), context);

    private static NativeCommandRequest Request(
        NativeCommandIntent intent,
        CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            intent,
            context.ViewId);

    private static NativeJsonObject Artifact(OfficeArtifact artifact) => new([
        new("artifact_id", new NativeJsonString(artifact.ArtifactId)),
        new("content_hash", new NativeJsonString(artifact.ContentHash)),
        new("media_type", new NativeJsonString(artifact.MediaType)),
        new("uri", new NativeJsonString(artifact.Uri)),
        new("sensitivity", new NativeJsonString(artifact.Sensitivity)),
        new("acl_fingerprint", new NativeJsonString(artifact.AclFingerprint)),
    ]);

    private static NativeJsonObject Budget(OfficeLossBudget budget) => new([
        new("structure", new NativeJsonInteger(budget.Structure)),
        new("style_layout", new NativeJsonInteger(budget.StyleLayout)),
        new("formula_cache", new NativeJsonInteger(budget.FormulaCache)),
        new("chart_media", new NativeJsonInteger(budget.ChartMedia)),
        new("macro_active_content", new NativeJsonInteger(budget.MacroActiveContent)),
        new("tracked_changes_comments", new NativeJsonInteger(budget.TrackedChangesComments)),
        new("form_field", new NativeJsonInteger(budget.FormField)),
        new("metadata", new NativeJsonInteger(budget.Metadata)),
        new("signature_encryption", new NativeJsonInteger(budget.SignatureEncryption)),
        new("accessibility", new NativeJsonInteger(budget.Accessibility)),
    ]);
}
