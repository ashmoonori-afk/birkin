import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { discoverDashboard } from "../src/discovery.js";

describe("dashboard discovery", () => {
  it("reads the private runtime session emitted by birkin web", async () => {
    const directory = await mkdtemp(join(tmpdir(), "birkin-vscode-"));
    const path = join(directory, "session.json");
    await writeFile(path, JSON.stringify({ port: 54321, token: "capability" }), "utf8");
    await expect(discoverDashboard("", "", path)).resolves.toEqual({
      url: "http://127.0.0.1:54321", token: "capability",
    });
  });

  it("rejects a URL override without a paired token before reading local authority", async () => {
    const reads: string[] = [];
    await expect(discoverDashboard(
      "https://example.invalid",
      "",
      "unused-session.json",
      {
        workspaceTrusted: true,
        readSession: async (path) => {
          reads.push(path);
          return JSON.stringify({ port: 54321, token: "local-capability" });
        },
      },
    )).rejects.toThrow("both");
    expect(reads).toEqual([]);
  });

  it("rejects paired overrides from an untrusted workspace", async () => {
    await expect(discoverDashboard(
      "https://example.invalid",
      "override-capability",
      "unused-session.json",
      { workspaceTrusted: false },
    )).rejects.toThrow("trusted workspace");
  });

  it("constructs local discovery with a literal loopback host", async () => {
    const value = await discoverDashboard(
      "",
      "",
      "session.json",
      {
        readSession: async () => JSON.stringify({
          port: 54321,
          token: "local-capability",
          host: "example.invalid",
        }),
      },
    );
    expect(value).toEqual({
      url: "http://127.0.0.1:54321",
      token: "local-capability",
    });
  });
});
