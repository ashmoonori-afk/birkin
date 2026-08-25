import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("authority-bearing settings", () => {
  it("keeps gateway and dashboard destinations machine scoped", async () => {
    const packageJson = JSON.parse(
      await readFile(join(__dirname, "..", "package.json"), "utf8"),
    ) as {
      contributes: {
        configuration: {
          properties: Record<string, { scope?: string }>;
        };
      };
    };
    const properties = packageJson.contributes.configuration.properties;

    expect(properties["birkin.gatewayUrl"]?.scope).toBe("machine");
    expect(properties["birkin.dashboardUrl"]?.scope).toBe("machine");
    expect(properties["birkin.dashboardToken"]?.scope).toBe("machine");
  });
});
