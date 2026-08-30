using Birkin.Native.Shell.Lifecycle;

namespace Birkin.Native.Shell.Presentation;

public sealed record StartupFailurePresentation(
    BridgeStartupFailureReason Reason,
    string ErrorCode,
    string Title,
    string Explanation,
    string RecoveryAction,
    bool CanRetry)
{
    public static StartupFailurePresentation Create(
        BridgeStartupFailureReason reason,
        bool canRetry = true) =>
        reason switch
        {
            BridgeStartupFailureReason.CliUnavailable => new(
                reason,
                "E_CLI_LAUNCH",
                "birkin 실행 파일을 찾을 수 없습니다",
                "Windows 앱이 birkin 명령을 시작하지 못했습니다.",
                "Birkin CLI를 설치하거나 실행 파일의 전체 경로를 설정한 다음 다시 시도하세요.",
                canRetry),
            BridgeStartupFailureReason.CliFailed => new(
                reason,
                "E_CLI_STARTUP",
                "Birkin CLI 시작을 완료하지 못했습니다",
                "birkin 명령이 사용할 수 있는 로컬 bridge endpoint를 제공하지 못했습니다.",
                "터미널에서 birkin native-bridge serve --transport loopback을 실행해 문제를 확인한 다음 다시 시도하세요.",
                canRetry),
            BridgeStartupFailureReason.CliCrashLoop => new(
                reason,
                "E_CLI_CRASH_LOOP",
                "Birkin CLI가 반복해서 종료되었습니다",
                "birkin 명령이 1분 안에 5번 종료되었습니다.",
                "터미널에서 CLI 상태를 확인하고 안정화한 다음 다시 시도하세요.",
                canRetry),
            BridgeStartupFailureReason.CliTimedOut => new(
                reason,
                "E_CLI_TIMEOUT",
                "Birkin CLI 시작 시간이 초과되었습니다",
                "birkin 명령이 15초 안에 로컬 bridge endpoint를 알리지 않았습니다.",
                "설정한 실행 파일 경로를 확인한 다음 다시 연결하세요.",
                canRetry),
            _ => throw new ArgumentOutOfRangeException(nameof(reason)),
        };
}
