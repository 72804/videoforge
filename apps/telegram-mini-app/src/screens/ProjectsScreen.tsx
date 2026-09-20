"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import { formatDuration, statusLabel } from "@/lib/format";
import type { Project } from "@/lib/types";

export function ProjectsScreen() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .projects()
      .then((list) =>
        setProjects([...list].sort((a, b) => b.updated_at.localeCompare(a.updated_at))),
      )
      .catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, []);

  return (
    <>
      <h1>Projects</h1>
      {error ? <p className="error">{error}</p> : null}
      {!projects ? <div className="skeleton" /> : null}
      {projects && projects.length === 0 ? <p className="lede">Create your first video.</p> : null}
      {projects?.map((p) => (
        <Link key={p.id} href={`/projects/${p.id}`} className="card" data-testid="project-card">
          <div className={`status-pill ${p.status}`}>{statusLabel(p.status)}</div>
          <h2 style={{ marginTop: 8 }}>{p.title}</h2>
          <p className="lede">
            {formatDuration(p.duration_seconds)} · {p.scene_count} scenes
          </p>
        </Link>
      ))}
    </>
  );
}
