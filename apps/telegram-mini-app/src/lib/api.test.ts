import { afterEach, describe, expect, it, vi } from "vitest";
import { client } from "./api";
import { saveSession } from "./session";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("api client", () => {
  it("sends bearer session and request id", async () => {
    saveSession("tok", { id: "u1" });
    const fetchMock = vi.fn().mockResolvedValue(json([{ id: "auto", display_name: "Auto", capabilities: [], quality_tier: "standard", available: true }]));
    vi.stubGlobal("fetch", fetchMock);
    await client.models();
    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
    expect(headers.get("X-Request-ID")).toBeTruthy();
  });

  it("parses API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json({ error: { code: "SCENE_LOCKED", message: "locked" } }, 409)),
    );
    await expect(client.lockScene("s1")).rejects.toMatchObject({ code: "SCENE_LOCKED" });
  });

  it("creates AUTO projects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ id: "p1", duration_mode: "AUTO" })));
    const project = await client.createProject({ prompt: "hello", duration_mode: "AUTO" });
    expect(project.id).toBe("p1");
  });

  it("quotes and starts generation with simulated payment", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ plan_id: "pl1", scene_count: 3, line_items: [] }))
      .mockResolvedValueOnce(json({ quote_id: "q1", stars: 240, simulated: true }))
      .mockResolvedValueOnce(json({ quote_id: "q1", status: "AUTHORIZED", simulated: true }))
      .mockResolvedValueOnce(json({ job_id: "j1", status: "QUEUED" }))
      .mockResolvedValueOnce(json({ job_id: "j1", status: "COMPLETED", work_units: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await client.plan("p1");
    await client.quote("p1", "pl1");
    await client.confirmPayment("q1");
    const job = await client.generate("p1", "q1");
    expect(job.job_id).toBe("j1");
    const polled = await client.job("j1");
    expect(polled.status).toBe("COMPLETED");
  });

  it("maps network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(client.projects()).rejects.toMatchObject({ code: "NETWORK" });
  });

  it("covers character, scene, and render client paths", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes("/characters") && init?.method === "POST" && !(init as { form?: FormData }).form) {
        return json({ id: "c1", name: "Alex" });
      }
      if (u.includes("/references")) return json({ id: "r1" });
      if (u.includes("/reorder")) return json({ invalidated: ["render"] });
      if (u.includes("/lock")) return json({ ok: true });
      if (u.includes("/restore")) return json({ ok: true });
      if (u.includes("regenerate-image")) return json({ job_id: "ji", status: "QUEUED" });
      if (u.includes("regenerate-video")) return json({ job_id: "jv", status: "QUEUED" });
      if (u.includes("/render")) return json({ job_id: "jr", status: "QUEUED" });
      if (u.includes("/scenes/") && init?.method === "PATCH") {
        return json({ scene_version: { id: "v2" }, invalidated: ["video"] });
      }
      return json({ id: "ok" });
    });
    vi.stubGlobal("fetch", fetchMock);
    await client.createCharacter("p1", { name: "Alex", description: "curious" });
    await client.uploadReference("c1", new File(["x"], "a.jpg", { type: "image/jpeg" }));
    await client.patchScene("s1", { visual_prompt: "box" });
    await client.lockScene("s1");
    await client.regenImage("s1", "q1");
    await client.regenVideo("s1", "q1");
    await client.restore("s1", "v1");
    await client.reorder("p1", ["s2", "s1"]);
    await client.render("p1", "q2");
    expect(fetchMock).toHaveBeenCalled();
  });
});
