import { describe, expect, it } from "vitest";
import { attachEditorContext, toEditorContext, type EditorSnapshot } from "../src/context.js";

const snapshot: EditorSnapshot = {
  file: "src/app.ts", workspace: "/work/demo", selection: "answer()",
  start: { line: 3, character: 2 }, end: { line: 3, character: 10 },
  openEditors: [
    { path: "src/app.ts", language: "typescript", dirty: true },
    { path: "README.md", language: "markdown", dirty: false },
  ],
};

describe("editor context", () => {
  it("preserves the active selection range", () => {
    expect(toEditorContext(snapshot)).toEqual({
      file: "src/app.ts", workspace: "/work/demo", selection_text: "answer()",
      range: { start: { line: 3, character: 2 }, end: { line: 3, character: 10 } },
    });
  });

  it("sends active selection and all open files as untrusted user data", () => {
    const prompt = attachEditorContext("Fix this", toEditorContext(snapshot), snapshot.openEditors);
    expect(prompt).toContain("Fix this");
    expect(prompt).toContain("answer()");
    expect(prompt).toContain("README.md");
    expect(prompt).toContain('trust="untrusted-user-data"');
  });
});
