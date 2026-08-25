import { describe, expect, it, vi } from "vitest";
import type { BirkinClient } from "../src/client.js";
import { StatusController } from "../src/status.js";
import type { DashboardSession, RuntimeStatus } from "../src/types.js";

const item = {
  command: "",
  name: "",
  text: "",
  tooltip: "",
  show: vi.fn(),
  dispose: vi.fn(),
};

vi.mock("vscode", () => ({
  StatusBarAlignment: { Left: 1 },
  window: {
    createStatusBarItem: () => item,
  },
}));

describe("status refresh lifecycle", () => {
  it("keeps one request in flight and aborts it on dispose", async () => {
    let release: ((value: RuntimeStatus) => void) | undefined;
    const signals: Array<AbortSignal | undefined> = [];
    const client = {
      status: (
        _runtime: DashboardSession,
        signal?: AbortSignal,
      ) => {
        signals.push(signal);
        return new Promise<RuntimeStatus>((resolve) => {
          release = resolve;
        });
      },
    } as unknown as BirkinClient;
    const controller = new StatusController(
      client,
      async () => ({ url: "http://127.0.0.1:1", token: "test-capability" }),
    );

    const first = controller.refresh();
    const second = controller.refresh();
    await Promise.resolve();

    expect(signals).toHaveLength(1);
    controller.dispose();
    expect(signals[0]?.aborted).toBe(true);
    release?.({
      daemon: false,
      stale: false,
      pending_count: 0,
      model: null,
      provider: null,
    });
    await Promise.all([first, second]);
  });
});
