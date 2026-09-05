using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Shell.Presentation;

public sealed record OfficeOperationSupportPresentation(
    string Label,
    string Status,
    string AgentPath,
    string InstallCondition);

public sealed record OfficeFormatSupportPresentation(
    string Format,
    IReadOnlyList<OfficeOperationSupportPresentation> Operations)
{
    public string FormatLabel => Format.ToUpperInvariant();
}

public static class OfficeSupportPresentationMapper
{
    private static readonly (string Key, string Label)[] Operations =
    [
        ("extract", "읽기"),
        ("create", "생성"),
        ("patch", "수정"),
        ("render", "렌더링"),
        ("recalculate", "재계산"),
    ];

    public static IReadOnlyList<OfficeFormatSupportPresentation> FromSurface(
        NativeSurfaceProjection? surface)
    {
        if (surface?.Payload["inventory"] is not NativeJsonArray inventory)
        {
            return [];
        }
        return inventory.Values.OfType<NativeJsonObject>()
            .Select(Format)
            .Where(row => row is not null)
            .Cast<OfficeFormatSupportPresentation>()
            .ToArray();
    }

    private static OfficeFormatSupportPresentation? Format(NativeJsonObject item)
    {
        if (Text(item, "format") is not { } format
            || item["capabilities"] is not NativeJsonObject capabilities)
        {
            return null;
        }
        return new OfficeFormatSupportPresentation(
            format,
            Operations.Select(operation => Operation(capabilities, operation)).ToArray());
    }

    private static OfficeOperationSupportPresentation Operation(
        NativeJsonObject capabilities,
        (string Key, string Label) operation)
    {
        if (capabilities[operation.Key] is not NativeJsonObject capability)
        {
            return new(operation.Label, "미지원", "에이전트 경로 미연결", "설치로 활성화되지 않음");
        }
        var state = Text(capability, "state");
        var availability = Text(capability, "availability");
        var publicEntrypoint = Text(capability, "public_entrypoint");
        var status = state == "unsupported"
            ? "미지원"
            : publicEntrypoint is null
                ? "하위 기능만 있음"
                : availability switch
                {
                    "conditional" => "조건부",
                    "structured-preview-only" => "구조 미리보기",
                    "bounded" => "제한 지원",
                    _ => "지원",
                };
        var install = Text(capability, "install_probe") switch
        {
            null => "기본 제공",
            "source-provenance-required" => "승인된 소스 구성 필요",
            _ => "선택 패키지 필요",
        };
        return new(
            operation.Label,
            status,
            publicEntrypoint is null ? "에이전트 경로 미연결" : "에이전트에서 사용 가능",
            install);
    }

    private static string? Text(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text ? text.Value : null;
}
