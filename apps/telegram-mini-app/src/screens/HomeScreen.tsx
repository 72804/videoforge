"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import { formatDuration, stageLabel, statusLabel } from "@/lib/format";
import type { Project, Usage } from "@/lib/types";

export function HomeScreen() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([client.projects(), client.usage()])
      .then(([p, u]) => {
        setProjects(p);
        setUsage(u);
      })
      .catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, []);

  const active = projects?.find((p) => p.status === "generating");
  const recent = [...(projects || [])]
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 6);

  return (
    <>
      <h1>Create your next video</h1>
      <p className="lede">Write a prompt. We’ll handle story, pictures, motion, and sound.</p>
      <Link href="/create" className="btn primary" data-testid="create-cta">
        + Create Video
      </Link>
      {error ? <p className="error">{error}</p> : null}
      <div className="card" style={{ marginTop: 18 }}>
        <div className="lede" style={{ margin: 0 }}>Available</div>
        <div className="stars">{Math.max(0, (usage?.stars_purchased || 0) - (usage?.stars_debited || 0))} ⭐</div>
        <div className="sim">Simulated</div>
      </div>
      {active ? (
        <Link href={`/jobs/${active.active_job_id}`} className="card" data-testid="active-job">
          <div className="status-pill generating">{statusLabel(active.status)}</div>
          <h2 style={{ marginTop: 10 }}>{active.title}</h2>
          {active.progress
            ? Object.entries(active.progress).map(([k, v]) => (
                <p key={k} className="lede" style={{ margin: "4px 0" }}>
                  {stageLabel(k)} {v}
                </p>
              ))
            : null}
        </Link>
      ) : null}
      <h2>Recent</h2>
      {!projects ? <div className="skeleton" /> : null}
      {projects && recent.length === 0 ? (
        <p className="lede">Create your first video.</p>
      ) : (
        recent.map((p) => (
          <Link key={p.id} href={`/projects/${p.id}`} className="card">
            <strong>{p.title}</strong>
            <div className="lede" style={{ margin: "6px 0 0" }}>
              {statusLabel(p.status)} · {formatDuration(p.duration_seconds)} · {p.scene_count} scenes
            </div>
          </Link>
        ))
      )}
    </>
  );
}
