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
});
