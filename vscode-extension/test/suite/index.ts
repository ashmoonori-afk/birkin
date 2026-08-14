import * as assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { watch } from "node:fs";
import { join } from "node:path";
import * as vscode from "vscode";

async function screenshotGate(directory: string): Promise<void> {
  await mkdir(directory, { recursive: true });
  const resume = join(directory, "resume");
  const watcher = watch(directory);
  const resumed = new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("QA screenshot gate timed out")), 30_000);
    watcher.on("change", (_event, filename) => {
      if (filename === "resume") { clearTimeout(timer); resolve(); }
    });
    watcher.on("error", reject);
  });
  await writeFile(join(directory, "ready"), "diff open\n", "utf8");
  try { await resumed; } finally { watcher.close(); }
}

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension("birkin.birkin-vscode");
  assert.ok(extension, "Birkin extension is installed in the development host");
  await extension.activate();
  assert.equal(extension.isActive, true, "Birkin extension activates");

  const commands = await vscode.commands.getCommands(true);
  for (const command of ["birkin.ask", "birkin.reviewPlan", "birkin.reviewApprovals",
    "birkin.rollback", "birkin.refreshStatus"]) {
    assert.ok(commands.includes(command), `${command} is registered`);
  }

  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  assert.ok(root, "development host has a workspace");
  const before = vscode.Uri.joinPath(root, ".birkin-qa-before.ts");
  const after = vscode.Uri.joinPath(root, ".birkin-qa-after.ts");
  await vscode.workspace.fs.writeFile(before, Buffer.from("const status = 'before';\n"));
  await vscode.workspace.fs.writeFile(after, Buffer.from("const status = 'after';\n"));
  try {
    await vscode.commands.executeCommand("vscode.diff", before, after, "Birkin proposed change");
    assert.equal(vscode.window.tabGroups.activeTabGroup.activeTab?.label,
      "Birkin proposed change", "proposed diff opens in the editor host");
    const gate = process.env.BIRKIN_QA_SCREENSHOT_GATE;
    if (gate) await screenshotGate(gate);
    await vscode.commands.executeCommand("birkin.refreshStatus");
  } finally {
    await Promise.all([vscode.workspace.fs.delete(before), vscode.workspace.fs.delete(after)]);
  }
  console.log("QA: activation, commands, proposed diff editor, and status refresh exercised");
}
