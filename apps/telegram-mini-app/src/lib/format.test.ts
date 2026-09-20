import { describe, expect, it } from "vitest";
import { friendlyMessage } from "./errors";
import {
  SURPRISES,
  durationPayload,
  formatDuration,
  invalidationMessage,
  lineItemLabel,
  stageLabel,
  statusLabel,
} from "./format";

describe("format", () => {
  it("formats duration", () => {
    expect(formatDuration(8)).toBe("8s");
    expect(formatDuration(68)).toBe("~1m 08s");
  });
  it("maps statuses", () => {
    expect(statusLabel("draft")).toBe("Draft");
    expect(statusLabel("generating")).toBe("Generating");
    expect(statusLabel("ready")).toBe("Ready");
    expect(statusLabel("failed")).toBe("Failed");
    expect(statusLabel("quoted")).toBe("Waiting for payment");
  });
  it("maps line items without USD", () => {
    expect(lineItemLabel("still")).toBe("Images");
    expect(lineItemLabel("video")).toBe("Video animation");
  });
  it("explains invalidation without enums", () => {
    expect(invalidationMessage(["video"])).toMatch(/Video needs to be regenerated/);
  });
  it("builds AUTO and FIXED duration payloads", () => {
    expect(durationPayload("AUTO", "45")).toEqual({
      duration_mode: "AUTO",
      target_duration_seconds: null,
    });
    expect(durationPayload("60", "45").duration_mode).toBe("FIXED");
  });
  it("has local surprise prompts", () => {
    expect(SURPRISES.length).toBeGreaterThan(1);
  });
  it("labels work units", () => {
    expect(stageLabel("images")).toBe("Creating images");
    expect(stageLabel("script")).toBe("Story");
  });
});

describe("errors", () => {
  it("maps backend codes", () => {
    expect(friendlyMessage({ code: "QUOTE_EXPIRED" })).toMatch(/Price expired/);
    expect(friendlyMessage({ code: "PAYMENT_REQUIRED" })).toMatch(/Payment is required/);
    expect(friendlyMessage({ code: "LIMIT_EXCEEDED" })).toMatch(/limit/);
    expect(friendlyMessage({ code: "SCENE_LOCKED" })).toMatch(/Unlock/);
    expect(friendlyMessage({ code: "MODEL_UNAVAILABLE" })).toMatch(/unavailable/);
  });
  it("hides raw internals", () => {
    expect(friendlyMessage({ code: "X", message: "sqlalchemy traceback" })).toMatch(/Something went wrong/);
  });
});
