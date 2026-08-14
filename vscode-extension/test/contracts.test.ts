import { describe, expect, it } from "vitest";
import { parseApprovals, parseStatus, proposedChange } from "../src/contracts.js";

describe("dashboard contracts", () => {
  it("extracts an inline file proposal from the existing approval payload", () => {
    const approval = parseApprovals([{
      id: "abc123abc123", title: "edit", description: "safe", category: "harness",
      payload: { edit: { path: "demo.ts", before: "old\n", after: "new\n" } }, risk: "medium",
    }])[0];
    expect(approval).toBeDefined();
    expect(proposedChange(approval!)).toEqual({ path: "demo.ts", before: "old\n", after: "new\n" });
  });

  it("rejects invented status shapes", () => {
    expect(() => parseStatus({ daemon: "yes", stale: false, pending_count: 0 })).toThrow();
  });
});
