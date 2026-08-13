import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { BirkinError } from "./errors.js";
import { isObject } from "./contracts.js";
import type { DashboardSession } from "./types.js";

export async function discoverDashboard(
  urlOverride: string,
  tokenOverride: string,
  sessionPath = join(homedir(), ".birkin", "web_session.json"),
): Promise<DashboardSession> {
  if (urlOverride && tokenOverride) return { url: urlOverride.replace(/\/$/, ""), token: tokenOverride };
  try {
    const value: unknown = JSON.parse(await readFile(sessionPath, "utf8"));
    if (!isObject(value) || typeof value.port !== "number" || typeof value.token !== "string") {
      throw new Error("invalid session record");
    }
    return {
      url: urlOverride.replace(/\/$/, "") || `http://127.0.0.1:${value.port}`,
      token: tokenOverride || value.token,
    };
  } catch (error) {
    throw new BirkinError(
      "Birkin dashboard is not running. Start `birkin web --no-browser`.",
      "configuration", error,
    );
  }
}
