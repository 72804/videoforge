import type { ApiError } from "./types";

const MESSAGES: Record<string, string> = {
  QUOTE_EXPIRED: "Price expired. Recalculate before generating.",
  PLAN_STALE: "The plan changed. Recalculate the price.",
  PAYMENT_REQUIRED: "Payment is required before generation.",
  LIMIT_EXCEEDED: "You've reached the current generation limit.",
  SCENE_LOCKED: "Unlock this scene before editing it.",
  MODEL_UNAVAILABLE: "This model is currently unavailable.",
  AUTH_INVALID: "Sign in again to continue.",
  AUTH_EXPIRED: "Your session expired. Sign in again.",
  FORBIDDEN: "You don't have access to this.",
  NOT_FOUND: "We couldn't find that.",
  JOB_CONFLICT: "A generation is already running.",
  IDEMPOTENCY_CONFLICT: "Retry with a fresh request.",
  INVALID_UPLOAD: "That photo couldn't be used. Try another image.",
  INVALID_PROJECT: "Check your project details and try again.",
};

export class ClientError extends Error {
  code: string;
  constructor(error: ApiError) {
    super(friendlyMessage(error));
    this.code = error.code;
    this.name = "ClientError";
  }
}

export function friendlyMessage(error: ApiError | { code?: string; message?: string }): string {
  const code = error.code || "INTERNAL";
  if (MESSAGES[code]) return MESSAGES[code];
  const raw = error.message || "";
  if (!raw || /traceback|sqlalchemy|psycopg|exception/i.test(raw)) {
    return "Something went wrong. Try again.";
  }
  return raw;
}

export function networkMessage(): string {
  return "Connection lost. Try again.";
}
