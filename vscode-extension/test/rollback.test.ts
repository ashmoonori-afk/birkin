import { beforeEach, describe, expect, it, vi } from "vitest";

const restored = {
  hash: "abc1234abc1234abc1234abc1234abc1234abc1",
  reason: "before edits",
  short: "abc1234",
  date: "2026-01-01T00:00:00Z",
};

const info = vi.fn();
const warning = vi.fn();
const quickPick = vi.fn();
const executeCommand = vi.fn();

vi.mock("vscode", () => ({
  StatusBarAlignment: { Left: 1 },
  EventEmitter: class {
    public readonly event = vi.fn();
    public readonly fire = vi.fn();
    public readonly dispose = vi.fn();
  },
  Uri: { parse: (value: string) => ({ toString: () => value }) },
  window: {
    activeTextEditor: undefined,
    createStatusBarItem: () => ({
      command: "",
      name: "",
      text: "",
      tooltip: "",
      show: vi.fn(),
      dispose: vi.fn(),
    }),
    showQuickPick: (...args: unknown[]) => quickPick(...args),
    showWarningMessage: (...args: unknown[]) => warning(...args),
    showInformationMessage: (...args: unknown[]) => info(...args),
    showErrorMessage: vi.fn(),
    showInputBox: vi.fn(),
    showTextDocument: vi.fn(),
    setStatusBarMessage: vi.fn(),
  },
  workspace: {
    name: "demo",
    isTrusted: true,
    workspaceFolders: [{ uri: { fsPath: "C:\\work\\demo" } }],
    textDocuments: [],
    getConfiguration: () => ({
      get: (key: string, fallback: unknown) =>
        key === "dashboardUrl" ? "http://127.0.0.1:8787" : key === "dashboardToken" ? "capability" : fallback,
    }),
    registerTextDocumentContentProvider: vi.fn(),
    openTextDocument: vi.fn(),
  },
  commands: {
    registerCommand: vi.fn(),
    executeCommand: (...args: unknown[]) => executeCommand(...args),
  },
}));

const commands = new Map<string, () => Promise<void>>();

beforeEach(async () => {
  const vscode = await import("vscode");
  vi.mocked(vscode.commands.registerCommand).mockImplementation(
    ((id: string, handler: () => Promise<void>) => {
      commands.set(id, handler);
      return { dispose: vi.fn() };
    }) as unknown as typeof vscode.commands.registerCommand,
  );
  commands.clear();
  info.mockReset();
  warning.mockReset();
  quickPick.mockReset();
  executeCommand.mockReset();
});

describe("birkin.rollback approval handoff", () => {
  it("offers approval review after a restore proposal is accepted", async () => {
    const originalFetch = globalThis.fetch;
    const fetched: string[] = [];
    const { activate } = await import("../src/extension.js");
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      fetched.push(url);
      if (url.endsWith("/api/checkpoints?workspace=C%3A%5Cwork%5Cdemo")) {
        return new Response(JSON.stringify([restored]), { status: 200 });
      }
      if (url.endsWith(`/api/checkpoints/${restored.hash}/restore`)) {
        return new Response(
          JSON.stringify({
            ok: true,
            approval_required: true,
            approval_id: "a1b2c3d4e5f6",
            mode: "files",
          }),
          { status: 202 },
        );
      }
      throw new Error(`unexpected request ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    activate({ subscriptions: { push: vi.fn() } } as unknown as Parameters<typeof activate>[0]);

    quickPick.mockResolvedValueOnce({ checkpoint: restored });
    warning.mockResolvedValueOnce("Restore");
    info.mockResolvedValueOnce(undefined);

    const handler = commands.get("birkin.rollback");
    expect(handler).toBeDefined();
    await handler!();

    expect(fetched).toContain(`http://127.0.0.1:8787/api/checkpoints/${restored.hash}/restore`);
    expect(info).toHaveBeenCalledTimes(1);
    const [message, ...actions] = info.mock.calls[0] as unknown as [string, ...string[]];
    expect(message).toContain("a1b2c3d4e5f6");
    expect(message).toMatch(/proposal/i);
    expect(message).not.toMatch(/(has|is|was|completed|successfully)\s+restored/i);
    expect(message).not.toMatch(/restore (is )?(complete|done|finished)/i);
    expect(actions).toContain("Review Approvals");
    expect(executeCommand).not.toHaveBeenCalled();

    info.mockResolvedValueOnce("Review Approvals");
    warning.mockResolvedValueOnce("Restore");
    quickPick.mockResolvedValueOnce({ checkpoint: restored });
    await handler!();
    expect(executeCommand).toHaveBeenCalledWith("birkin.reviewApprovals");

    globalThis.fetch = originalFetch;
  });
});
