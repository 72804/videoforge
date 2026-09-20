"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import { SURPRISES } from "@/lib/format";
import { hapticTap } from "@/lib/haptics";

export function CreatePromptScreen() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function continueCreate() {
    setBusy(true);
    setError(null);
    hapticTap();
    try {
      const project = await client.createProject({
        prompt,
        title: prompt.slice(0, 42) || "Untitled",
        duration_mode: "AUTO",
        aspect_ratio: "9:16",
        quality_profile: "balanced",
      });
      router.push(`/create/${project.id}/characters`);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not create the project.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Create Video</h1>
      <p className="lede">Tell us the story. Characters come next.</p>
      <div className="field">
        <label htmlFor="prompt">Prompt</label>
        <textarea
          id="prompt"
          data-testid="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Create a dark comedy about two roommates who discover a mysterious box in their apartment..."
        />
      </div>
      <button
        className="btn ghost"
        type="button"
        onClick={() => setPrompt(SURPRISES[Math.floor(Math.random() * SURPRISES.length)])}
      >
        Surprise me
      </button>
      {error ? <p className="error">{error}</p> : null}
      <div style={{ height: 12 }} />
      <button
        className="btn primary"
        data-testid="continue-prompt"
        disabled={busy || prompt.trim().length < 8}
        onClick={continueCreate}
      >
        {busy ? "Saving…" : "Continue"}
      </button>
    </>
  );
}
