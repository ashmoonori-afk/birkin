import * as vscode from "vscode";
import { BirkinClient } from "./client.js";
import { attachEditorContext, toEditorContext, type EditorSnapshot } from "./context.js";
import { proposedChange } from "./contracts.js";
import { DiffStore } from "./diffStore.js";
import { discoverDashboard } from "./discovery.js";
import { errorMessage } from "./errors.js";
import { StatusController } from "./status.js";
import type { DashboardSession, OpenEditor } from "./types.js";

function configuration() {
  const config = vscode.workspace.getConfiguration("birkin");
  return {
    gatewayUrl: config.get<string>("gatewayUrl", "http://127.0.0.1:8788/message"),
    gatewayToken: config.get<string>("gatewayToken", ""),
    dashboardUrl: config.get<string>("dashboardUrl", ""),
    dashboardToken: config.get<string>("dashboardToken", ""),
    refreshSeconds: config.get<number>("statusRefreshSeconds", 5),
  };
}

async function dashboard(): Promise<DashboardSession> {
  const config = configuration();
  return discoverDashboard(config.dashboardUrl, config.dashboardToken);
}

function snapshot(): EditorSnapshot {
  const editor = vscode.window.activeTextEditor;
  if (editor === undefined) throw new Error("Open a file before sending editor context.");
  const workspace = vscode.workspace.getWorkspaceFolder(editor.document.uri)?.uri.fsPath
    ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "";
  const openEditors: OpenEditor[] = vscode.workspace.textDocuments
    .filter((document) => !document.isClosed && document.uri.scheme === "file")
    .map((document) => ({ path: vscode.workspace.asRelativePath(document.uri, false),
      language: document.languageId, dirty: document.isDirty }));
  return {
    file: vscode.workspace.asRelativePath(editor.document.uri, false), workspace,
    selection: editor.document.getText(editor.selection),
    start: { line: editor.selection.start.line, character: editor.selection.start.character },
    end: { line: editor.selection.end.line, character: editor.selection.end.character },
    openEditors,
  };
}

async function showText(title: string, text: string, language = "markdown"): Promise<void> {
  const document = await vscode.workspace.openTextDocument({ language, content: text });
  await vscode.window.showTextDocument(document, { preview: true });
  void vscode.window.setStatusBarMessage(`Birkin: ${title}`, 3000);
}

export function activate(context: vscode.ExtensionContext): void {
  const client = new BirkinClient();
  const diffs = new DiffStore();
  const status = new StatusController(client, dashboard);
  const session = `vscode:${vscode.workspace.name ?? "default"}`;
  context.subscriptions.push(diffs, status,
    vscode.workspace.registerTextDocumentContentProvider("birkin-proposed", diffs));

  const ask = async (text: string): Promise<string> => {
    const current = snapshot();
    const editorContext = toEditorContext(current);
    try { await client.sendContext(await dashboard(), editorContext); }
    catch { /* Prompt packet below carries the same context when WebUI is absent. */ }
    status.running();
    const config = configuration();
    try {
      return await client.ask(config.gatewayUrl, config.gatewayToken, session,
        attachEditorContext(text, editorContext, current.openEditors));
    } finally { void status.refresh(); }
  };

  const guarded = (operation: () => Promise<void>) => async (): Promise<void> => {
    try { await operation(); }
    catch (error) { void vscode.window.showErrorMessage(`Birkin: ${errorMessage(error)}`); }
  };

  context.subscriptions.push(vscode.commands.registerCommand("birkin.ask", guarded(async () => {
    const text = await vscode.window.showInputBox({ prompt: "Ask Birkin", placeHolder: "Explain or change the selected code" });
    if (text === undefined || !text.trim()) return;
    await showText("response", await ask(text));
  })));

  context.subscriptions.push(vscode.commands.registerCommand("birkin.reviewPlan", guarded(async () => {
    const request = await vscode.window.showInputBox({ prompt: "What should Birkin plan?" });
    if (request === undefined || !request.trim()) return;
    const plan = await ask(
      `Plan this request without executing it or changing files. Return a concise, reviewable plan:\n${request}`);
    await showText("plan ready for review", `# Birkin Plan\n\n${plan}`);
    const decision = await vscode.window.showInformationMessage(
      "Review the Birkin plan. Execute it now?", { modal: true }, "Execute Plan");
    if (decision !== "Execute Plan") return;
    status.running("Executing plan");
    const config = configuration();
    const reply = await client.ask(config.gatewayUrl, config.gatewayToken, session,
      "Execute the plan I just reviewed. Keep consequential actions in Birkin's approval queue.");
    await showText("execution finished", reply);
    void vscode.commands.executeCommand("birkin.reviewApprovals");
  })));

  context.subscriptions.push(vscode.commands.registerCommand("birkin.reviewApprovals", guarded(async () => {
    const runtime = await dashboard();
    const approvals = await client.approvals(runtime);
    if (approvals.length === 0) { void vscode.window.showInformationMessage("Birkin has no pending approvals."); return; }
    const picked = await vscode.window.showQuickPick(approvals.map((approval) => ({
      label: approval.title, description: `${approval.risk ?? "review"} · ${approval.category}`,
      detail: approval.description, approval,
    })), { placeHolder: "Select an agent proposal to inspect" });
    if (picked === undefined) return;
    const change = proposedChange(picked.approval);
    if (change !== undefined) {
      const before = diffs.put(`${picked.approval.id}/before/${change.path}`, change.before);
      const after = diffs.put(`${picked.approval.id}/after/${change.path}`, change.after);
      await vscode.commands.executeCommand("vscode.diff", before, after,
        `Birkin proposal: ${change.path}`, { preview: true });
    } else {
      await showText("approval details", `# ${picked.approval.title}\n\n${picked.approval.description}\n\n\`\`\`json\n${JSON.stringify(picked.approval.payload, null, 2)}\n\`\`\``);
    }
    const action = await vscode.window.showWarningMessage(
      `Resolve “${picked.approval.title}”?`, { modal: true }, "Approve", "Reject");
    if (action === "Approve" || action === "Reject") {
      await client.resolve(runtime, picked.approval.id, action === "Approve" ? "approve" : "reject");
      void vscode.window.showInformationMessage(`Birkin proposal ${action.toLowerCase()}d.`);
      void status.refresh();
    }
  })));

  context.subscriptions.push(vscode.commands.registerCommand("birkin.rollback", guarded(async () => {
    const workspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (workspace === undefined) throw new Error("Open a workspace before rollback.");
    const runtime = await dashboard();
    const checkpoints = await client.checkpoints(runtime, workspace);
    const picked = await vscode.window.showQuickPick(checkpoints.map((checkpoint) => ({
      label: checkpoint.reason, description: checkpoint.short, detail: checkpoint.date, checkpoint,
    })), { placeHolder: "Restore a Birkin checkpoint" });
    if (picked === undefined) return;
    const confirm = await vscode.window.showWarningMessage(
      `Restore checkpoint ${picked.checkpoint.short}? Birkin snapshots the current state first.`,
      { modal: true }, "Restore");
    if (confirm !== "Restore") return;
    await client.rollback(runtime, picked.checkpoint.hash, workspace);
    void vscode.window.showInformationMessage("Birkin restored the checkpoint.");
  })));

  context.subscriptions.push(vscode.commands.registerCommand("birkin.refreshStatus", () => status.refresh()));
  status.start(configuration().refreshSeconds);
}

export function deactivate(): void {}
