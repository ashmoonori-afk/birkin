import { BirkinError } from "./errors.js";
import { parseApprovals, parseCheckpoints, parseReply, parseStatus } from "./contracts.js";
import type { Approval, Checkpoint, DashboardSession, EditorContext, RuntimeStatus } from "./types.js";

export type Request = (
  url: string,
  init: { readonly method: "GET" | "POST"; readonly headers: Readonly<Record<string, string>>; readonly body?: string },
) => Promise<{ readonly status: number; readonly body: string }>;

const nativeRequest: Request = async (url, init) => {
  try {
    const response = await fetch(url, init);
    return { status: response.status, body: await response.text() };
  } catch (error) {
    throw new BirkinError(`Cannot reach ${url}`, "transport", error);
  }
};

function decode(result: { readonly status: number; readonly body: string }): unknown {
  if (result.status < 200 || result.status >= 300) {
    throw new BirkinError(`Birkin returned HTTP ${result.status}: ${result.body.slice(0, 200)}`, "transport");
  }
  try { return JSON.parse(result.body) as unknown; }
  catch (error) { throw new BirkinError("Birkin returned invalid JSON", "contract", error); }
}

export class BirkinClient {
  public constructor(private readonly request: Request = nativeRequest) {}

  public async ask(url: string, token: string, session: string, text: string): Promise<string> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["X-Birkin-Token"] = token;
    return parseReply(decode(await this.request(url, { method: "POST", headers,
      body: JSON.stringify({ session, text }) })));
  }

  public async sendContext(runtime: DashboardSession, context: EditorContext): Promise<void> {
    decode(await this.post(runtime, "/api/context", context));
  }

  public async approvals(runtime: DashboardSession): Promise<readonly Approval[]> {
    return parseApprovals(decode(await this.get(runtime, "/api/approvals")));
  }

  public async resolve(runtime: DashboardSession, id: string, action: "approve" | "reject"): Promise<void> {
    decode(await this.post(runtime, "/api/approvals", { id, action }));
  }

  public async checkpoints(runtime: DashboardSession, workspace: string): Promise<readonly Checkpoint[]> {
    const query = `?workspace=${encodeURIComponent(workspace)}`;
    return parseCheckpoints(decode(await this.get(runtime, `/api/checkpoints${query}`)));
  }

  public async rollback(runtime: DashboardSession, hash: string, workspace: string): Promise<void> {
    decode(await this.post(runtime, `/api/checkpoints/${hash}/restore`, { workspace }));
  }

  public async status(runtime: DashboardSession): Promise<RuntimeStatus> {
    return parseStatus(decode(await this.get(runtime, "/api/status")));
  }

  private get(runtime: DashboardSession, path: string) {
    return this.request(`${runtime.url}${path}`, { method: "GET", headers: this.headers(runtime) });
  }

  private post(runtime: DashboardSession, path: string, value: object) {
    return this.request(`${runtime.url}${path}`, { method: "POST", headers: this.headers(runtime), body: JSON.stringify(value) });
  }

  private headers(runtime: DashboardSession): Readonly<Record<string, string>> {
    return { "Content-Type": "application/json", "X-Birkin-Token": runtime.token };
  }
}
