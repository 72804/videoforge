"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { client } from "@/lib/api";
import { IS_DEV } from "@/lib/config";
import { ClientError } from "@/lib/errors";
import { formatDuration, statusLabel } from "@/lib/format";
import { hapticSuccess } from "@/lib/haptics";
import type { Project, Scene } from "@/lib/types";

export function ProjectScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rendering, setRendering] = useState("");

  async function load() {
    const [p, s] = await Promise.all([client.project(projectId), client.scenes(projectId)]);
    setProject(p);
    setScenes(s);
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, [projectId]);

  async function render() {
    setBusy(true);
    setError(null);
    setRendering("Calculating…");
    try {
      const plan = await client.plan(projectId, "render");
      const quote = await client.quote(projectId, plan.plan_id);
      await client.confirmPayment(quote.quote_id);
      setRendering("Rendering…");
      const job = await client.render(projectId, quote.quote_id);
      if (IS_DEV) await client.runWorker(job.job_id);
      hapticSuccess();
      setRendering("Ready");
      await load();
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Render failed.");
    } finally {
      setBusy(false);
    }
  }

  async function move(index: number, dir: -1 | 1) {
    const next = [...scenes];
    const swap = index + dir;
    if (swap < 0 || swap >= next.length) return;
    const tmp = next[index];
    next[index] = next[swap];
    next[swap] = tmp;
    await client.reorder(projectId, next.map((s) => s.id));
    await load();
  }

  return (
    <>
      <h1>{project?.title || "Project"}</h1>
      <div className={`status-pill ${project?.status || ""}`}>{statusLabel(project?.status || "")}</div>
      <div className="card" style={{ minHeight: 180, marginTop: 16 }}>
        <p className="lede">{project?.prompt}</p>
        <p>{formatDuration(project?.duration_seconds)}</p>
        {IS_DEV ? <div className="mock-tag" style={{ position: "relative" }}>Mock preview</div> : null}
      </div>
      {project?.status === "generating" && project.active_job_id ? (
        <Link className="btn" href={`/jobs/${project.active_job_id}`}>
          View progress
        </Link>
      ) : null}
      <div className="row" style={{ margin: "12px 0" }}>
        <button className="btn primary" type="button">Play / Preview</button>
        <button className="btn" data-testid="render" disabled={busy} onClick={render}>
          {rendering || "Render / Export"}
        </button>
      </div>
      <h2>Scenes</h2>
      <div className="strip" data-testid="scene-strip">
        {scenes.map((scene, index) => (
          <button
            key={scene.id}
            className="scene-card"
            onClick={() => router.push(`/projects/${projectId}/scenes/${scene.id}`)}
          >
            {IS_DEV ? <span className="mock-tag">Mock Scene {index + 1}</span> : null}
            {scene.locked ? <span>🔒</span> : null}
            <strong>Scene {index + 1}</strong>
            <span>{formatDuration(scene.duration_seconds)}</span>
            <span>{scene.video_asset_version_id ? "Video" : "Still"}</span>
          </button>
        ))}
      </div>
      {scenes.map((scene, index) => (
        <div key={`${scene.id}-move`} className="row" style={{ marginBottom: 8 }}>
          <button className="btn ghost" onClick={() => move(index, -1)} disabled={index === 0}>
            Move earlier
          </button>
          <button className="btn ghost" data-testid="move-later" onClick={() => move(index, 1)} disabled={index === scenes.length - 1}>
            Move later
          </button>
        </div>
      ))}
      {error ? <p className="error">{error}</p> : null}
    </>
  );
}
