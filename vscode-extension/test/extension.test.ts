import { describe, expect, it, vi } from "vitest";

interface Folder {
  readonly name: string;
  readonly uri: { readonly scheme: string; readonly fsPath: string };
}

interface Editor {
  readonly document: { readonly uri: Folder["uri"] };
}

interface FolderPick {
  readonly label: string;
  readonly description: string;
  readonly folder: Folder;
}

const CHECKPOINT = {
  hash: "abc123abc123", short: "abc123a", date: "2026-01-01", reason: "before rollout",
};

const configurationValues: Record<string, unknown> = {
  gatewayUrl: "http://127.0.0.1:8788/message",
  gatewayToken: "",
  dashboardUrl: "http://127.0.0.1:8787",
  dashboardToken: "dashboard-capability",
  statusRefreshSeconds: 2,
};

const rootRegistry: Folder[] = [];

function resolveFolder(document: { readonly uri: Folder["uri"] }): Folder | undefined {
  return rootRegistry.find((folder) => folder.uri.fsPath === document?.uri?.fsPath);
}

const state = {
  calls: [] as Array<{ readonly url: string; readonly body: string }>,
  folders: [] as Folder[],
  activeEditor: undefined as Editor | undefined,
  commands: new Map<string, () => Promise<void>>(),
  pickerReturn: "first" as "first" | "dismiss",
  errors: [] as string[],
  checkpointLabels: [] as string[],
  folderPicks: [] as FolderPick[],
  contentProvider: undefined as unknown,
};

vi.mock("vscode", () => ({
  StatusBarAlignment: { Left: 1 },
  Uri: {
    file: (fsPath: string) => ({ scheme: "file", fsPath, path: fsPath, toString: () => fsPath }),
    parse: (value: string) => ({ scheme: "birkin-proposed", fsPath: value, path: value, toString: () => value }),
  },
  EventEmitter: class {
    public readonly event = (): { dispose: () => void } => ({ dispose: () => undefined });
    public fire(): void {}
    public dispose(): void {}
  },
  workspace: {
    isTrusted: true,
    name: "demo",
    get textDocuments(): readonly unknown[] { return []; },
    get workspaceFolders(): readonly Folder[] | undefined {
      return state.folders.length === 0 ? undefined : [...state.folders];
    },
    get activeTextEditor(): Editor | undefined { return state.activeEditor; },
    getConfiguration: () => ({
      get: (key: string, fallback?: unknown) => configurationValues[key] ?? fallback,
    }),
    getWorkspaceFolder: (uri: Folder["uri"]): Folder | undefined =>
      rootRegistry.find((folder) => folder.uri.fsPath === uri.fsPath),
    asRelativePath: (target: Folder["uri"] | string): string =>
      typeof target === "string" ? target : target.fsPath,
    openTextDocument: async () => ({ uri: { scheme: "file", fsPath: "/virtual/doc.md" } }),
    registerTextDocumentContentProvider: (_scheme: string, provider: unknown) => {
      state.contentProvider = provider;
      return { dispose: () => undefined };
    },
  },
  window: {
    get activeTextEditor(): Editor | undefined { return state.activeEditor; },
    createStatusBarItem: () => ({
      command: "", name: "", text: "", tooltip: "", show: () => undefined, dispose: () => undefined,
    }),
    setStatusBarMessage: () => ({ dispose: () => undefined }),
    showInputBox: async () => undefined,
    showInformationMessage: async () => undefined,
    showErrorMessage: async (message: string) => { state.errors.push(message); },
    showWarningMessage: async () => "Restore",
    showQuickPick: async (items: readonly unknown[]) => {
      const options = items as readonly {
        readonly label?: unknown;
        readonly description?: unknown;
        readonly folder?: Folder;
      }[];
      if (options.some((option) => option.folder !== undefined)) {
        state.folderPicks = options.map((option) => ({
          label: String(option.label),
          description: String(option.description ?? ""),
          folder: option.folder as Folder,
        }));
        if (state.pickerReturn === "dismiss") return undefined;
        return options[1] ?? options[0];
      }
      state.checkpointLabels = options.map((option) => String(option.label));
      return options[0];
    },
    showTextDocument: async () => undefined,
  },
  commands: {
    registerCommand: (id: string, callback: () => Promise<void>) => {
      state.commands.set(id, callback);
      return { dispose: () => undefined };
    },
    executeCommand: async () => undefined,
  },
}));

import { BirkinClient } from "../src/client.js";
import { activate } from "../src/extension.js";

function folder(name: string, fsPath: string): Folder {
  return { name, uri: { scheme: "file", fsPath } };
}

function focusEditorFor(target: Folder | undefined): void {
  state.activeEditor = target === undefined ? undefined : makeEditor(target);
}

function makeEditor(target: Folder): Editor {
  return {
    get document(): { readonly uri: Folder["uri"] } {
      return { uri: target.uri };
    },
  };
}

function resetState(targets: readonly Folder[]): void {
  state.errors = [];
  state.calls = [];
  state.errors = [];
  state.checkpointLabels = [];
  state.folderPicks = [];
  state.pickerReturn = "first";
  state.folders = [...targets];
  rootRegistry.length = 0;
  rootRegistry.push(...targets);
  state.activeEditor = undefined;
  state.commands.clear();
  state.contentProvider = undefined;
}

function activateWithStubbedClient(): void {
  state.commands.clear();
  const client = new BirkinClient(async () => ({ status: 200, body: "[]" }));
  client.checkpoints = async (runtime, workspace) => {
    state.calls.push({
      url: `${runtime.url}/api/checkpoints?workspace=${encodeURIComponent(workspace)}`,
      body: "",
    });
    return [{ hash: CHECKPOINT.hash, short: CHECKPOINT.short, date: CHECKPOINT.date, reason: CHECKPOINT.reason }];
  };
  client.rollback = async (runtime, hash, workspace) => {
    state.calls.push({
      url: `${runtime.url}/api/checkpoints/${hash}/restore`,
      body: JSON.stringify({ workspace, mode: "files" }),
    });
  };
  activate({ subscriptions: [] } as unknown as Parameters<typeof activate>[0], client);
}

function command(): () => Promise<void> {
  const registered = state.commands.get("birkin.rollback");
  if (registered === undefined) throw new Error("birkin.rollback was not registered");
  return registered;
}

function rollback(): Promise<void> {
  const running = command()();
  void running.catch(() => undefined);
  return running;
}

function findCall(fragment: string) {
  return state.calls.find((call) => call.url.includes(fragment));
}

describe("birkin.rollback workspace resolution", () => {
  it("rollback uses the active editor workspace for listing and restore", async () => {
    const rootA = folder("A", "/ws/A");
    const rootB = folder("B", "/ws/B");
    resetState([rootA, rootB]);
    focusEditorFor(rootB);
    activateWithStubbedClient();

    // The active editor moves to A while the command is in flight; the captured
    // folder must stay B for both the listing and the restore.
    const invocation = rollback();
    await new Promise((resolve) => setTimeout(resolve, 1));
    focusEditorFor(rootA);
    await invocation;

    expect(findCall("/api/checkpoints?")?.url).toBe(
      "http://127.0.0.1:8787/api/checkpoints?workspace=%2Fws%2FB",
    );
    expect(findCall("/restore")?.body).toBe(
      JSON.stringify({ workspace: "/ws/B", mode: "files" }),
    );
    expect(state.checkpointLabels).toEqual([CHECKPOINT.reason]);
    expect(state.folderPicks).toEqual([]);
    expect(state.contentProvider).toBeDefined();
  });

  it("rollback prompts for a folder without an active workspace", async () => {
    const rootA = folder("A", "/ws/A");
    const rootB = folder("B", "/ws/B");
    resetState([rootA, rootB]);
    activateWithStubbedClient();

    await rollback();

    expect(state.folderPicks.map((pick) => ({ label: pick.label, description: pick.description })))
      .toEqual([
        { label: "A", description: "/ws/A" },
        { label: "B", description: "/ws/B" },
      ]);
    expect(state.folderPicks.map((pick) => pick.folder.uri.fsPath)).toEqual(["/ws/A", "/ws/B"]);
    expect(findCall("/api/checkpoints?")?.url).toBe(
      "http://127.0.0.1:8787/api/checkpoints?workspace=%2Fws%2FB",
    );
    expect(findCall("/restore")?.body).toBe(
      JSON.stringify({ workspace: "/ws/B", mode: "files" }),
    );
  });

  it("rollback cancels before requests when folder selection is dismissed", async () => {
    const rootA = folder("A", "/ws/A");
    const rootB = folder("B", "/ws/B");
    resetState([rootA, rootB]);
    activateWithStubbedClient();
    state.pickerReturn = "dismiss";

    await rollback();

    expect(state.calls).toEqual([]);
    expect(state.folderPicks.map((pick) => pick.label)).toEqual(["A", "B"]);
  });

  it("rollback uses the sole workspace folder without a folder picker", async () => {
    resetState([folder("A", "/ws/A")]);
    activateWithStubbedClient();

    await rollback();

    expect(state.folderPicks).toEqual([]);
    expect(state.checkpointLabels).toEqual([CHECKPOINT.reason]);
    expect(findCall("/api/checkpoints?")?.url).toBe(
      "http://127.0.0.1:8787/api/checkpoints?workspace=%2Fws%2FA",
    );
    expect(findCall("/restore")?.body).toBe(
      JSON.stringify({ workspace: "/ws/A", mode: "files" }),
    );
  });

  it("rollback reports the existing error when no folder is open", async () => {
    resetState([]);
    activateWithStubbedClient();

    await rollback();

    expect(state.calls).toEqual([]);
    expect(state.errors).toEqual(["Birkin: Open a workspace before rollback."]);
  });
});
