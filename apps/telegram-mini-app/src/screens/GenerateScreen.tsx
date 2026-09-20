"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import { stageLabel } from "@/lib/format";
import type { Job } from "@/lib/types";

const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED", "PARTIAL"]);

export function GenerateScreen({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    async function tick() {
      try {
        const next = await client.job(jobId);
        if (stop) return;
        setJob(next);
        if (!TERMINAL.has(next.status)) {
          window.setTimeout(tick, 1500);
        }
      } catch (err) {
        if (!stop) setError(err instanceof ClientError ? err.message : "Could not load progress.");
      }
    }
    tick();
    return () => {
      stop = true;
    };
  }, [jobId]);

  useEffect(() => {
    if (job?.status === "COMPLETED" || job?.status === "PARTIAL") {
      const t = window.setTimeout(() => router.push(`/projects/${job.project_id}`), 600);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [job, router]);

  return (
    <>
      <h1>Generating</h1>
      <p className="lede">{job?.current_stage || "Starting"}</p>
      {!job ? <div className="skeleton" /> : null}
      {job?.work_units.map((unit) => {
        const done = unit.total > 0 && unit.completed >= unit.total;
        return (
          <div className="card" key={unit.type} data-testid={`unit-${unit.type}`}>
            <strong>{stageLabel(unit.type)}</strong>
            <p className="lede" style={{ margin: "6px 0 0" }}>
              {done ? "✓" : unit.total ? `${unit.completed} / ${unit.total}` : "waiting"}
            </p>
            {unit.total ? (
              <div className="progress" style={{ marginTop: 10 }}>
                <span style={{ width: `${Math.min(100, (unit.completed / unit.total) * 100)}%` }} />
              </div>
            ) : null}
          </div>
        );
      })}
      {job?.status === "FAILED" ? <p className="error">{job.failure_message || "Generation failed."}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <p className="lede">You can leave this screen. Progress is saved.</p>
    </>
  );
}
