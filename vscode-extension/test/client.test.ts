import { describe, expect, it, vi } from "vitest";
import { BirkinClient, type Request } from "../src/client.js";

const runtime = { url: "http://127.0.0.1:8787", token: "secret" };

describe("Birkin client", () => {
  it("uses the gateway's existing message contract", async () => {
    const request = vi.fn<Request>().mockResolvedValue({ status: 200, body: '{"reply":"done"}' });
    const client = new BirkinClient(request);
    await expect(client.ask("http://127.0.0.1:8788/message", "gate", "vscode:demo", "task"))
      .resolves.toBe("done");
    expect(request).toHaveBeenCalledWith("http://127.0.0.1:8788/message", expect.objectContaining({
      method: "POST", body: JSON.stringify({ session: "vscode:demo", text: "task" }),
      headers: expect.objectContaining({ "X-Birkin-Token": "gate" }),
    }));
  });

  it("routes approve through the dashboard approval authority", async () => {
    const request = vi.fn<Request>().mockResolvedValue({ status: 200, body: '{"ok":true}' });
    await new BirkinClient(request).resolve(runtime, "abc123abc123", "approve");
    expect(request).toHaveBeenCalledWith(`${runtime.url}/api/approvals`, expect.objectContaining({
      body: JSON.stringify({ id: "abc123abc123", action: "approve" }),
      headers: expect.objectContaining({ "X-Birkin-Token": "secret" }),
    }));
  });

  it("surfaces HTTP failures as typed transport errors", async () => {
    const request: Request = async () => ({ status: 403, body: "forbidden" });
    await expect(new BirkinClient(request).approvals(runtime)).rejects.toMatchObject({ code: "transport" });
  });
});
