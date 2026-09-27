"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import { hapticTap } from "@/lib/haptics";

export function FriendGroupStartScreen() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    hapticTap();
    try {
      const project = await client.createProject({
        prompt: "Friend group episode — situation coming next.",
        title: "Friend group video",
        duration_mode: "AUTO",
        aspect_ratio: "9:16",
        quality_profile: "balanced",
        content_type: "friend_group",
        visibility: "PRIVATE",
      });
      router.push(`/create/${project.id}/cast`);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not start.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Friend Group</h1>
      <p className="lede">Pick the cast first. Story comes after you know who is in the room.</p>
      {error ? <p className="error">{error}</p> : null}
      <button className="btn primary" data-testid="start-friend-group" disabled={busy} onClick={start}>
        {busy ? "Starting…" : "Select Cast"}
      </button>
    </>
  );
}
