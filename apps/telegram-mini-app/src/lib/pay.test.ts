import { afterEach, describe, expect, it, vi } from "vitest";
import { settleQuote } from "./pay";
import { saveSession } from "./session";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("settleQuote development", () => {
  it("uses simulated confirm in development", async () => {
    saveSession("tok", { id: "u" });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ quote_id: "q1", simulated: true }), {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await settleQuote("q1");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/dev/payments/");
  });
});
