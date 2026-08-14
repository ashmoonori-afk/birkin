export class BirkinError extends Error {
  public constructor(
    message: string,
    public readonly code: "configuration" | "transport" | "contract" | "cancelled",
    public override readonly cause?: unknown,
  ) {
    super(message);
    this.name = "BirkinError";
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
