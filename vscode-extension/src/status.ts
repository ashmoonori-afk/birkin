import * as vscode from "vscode";
import { errorMessage } from "./errors.js";
import type { BirkinClient } from "./client.js";
import type { DashboardSession } from "./types.js";

export class StatusController implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 20);
  private timer: NodeJS.Timeout | undefined;
  private refreshController: AbortController | undefined;
  private refreshing = false;

  public constructor(private readonly client: BirkinClient, private readonly runtime: () => Promise<DashboardSession>) {
    this.item.command = "birkin.refreshStatus";
    this.item.name = "Birkin agent status";
    this.item.text = "$(circle-outline) Birkin";
    this.item.show();
  }

  public running(label = "Running"): void {
    this.item.text = `$(loading~spin) Birkin: ${label}`;
    this.item.tooltip = "Birkin agent turn is running";
  }

  public async refresh(): Promise<void> {
    if (this.refreshing) return;
    this.refreshing = true;
    const controller = new AbortController();
    this.refreshController = controller;
    try {
      const status = await this.client.status(
        await this.runtime(),
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const icon = status.daemon ? "$(pulse)" : "$(circle-slash)";
      this.item.text = `${icon} Birkin${status.pending_count ? ` · ${status.pending_count} review` : ""}`;
      this.item.tooltip = `${status.provider ?? "unknown"} / ${status.model ?? "default"}`;
    } catch (error) {
      if (controller.signal.aborted) return;
      this.item.text = "$(debug-disconnect) Birkin";
      this.item.tooltip = errorMessage(error);
    } finally {
      if (this.refreshController === controller) {
        this.refreshController = undefined;
        this.refreshing = false;
      }
    }
  }

  public start(seconds: number): void {
    this.stop();
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), seconds * 1000);
  }

  public stop(): void {
    if (this.timer !== undefined) clearInterval(this.timer);
    this.timer = undefined;
    this.refreshController?.abort();
  }
  public dispose(): void { this.stop(); this.item.dispose(); }
}
