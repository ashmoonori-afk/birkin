import { BirkinError } from "./errors.js";
import type { Approval, Checkpoint, ProposedChange, RuntimeStatus } from "./types.js";

type JsonObject = Readonly<Record<string, unknown>>;

export function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringField(value: JsonObject, key: string): string {
  const field = value[key];
  if (typeof field !== "string") {
    throw new BirkinError(`Birkin response is missing ${key}`, "contract");
  }
  return field;
}

export function parseReply(value: unknown): string {
  if (!isObject(value)) throw new BirkinError("Invalid gateway response", "contract");
  return stringField(value, "reply");
}

export function parseApprovals(value: unknown): readonly Approval[] {
  if (!Array.isArray(value)) throw new BirkinError("Invalid approvals response", "contract");
  return value.map((item) => {
    if (!isObject(item) || !isObject(item.payload)) {
      throw new BirkinError("Invalid approval record", "contract");
    }
    const risk = typeof item.risk === "string" ? item.risk : undefined;
    return {
      id: stringField(item, "id"), title: stringField(item, "title"),
      description: typeof item.description === "string" ? item.description : "",
      category: stringField(item, "category"), payload: item.payload,
      ...(risk === undefined ? {} : { risk }),
    };
  });
}

export function parseCheckpoints(value: unknown): readonly Checkpoint[] {
  if (!Array.isArray(value)) throw new BirkinError("Invalid checkpoints response", "contract");
  return value.map((item) => {
    if (!isObject(item)) throw new BirkinError("Invalid checkpoint record", "contract");
    return { hash: stringField(item, "hash"), short: stringField(item, "short"),
      date: stringField(item, "date"), reason: stringField(item, "reason") };
  });
}

export function parseStatus(value: unknown): RuntimeStatus {
  if (!isObject(value)) throw new BirkinError("Invalid status response", "contract");
  const daemon = value.daemon;
  const stale = value.stale;
  const count = value.pending_count;
  if (typeof daemon !== "boolean" || typeof stale !== "boolean" || typeof count !== "number") {
    throw new BirkinError("Invalid status fields", "contract");
  }
  return { daemon, stale, pending_count: count,
    model: typeof value.model === "string" ? value.model : null,
    provider: typeof value.provider === "string" ? value.provider : null };
}

export function proposedChange(approval: Approval): ProposedChange | undefined {
  const nested = approval.payload.edit;
  const edit = isObject(nested) ? nested : approval.payload;
  const path = edit.file ?? edit.path;
  if (typeof path !== "string" || typeof edit.before !== "string" || typeof edit.after !== "string") {
    return undefined;
  }
  return { path, before: edit.before, after: edit.after };
}
