export interface Position {
  readonly line: number;
  readonly character: number;
}

export interface EditorContext {
  readonly file: string;
  readonly range: { readonly start: Position; readonly end: Position };
  readonly selection_text: string;
  readonly workspace: string;
}

export interface OpenEditor {
  readonly path: string;
  readonly language: string;
  readonly dirty: boolean;
}

export interface ProposedChange {
  readonly path: string;
  readonly before: string;
  readonly after: string;
}

export interface Approval {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly category: string;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly risk?: string;
}

export interface Checkpoint {
  readonly hash: string;
  readonly short: string;
  readonly date: string;
  readonly reason: string;
}

export interface DashboardSession {
  readonly url: string;
  readonly token: string;
}

export interface RuntimeStatus {
  readonly daemon: boolean;
  readonly stale: boolean;
  readonly pending_count: number;
  readonly model: string | null;
  readonly provider: string | null;
}
