import type { EditorContext, OpenEditor, Position } from "./types.js";

export interface EditorSnapshot {
  readonly file: string;
  readonly workspace: string;
  readonly selection: string;
  readonly start: Position;
  readonly end: Position;
  readonly openEditors: readonly OpenEditor[];
}

export function toEditorContext(snapshot: EditorSnapshot): EditorContext {
  return {
    file: snapshot.file,
    workspace: snapshot.workspace,
    selection_text: snapshot.selection,
    range: { start: snapshot.start, end: snapshot.end },
  };
}

export function attachEditorContext(
  request: string,
  context: EditorContext,
  openEditors: readonly OpenEditor[],
): string {
  const packet = JSON.stringify({ active: context, openFiles: openEditors }, null, 2);
  return `${request}\n\n<editor-context trust="untrusted-user-data">\n${packet}\n</editor-context>`;
}
