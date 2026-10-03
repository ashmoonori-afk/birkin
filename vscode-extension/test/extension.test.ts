import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => {
  return {
    folders: [] as Array<Record<string, unknown>>,
    activeEditor: undefined as { document: { uri: unknown } } | undefined,
    openDocument: undefined as { uri: unknown } | undefined,
    folderQuickPick: vi.fn(),
    checkpointQuickPick: vi.fn(),
    warningMessage: vi.fn(),
    informationMessage: vi.fn(),
    errorMessage: vi.fn(),
    inputBox: vi.fn(),
    registered: new Map<string, () => Promise<void>>(),
    statusItem: {
      command: "", name: "", text: "", tooltip: "", show: vi.fn(), dispose: vi.fn(),
    },
    disposables: [] as Array<{ dispose: () => void }>,
    apply: (): void => {
      state.folderQuickPick.mockReset();
      state.checkpointQuickPick.mockReset();
      state.warningMessage.mockReset();
      state.informationMessage.mockReset();
      state.errorMessage.mockReset();
      state.inputBox.mockReset();
      state.registered.clear();
      state.statusItem.show.mockReset();
      state.statusItem.dispose.mockReset();
      state.disposables.length = 0;
    },
    resolvedFolders: new Map<string, Record<string, unknown>>(),
  };
});

vi.mock("vscode", () => ({
  StatusBarAlignment: { Left: 1 },
  EventEmitter: class {
    private readonly listeners = new Set<(value: unknown) => void>();
    public readonly event = (listener: (value: unknown) => void) => {
      this.listeners.add(listener);
      return { dispose: () => { this.listeners.delete(listener); } };
    };
    public fire(value: unknown): void { for (const listener of this.listeners) listener(value); }
    public dispose(): void { this.listeners.clear(); }
  },
  window: {
    createStatusBarItem: () => state.statusItem,
    get activeTextEditor() { return state.activeEditor; },
    // The fake treats a request for the folder picker's placeholder as folder selection.
    showQuickPick: (items: unknown[], options?: { placeHolder?: string }) =>
      (options?.placeHolder === FOLDER_PLACEHOLDER
        ? state.folderQuickPick(items, options)
        : state.checkpointQuickPick(items, options)),
    showWarningMessage: (...args: unknown[]) => state.warningMessage(...args),
    showInformationMessage: (...args: unknown[]) => state.informationMessage(...args),
    showErrorMessage: (...args: unknown[]) => state.errorMessage(...args),
    showInputBox: (...args: unknown[]) => state.inputBox(...args),
    showTextDocument: vi.fn(async () => ({})),
    setStatusBarMessage: vi.fn(() => ({ dispose: vi.fn() })),
  },
  workspace: {
    get workspaceFolders() { return state.folders.length === 0 ? undefined : state.folders; },
    getWorkspaceFolder(uri: { fsPath?: string; toString: () => string }) {
      const byUri = state.resolvedFolders.get(uri.toString());
      if (byUri !== undefined) return byUri;
      // VS Code ownership is path containment; a document under a root resolves to it
      // even when the two URIs are spelled with different slash counts.
      const target = uri.fsPath ?? "";
      const owned = state.folders
        .map((entry) => entry as unknown as Folder)
        .filter((entry) => target === entry.uri.fsPath || target.startsWith(`${entry.uri.fsPath}/`))
        .sort((left, right) => right.uri.fsPath.length - left.uri.fsPath.length)[0];
      return owned;
    },
    get textDocuments() { return state.openDocument === undefined ? [] : [state.openDocument]; },
    asRelativePath: (uri: { fsPath?: string }) => uri.fsPath ?? "",
    isTrusted: true,
    getConfiguration: () => ({
      get: <T>(key: string, fallback: T): T => {
        if (key === "dashboardUrl") return "http://127.0.0.1:4399" as unknown as T;
        if (key === "dashboardToken") return "test-capability" as unknown as T;
        return fallback;
      },
    }),
    openTextDocument: vi.fn(async () => ({})),
    registerTextDocumentContentProvider: () => ({ dispose: vi.fn() }),
  },
  commands: {
    registerCommand: (id: string, callback: () => Promise<void>) => {
      state.registered.set(id, callback);
      const disposable = { dispose: vi.fn() };
      state.disposables.push(disposable);
      return disposable;
    },
    executeCommand: vi.fn(async () => undefined),
  },
}));

import { activate } from "../src/extension.js";
import type { Checkpoint } from "../src/types.js";

const DASHBOARD = "http://127.0.0.1:4399";
const FOLDER_PLACEHOLDER = "체크포인트를 복원할 워크스페이스 폴더를 선택하세요";

function checkpoint(hash: string, short: string, reason: string): Checkpoint {
  return { hash, short, date: "2026-10-03T00:00:00Z", reason };
}

const ROOTS = {
  a: folder("root-a", "/tmp/birkin roots/alpha", 0),
  b: folder("root-b", "/tmp/birkin roots/베타", 1),
};

const OUTSIDE = "/tmp/birkin roots/outside";
const INNER = "/tmp/birkin roots/alpha/inner";
const DUPLICATE_FIRST = "/tmp/birkin roots/dup one";
const DUPLICATE_SECOND = "/tmp/birkin roots/dup two";

const CHECKPOINTS = {
  a: checkpoint("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "aaaaaaa", "root A checkpoint"),
  b: checkpoint("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "bbbbbbb", "root B checkpoint"),
};

function folder(name: string, path: string, index: number) {
  return {
    index, name,
    uri: { scheme: "file", fsPath: path, path, toString: () => `file:///${path.replace(/\\/g, "/")}` },
  };
}

function document(root: string, relative: string) {
  const fsPath = `${root}/${relative}`;
  return { uri: { scheme: "file", fsPath, path: fsPath, toString: () => `file:///${fsPath.replace(/\\/g, "/")}` } };
}

function editor(uri: unknown) {
  return { document: { uri } } as never;
}

type Folder = ReturnType<typeof folder>;

interface Recorded { method: string; url: string; headers: Record<string, string>; body?: string }

function jsonResponse(status: number, value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status, headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => { resolve = settle; });
  return { promise, resolve };
}

function timeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timeout: ${label}`)), ms);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });
}

function workspaceOf(url: string): string | null {
  try { return new URL(url).searchParams.get("workspace"); } catch { return null; }
}

function restoreWorkspace(record: Recorded): string | undefined {
  if (record.body === undefined) return undefined;
  try { return (JSON.parse(record.body) as { workspace?: string }).workspace; }
  catch { return undefined; }
}

describe("birkin.rollback workspace selection", () => {
  let requests: Recorded[] = [];
  let originalFetch: typeof globalThis.fetch;

  const environment = (roots: Folder[], ownership: Folder[] = roots) => {
    state.folders = roots as unknown as Array<Record<string, unknown>>;
    const byPath = ownership.map((entry) =>
      [`fsPath:${entry.uri.fsPath}`, entry] as [string, Record<string, unknown>]);
    state.resolvedFolders = new Map([
      ...ownership.map((entry) =>
        [entry.uri.toString(), entry] as [string, Record<string, unknown>]),
      ...byPath,
    ]);
  };

  beforeEach(() => {
    requests = [];
    state.folders = [];
    state.activeEditor = undefined;
    state.openDocument = undefined;
    state.resolvedFolders.clear();
    state.apply();
    state.folderQuickPick.mockResolvedValue(undefined);
    state.checkpointQuickPick.mockResolvedValue(undefined);
    state.warningMessage.mockResolvedValue(undefined);
    state.informationMessage.mockImplementation(async () => undefined);
    state.errorMessage.mockImplementation(async () => undefined);
    state.inputBox.mockResolvedValue(undefined);
    originalFetch = globalThis.fetch;
    globalThis.fetch = (async (input: string | URL | { url: string }, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const method = init?.method ?? "GET";
      const headers = { ...((init?.headers ?? {}) as Record<string, string>) };
      const body = typeof init?.body === "string" ? init.body : undefined;
      const record: Recorded = body === undefined
        ? { method, url, headers }
        : { method, url, headers, body };
      requests.push(record);
      if (method === "GET" && url.startsWith(`${DASHBOARD}/api/status`)) {
        return jsonResponse(200, { daemon: true, stale: false, pending_count: 0, model: null, provider: null });
      }
      if (method === "GET" && url.startsWith(`${DASHBOARD}/api/checkpoints?`)) {
        const workspace = workspaceOf(url);
        return jsonResponse(200, workspace === ROOTS.b.uri.fsPath
          ? [CHECKPOINTS.b]
          : [CHECKPOINTS.a]);
      }
      if (method === "POST" && url.startsWith(`${DASHBOARD}/api/checkpoints/`)) {
        return jsonResponse(202, { status: "pending", proposal: "proposal-1" });
      }
      return jsonResponse(404, { error: `unexpected route ${method} ${url}` });
    }) as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    for (const disposable of state.disposables) disposable.dispose();
    state.activeEditor = undefined;
    state.openDocument = undefined;
    state.folders = [];
    state.resolvedFolders.clear();
  });

  const rollbackRequests = () => requests.filter((request) => request.url.includes("/api/checkpoints"));
  const getRequests = () => requests.filter((request) => request.method === "GET" && request.url.includes("/api/checkpoints"));
  const postRequests = () => requests.filter((request) => request.method === "POST" && request.url.includes("/api/checkpoints"));

  const run = async (): Promise<void> => {
    const subscriptions: Array<{ dispose: () => void }> = [];
    activate({ subscriptions } as never);
    // Status start refreshes once through this test's fetch mock; no background timers to drain.
    await Promise.resolve();
    state.disposables.push(...subscriptions);
    const command = state.registered.get("birkin.rollback");
    if (command === undefined) throw new Error("birkin.rollback was not registered");
    await command();
  };

  it("keeps the captured workspace: active document in the second root", async () => {
    environment([ROOTS.a, ROOTS.b]);
    const documentB = document(ROOTS.b.uri.fsPath, "src/b.ts");
    state.activeEditor = editor(documentB.uri);
    state.openDocument = documentB;
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });

    const confirmationEntered = deferred<void>();
    const releaseConfirmation = deferred<string | undefined>();
    state.warningMessage.mockImplementation(() => {
      confirmationEntered.resolve();
      return releaseConfirmation.promise;
    });

    const invocation = run();
    await timeout(Promise.race([
      confirmationEntered.promise,
      invocation.then(() => { throw new Error("rollback finished before confirmation"); }),
    ]), 3000, "rollback admission to confirmation");

    expect(getRequests()).toHaveLength(1);
    expect(workspaceOf(getRequests()[0]!.url)).toBe(ROOTS.b.uri.fsPath);
    expect(postRequests()).toHaveLength(0);

    const documentA = document(ROOTS.a.uri.fsPath, "src/a.ts");
    state.activeEditor = editor(documentA.uri);
    state.openDocument = documentA;

    releaseConfirmation.resolve("Restore");
    await timeout(invocation, 3000, "rollback completion");

    expect(postRequests()).toHaveLength(1);
    expect(postRequests()[0]!.url).toBe(`${DASHBOARD}/api/checkpoints/${CHECKPOINTS.b.hash}/restore`);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(ROOTS.b.uri.fsPath);
    expect(state.folderQuickPick).not.toHaveBeenCalled();
    expect(state.errorMessage).not.toHaveBeenCalled();
  });

  it("keeps the captured workspace: explicit picker without an editor", async () => {
    environment([ROOTS.a, ROOTS.b]);
    state.activeEditor = undefined;
    state.openDocument = undefined;
    state.folderQuickPick.mockImplementation(async (items: Array<{ folder: Folder }>) => {
      const chosen = items.find((entry) => entry.folder.uri.fsPath === ROOTS.b.uri.fsPath);
      return chosen;
    });
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });

    const confirmationEntered = deferred<void>();
    const releaseConfirmation = deferred<string | undefined>();
    state.warningMessage.mockImplementation(() => {
      confirmationEntered.resolve();
      return releaseConfirmation.promise;
    });

    const invocation = run();
    await timeout(Promise.race([
      confirmationEntered.promise,
      invocation.then(() => { throw new Error("rollback finished before confirmation"); }),
    ]), 3000, "rollback admission to confirmation");

    expect(getRequests()).toHaveLength(1);
    expect(workspaceOf(getRequests()[0]!.url)).toBe(ROOTS.b.uri.fsPath);
    expect(postRequests()).toHaveLength(0);

    const documentA = document(ROOTS.a.uri.fsPath, "src/a.ts");
    state.activeEditor = editor(documentA.uri);
    state.openDocument = documentA;

    releaseConfirmation.resolve("Restore");
    await timeout(invocation, 3000, "rollback completion");

    expect(postRequests()).toHaveLength(1);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(ROOTS.b.uri.fsPath);
    expect(state.errorMessage).not.toHaveBeenCalled();
  });

  it("uses the active document's root instead of the first root", async () => {
    environment([ROOTS.a, ROOTS.b]);
    const documentB = document(ROOTS.b.uri.fsPath, "src/b.ts");
    state.activeEditor = editor(documentB.uri);
    state.openDocument = documentB;
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });
    state.warningMessage.mockResolvedValue("Restore");

    await run();

    expect(getRequests()).toHaveLength(1);
    expect(workspaceOf(getRequests()[0]!.url)).toBe(ROOTS.b.uri.fsPath);
    expect(postRequests()).toHaveLength(1);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(ROOTS.b.uri.fsPath);
    expect(postRequests()[0]!.url).toContain(CHECKPOINTS.b.hash);
    expect(state.folderQuickPick).not.toHaveBeenCalled();
  });

  it("offers the real folder objects and uses the picked one", async () => {
    environment([ROOTS.a, ROOTS.b]);
    state.folderQuickPick.mockImplementation(async (items: Array<{ folder: Folder; label: string; description: string }>) => {
      expect(items.map((entry) => entry.folder.uri.fsPath)).toEqual([
        ROOTS.a.uri.fsPath, ROOTS.b.uri.fsPath,
      ]);
      return items.find((entry) => entry.folder.uri.fsPath === ROOTS.b.uri.fsPath);
    });
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });
    state.warningMessage.mockResolvedValue("Restore");

    await run();

    expect(state.folderQuickPick).toHaveBeenCalledTimes(1);
    expect(workspaceOf(getRequests()[0]!.url)).toBe(ROOTS.b.uri.fsPath);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(ROOTS.b.uri.fsPath);
  });

  it("asks for a folder when the editor belongs to no root", async () => {
    environment([ROOTS.a, ROOTS.b]);
    const outside = document(OUTSIDE, "loose.ts");
    state.activeEditor = editor(outside.uri);
    state.openDocument = outside;
    state.folderQuickPick.mockImplementation(async (items: Array<{ folder: Folder }>) =>
      items.find((entry) => entry.folder.uri.fsPath === ROOTS.b.uri.fsPath));
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });
    state.warningMessage.mockResolvedValue("Restore");

    await run();

    expect(state.folderQuickPick).toHaveBeenCalledTimes(1);
    expect(workspaceOf(getRequests()[0]!.url)).toBe(ROOTS.b.uri.fsPath);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(ROOTS.b.uri.fsPath);
  });

  it("does nothing when the folder picker is dismissed", async () => {
    environment([ROOTS.a, ROOTS.b]);
    state.folderQuickPick.mockImplementation(async () => undefined);

    await run();

    expect(state.folderQuickPick).toHaveBeenCalledTimes(1);
    expect(rollbackRequests()).toHaveLength(0);
    expect(state.checkpointQuickPick).not.toHaveBeenCalled();
    expect(state.warningMessage).not.toHaveBeenCalled();
    expect(state.errorMessage).not.toHaveBeenCalled();
  });

  it("distinguishes duplicate root names by path", async () => {
    const firstDuplicate = folder("same", DUPLICATE_FIRST, 0);
    const secondDuplicate = folder("same", DUPLICATE_SECOND, 1);
    environment([firstDuplicate, secondDuplicate]);
    state.folderQuickPick.mockImplementation(async (items: Array<{ folder: Folder }>) =>
      items.find((entry) => entry.folder.uri.fsPath === DUPLICATE_SECOND));
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });
    state.warningMessage.mockResolvedValue("Restore");

    await run();

    const items = state.folderQuickPick.mock.calls[0]![0] as Array<{ label: string; description: string }>;
    expect(items[0]!.label).toBe(items[1]!.label);
    expect(items[0]!.description).not.toBe(items[1]!.description);
    expect(workspaceOf(getRequests()[0]!.url)).toBe(DUPLICATE_SECOND);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(DUPLICATE_SECOND);
  });

  it("uses the inner root resolved by the editor ownership lookup", async () => {
    const inner = folder("inner", INNER, 1);
    // The outer root is the first entry; only VS Code's ownership lookup may return the inner one.
    environment([ROOTS.a, inner]);
    const nested = document(INNER, "src/nested.ts");
    state.activeEditor = editor(nested.uri);
    state.openDocument = nested;
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });
    state.warningMessage.mockResolvedValue("Restore");

    await run();

    expect(state.folderQuickPick).not.toHaveBeenCalled();
    expect(workspaceOf(getRequests()[0]!.url)).toBe(INNER);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(INNER);
  });

  it("uses the sole root when the active editor belongs to no root", async () => {
    environment([ROOTS.a]);
    const outside = document(OUTSIDE, "loose.ts");
    state.activeEditor = editor(outside.uri);
    state.openDocument = outside;
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.a });
    state.warningMessage.mockResolvedValue("Restore");

    await run();

    expect(state.folderQuickPick).not.toHaveBeenCalled();
    expect(workspaceOf(getRequests()[0]!.url)).toBe(ROOTS.a.uri.fsPath);
    expect(restoreWorkspace(postRequests()[0]!)).toBe(ROOTS.a.uri.fsPath);
  });

  it("reports an error with no workspace folders", async () => {
    environment([]);

    await run();

    expect(state.errorMessage).toHaveBeenCalledTimes(1);
    expect(rollbackRequests()).toHaveLength(0);
    expect(state.folderQuickPick).not.toHaveBeenCalled();
    expect(state.checkpointQuickPick).not.toHaveBeenCalled();
  });

  it("reports an error for an empty workspace folder array", async () => {
    // An empty array is still an undefined-shaped workspace, exactly like an absent key.
    state.folders = [];

    await run();

    expect(state.errorMessage).toHaveBeenCalledTimes(1);
    expect(rollbackRequests()).toHaveLength(0);
    expect(state.checkpointQuickPick).not.toHaveBeenCalled();
  });

  it("stops after the checkpoint picker is dismissed", async () => {
    environment([ROOTS.a, ROOTS.b]);
    const documentB = document(ROOTS.b.uri.fsPath, "src/b.ts");
    state.activeEditor = editor(documentB.uri);
    state.openDocument = documentB;
    state.checkpointQuickPick.mockImplementation(async () => undefined);

    await run();

    expect(getRequests()).toHaveLength(1);
    expect(workspaceOf(getRequests()[0]!.url)).toBe(ROOTS.b.uri.fsPath);
    expect(postRequests()).toHaveLength(0);
    expect(state.warningMessage).not.toHaveBeenCalled();
  });

  it("stops when the checkpoint list is empty", async () => {
    environment([ROOTS.a, ROOTS.b]);
    const documentB = document(ROOTS.b.uri.fsPath, "src/b.ts");
    state.activeEditor = editor(documentB.uri);
    state.openDocument = documentB;
    state.checkpointQuickPick.mockResolvedValue(undefined);

    await run();

    expect(state.checkpointQuickPick).toHaveBeenCalledTimes(1);
    expect(postRequests()).toHaveLength(0);
    expect(state.warningMessage).not.toHaveBeenCalled();
  });

  it("stops after the restore confirmation is dismissed", async () => {
    environment([ROOTS.a, ROOTS.b]);
    const documentB = document(ROOTS.b.uri.fsPath, "src/b.ts");
    state.activeEditor = editor(documentB.uri);
    state.openDocument = documentB;
    state.checkpointQuickPick.mockResolvedValue({ checkpoint: CHECKPOINTS.b });
    state.warningMessage.mockImplementation(async () => undefined);

    await run();

    expect(getRequests()).toHaveLength(1);
    expect(postRequests()).toHaveLength(0);
    expect(state.informationMessage).not.toHaveBeenCalled();
  });
});
