"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { client } from "@/lib/api";
import { IS_DEV } from "@/lib/config";
import { ClientError } from "@/lib/errors";
import { formatDuration, lineItemLabel } from "@/lib/format";
import { hapticSuccess } from "@/lib/haptics";
import type { Character, Plan, Project, Quote } from "@/lib/types";

export function CreateReviewScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState(false);

  useEffect(() => {
    Promise.all([client.project(projectId), client.characters(projectId)])
      .then(([p, c]) => {
        setProject(p);
        setCharacters(c);
      })
      .catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, [projectId]);

  async function calculate() {
    setBusy(true);
    setError(null);
    try {
      const nextPlan = await client.plan(projectId);
      const nextQuote = await client.quote(projectId, nextPlan.plan_id);
      setPlan(nextPlan);
      setQuote(nextQuote);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not calculate price.");
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    if (!quote) return;
    if (!window.confirm("Simulated payment only. No real Telegram Stars will be charged. Continue?")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await client.confirmPayment(quote.quote_id);
      hapticSuccess();
      const job = await client.generate(projectId, quote.quote_id);
      if (IS_DEV) {
        await client.runWorker(job.job_id);
      }
      router.push(`/jobs/${job.job_id}`);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not start generation.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Review</h1>
      {!project ? <div className="skeleton" /> : null}
      <div className="card">
        <p className="lede">{project?.prompt}</p>
        <p>Duration · {project?.duration_mode === "AUTO" ? "Auto" : formatDuration(project?.target_duration_seconds)}</p>
        <p>Aspect · {project?.aspect_ratio}</p>
        <p>Quality · {project?.quality_profile}</p>
        <p>Models · Auto unless you changed them</p>
        <p>Characters · {characters.length ? characters.map((c) => c.name).join(", ") : "None"}</p>
      </div>
      {!quote ? (
        <button className="btn primary" data-testid="calculate-price" disabled={busy} onClick={calculate}>
          {busy ? "Calculating…" : "Calculate Price"}
        </button>
      ) : (
        <div className="card" data-testid="quote-card">
          <h2>Your video</h2>
          <p>Estimated duration {formatDuration(plan?.duration_seconds)}</p>
          <p>Estimated scenes {plan?.scene_count}</p>
          <p>AI video scenes {plan?.video_generations}</p>
          <p>Images {plan?.image_generations}</p>
          <p>Voice included · Music included</p>
          <div className="stars">{quote.stars} ⭐</div>
          <div className="sim">Simulated payment</div>
          <button className="btn ghost" style={{ marginTop: 12 }} onClick={() => setDetails(!details)}>
            {details ? "Hide details" : "View details"}
          </button>
          {details
            ? plan?.line_items.map((item) => (
                <p key={item.type}>
                  {lineItemLabel(item.type)} · {item.customer_stars} ⭐
                </p>
              ))
            : null}
        </div>
      )}
      {error ? <p className="error">{error}</p> : null}
      {quote ? (
        <button className="btn primary" data-testid="generate" disabled={busy} onClick={generate}>
          {busy ? "Starting…" : "Generate Video"}
        </button>
      ) : null}
    </>
  );
}
