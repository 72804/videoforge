import { describe, expect, it } from "vitest";
import { resolveApiBase } from "./config";

describe("production API URL guard", () => {
  it("allows empty base in development", () => {
    expect(resolveApiBase("development", "")).toBe("");
  });

  it("rejects localhost and missing https in production", () => {
    expect(() => resolveApiBase("production", "")).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
    expect(() => resolveApiBase("production", "http://127.0.0.1:8000")).toThrow(
      /NEXT_PUBLIC_API_BASE_URL/,
    );
    expect(() => resolveApiBase("production", "http://api.example")).toThrow(
      /NEXT_PUBLIC_API_BASE_URL/,
    );
    expect(resolveApiBase("production", "https://api.example")).toBe("https://api.example");
  });
});
