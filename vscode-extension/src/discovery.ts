import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { BirkinError } from "./errors.js";
import { isObject } from "./contracts.js";
import type { DashboardSession } from "./types.js";

interface DiscoveryOptions {
  readonly workspaceTrusted?: boolean;
  readonly readSession?: (path: string) => Promise<string>;
}

export async function discoverDashboard(
  urlOverride: string,
  tokenOverride: string,
  sessionPath = join(homedir(), ".birkin", "web_session.json"),
  options: DiscoveryOptions = {},
): Promise<DashboardSession> {
  const url = urlOverride.trim();
  const token = tokenOverride.trim();
  if (url || token) {
    if (!url || !token) {
      throw new BirkinError(
        "Dashboard URL and token overrides must both be configured.",
        "configuration",
      );
    }
    if (options.workspaceTrusted !== true) {
      throw new BirkinError(
        "Dashboard overrides require a trusted workspace.",
        "configuration",
      );
    }
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch (error) {
      throw new BirkinError(
        "Dashboard URL override is invalid.",
        "configuration",
        error,
      );
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new BirkinError(
        "Dashboard URL override must use HTTP or HTTPS.",
        "configuration",
      );
    }
    return { url: url.replace(/\/$/, ""), token };
  }
  try {
    const readSession = options.readSession
      ?? (async (path: string) => readFile(path, "utf8"));
    const value: unknown = JSON.parse(await readSession(sessionPath));
    if (
      !isObject(value)
      || typeof value.port !== "number"
      || !Number.isInteger(value.port)
      || value.port < 1
      || value.port > 65_535
      || typeof value.token !== "string"
      || !value.token
    ) {
      throw new Error("invalid session record");
    }
    return {
      url: `http://127.0.0.1:${value.port}`,
      token: value.token,
    };
  } catch (error) {
    throw new BirkinError(
      "Birkin dashboard is not running. Start `birkin web --no-browser`.",
      "configuration", error,
    );
  }
}
