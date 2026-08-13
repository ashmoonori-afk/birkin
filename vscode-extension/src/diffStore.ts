import * as vscode from "vscode";

export class DiffStore implements vscode.TextDocumentContentProvider, vscode.Disposable {
  private readonly values = new Map<string, string>();
  private readonly changed = new vscode.EventEmitter<vscode.Uri>();
  public readonly onDidChange = this.changed.event;

  public put(id: string, content: string): vscode.Uri {
    const uri = vscode.Uri.parse(`birkin-proposed:${id}`);
    this.values.set(uri.toString(), content);
    this.changed.fire(uri);
    return uri;
  }

  public provideTextDocumentContent(uri: vscode.Uri): string {
    return this.values.get(uri.toString()) ?? "";
  }

  public dispose(): void { this.changed.dispose(); this.values.clear(); }
}
