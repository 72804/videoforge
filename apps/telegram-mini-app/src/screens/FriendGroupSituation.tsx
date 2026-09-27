"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";

export function FriendGroupSituationScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [style, setStyle] = useState("");
  const [privacy, setPrivacy] = useState("PRIVATE");
  const [quality, setQuality] = useState("balanced");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await client.patchProject(projectId, {
        prompt,
        title: prompt.slice(0, 42) || "Friend group video",
        style,
        visibility: privacy,
        quality_profile: quality,
      });
      router.push(`/create/${projectId}/review`);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Situation</h1>
      <p className="lede">What happens in the first three seconds?</p>
      <div className="field">
        <label htmlFor="situation">Prompt</label>
        <textarea
          id="situation"
          data-testid="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Birko dares Kemal to lie to Müge about the cola tab…"
        />
      </div>
      <div className="field">
        <label htmlFor="style">Style (optional)</label>
        <input id="style" value={style} onChange={(e) => setStyle(e.target.value)} />
      </div>
      <div className="field">
        <label>Privacy</label>
        <div className="chip-row">
          {["PRIVATE", "FRIENDS", "PUBLIC"].map((id) => (
            <button key={id} type="button" className={`chip ${privacy === id ? "on" : ""}`} onClick={() => setPrivacy(id)}>
              {id[0] + id.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label>Quality</label>
        <div className="chip-row">
          {["economy", "balanced", "premium"].map((id) => (
            <button key={id} type="button" className={`chip ${quality === id ? "on" : ""}`} onClick={() => setQuality(id)}>
              {id[0].toUpperCase() + id.slice(1)}
            </button>
          ))}
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <button className="btn primary" data-testid="continue-situation" disabled={busy || prompt.trim().length < 8} onClick={save}>
        Review
      </button>
    </>
  );
}
