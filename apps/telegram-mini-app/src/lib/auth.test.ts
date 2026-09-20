import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("auth bootstrap source", () => {
  it("sends initData to the server and never trusts initDataUnsafe", () => {
    const gate = readFileSync(path.join(__dirname, "../components/AuthGate.tsx"), "utf8");
    const api = readFileSync(path.join(__dirname, "api.ts"), "utf8");
    expect(api).toContain("/api/v1/auth/telegram");
    expect(api).toContain("/api/v1/dev/auth");
    expect(gate).toContain("authTelegram(init)");
    expect(gate).toContain("devAuth");
    expect(gate).not.toContain("initDataUnsafe");
  });
});
