"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { client } from "@/lib/api";
import { IS_DEV } from "@/lib/config";
import { ClientError } from "@/lib/errors";
import { invalidationMessage } from "@/lib/format";
import { hapticSuccess, hapticWarn } from "@/lib/haptics";
import { settleQuote } from "@/lib/pay";
import { telegram } from "@/lib/telegram";
import type { Scene, SceneVersion } from "@/lib/types";

export function SceneEditorScreen({ projectId, sceneId }: { projectId: string; sceneId: string }) {
  const router = useRouter();
  const [scene, setScene] = useState<Scene | null>(null);
  const [visual, setVisual] = useState("");
  const [motion, setMotion] = useState("");
  const [saved, setSaved] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [quoteStars, setQuoteStars] = useState<number | null>(null);
  const [quoteId, setQuoteId] = useState<string | null>(null);
  const [regenKind, setRegenKind] = useState<"scene_image" | "scene_video" | null>(null);
  const [versions, setVersions] = useState<SceneVersion[]>([]);
  const [activeVersion, setActiveVersion] = useState<string>("");
  const [duration, setDuration] = useState("");
  const [imageModel, setImageModel] = useState("");
  const [videoModel, setVideoModel] = useState("");
  const [locked, setLocked] = useState(false);

  async function load() {
    const [list, detail, vers] = await Promise.all([
      client.scenes(projectId),
      client.scene(sceneId),
      client.versions(sceneId),
    ]);
    const row = list.find((s) => s.id === sceneId) || null;
    setScene(row);
    setVisual(detail.active_version.visual_prompt);
    setMotion(detail.active_version.motion_prompt);
    setDuration(String(detail.active_version.duration_seconds ?? ""));
    setImageModel(detail.active_version.image_model || "auto");
    setVideoModel(detail.active_version.video_model || "auto");
    setLocked(detail.scene.locked);
    setVersions(vers.versions);
    setActiveVersion(vers.active_version_id);
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
    const back = () => router.push(`/projects/${projectId}`);
    telegram()?.BackButton.show();
    telegram()?.BackButton.onClick(back);
    return () => {
      telegram()?.BackButton.offClick(back);
      telegram()?.BackButton.hide();
    };
  }, [projectId, sceneId, router]);

  async function save() {
    if (locked) {
      setError("Unlock this scene before editing it.");
      hapticWarn();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await client.patchScene(sceneId, {
        visual_prompt: visual,
        motion_prompt: motion,
        duration_seconds: duration ? Number(duration) : undefined,
        image_model: imageModel,
        video_model: videoModel,
      });
      setSaved(invalidationMessage(res.invalidated));
      hapticSuccess();
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function prepareRegen(kind: "scene_image" | "scene_video") {
    setBusy(true);
    setError(null);
    try {
      const plan = await client.plan(projectId, kind, sceneId);
      const quote = await client.quote(projectId, plan.plan_id);
      setQuoteStars(quote.stars);
      setQuoteId(quote.quote_id);
      setRegenKind(kind);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not quote regeneration.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmRegen() {
    if (!quoteId || !regenKind) return;
    setBusy(true);
    try {
      await settleQuote(quoteId);
      const job =
        regenKind === "scene_image"
          ? await client.regenImage(sceneId, quoteId)
          : await client.regenVideo(sceneId, quoteId);
      if (IS_DEV) await client.runWorker(job.job_id);
      hapticSuccess();
      setRegenKind(null);
      router.push(`/jobs/${job.job_id}`);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Regeneration failed.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleLock() {
    if (locked) await client.unlockScene(sceneId);
    else await client.lockScene(sceneId);
    await load();
  }

  return (
    <>
      <button className="btn ghost" data-testid="back-project" onClick={() => router.push(`/projects/${projectId}`)}>
        Back to project
      </button>
      <h1>Scene {(scene?.order_index ?? 0) + 1}</h1>
      {locked ? (
        <p className="lede">Locked. Automatic project regeneration will not replace this scene.</p>
      ) : null}
      <div className="card" style={{ minHeight: 140 }}>
        {IS_DEV ? <div className="mock-tag" style={{ position: "relative" }}>Mock scene</div> : null}
        <p>{scene?.duration_seconds}s</p>
        <p className="lede">Characters: {scene?.characters?.length ? scene.characters.join(", ") : "None"}</p>
      </div>
      <div className="field">
        <label htmlFor="visual">Visual prompt</label>
        <textarea id="visual" data-testid="visual-prompt" value={visual} onChange={(e) => setVisual(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="motion">Motion prompt</label>
        <textarea id="motion" value={motion} onChange={(e) => setMotion(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="sdur">Duration (seconds)</label>
        <input id="sdur" type="number" min={1} max={16} value={duration} onChange={(e) => setDuration(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="imodel">Image model</label>
        <input id="imodel" value={imageModel} onChange={(e) => setImageModel(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="vmodel">Video model</label>
        <input id="vmodel" value={videoModel} onChange={(e) => setVideoModel(e.target.value)} />
      </div>
      {saved ? <p className="ok">{saved === "Saved." ? "Saved" : saved}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <button className="btn primary" data-testid="save-scene" disabled={busy} onClick={save}>
        {busy ? "Saving…" : "Save"}
      </button>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn" disabled={busy || locked} onClick={() => prepareRegen("scene_image")}>
          Regenerate Image
        </button>
        <button className="btn" data-testid="regen-video" disabled={busy || locked} onClick={() => prepareRegen("scene_video")}>
          Regenerate Video
        </button>
      </div>
      <button className="btn ghost" style={{ marginTop: 12 }} onClick={toggleLock} data-testid="lock-scene">
        {locked ? "Unlock" : "Lock"}
      </button>
      {regenKind && quoteStars !== null ? (
        <div className="card" data-testid="regen-quote">
          <h2>{regenKind === "scene_image" ? "Regenerate image" : "Regenerate video"}</h2>
          <div className="stars">{quoteStars} ⭐</div>
          {IS_DEV ? <div className="sim">Simulated payment</div> : <p className="lede">Pay with Telegram Stars.</p>}
          <p className="lede">This will replace the current version. Previous versions remain available.</p>
          {regenKind === "scene_video" ? <p>Selected model: Veo Lite · Duration: 8 sec</p> : null}
          <div className="row">
            <button className="btn ghost" onClick={() => setRegenKind(null)}>Cancel</button>
            <button className="btn primary" data-testid="confirm-regen" disabled={busy} onClick={confirmRegen}>
              Regenerate
            </button>
          </div>
        </div>
      ) : null}
      <h2>Versions</h2>
      {versions
        .slice()
        .reverse()
        .map((version, idx, arr) => (
          <div className="card" key={version.id}>
            <strong>
              Version {arr.length - idx}
              {version.id === activeVersion ? " — Current" : ""}
            </strong>
            <p className="lede">
              {new Date(version.created_at).toLocaleString()} · {version.image_model} / {version.video_model} · {version.duration_seconds}s
            </p>
            {version.id !== activeVersion ? (
              <button
                className="btn"
                data-testid="restore-version"
                onClick={async () => {
                  if (!window.confirm("Restore this version as current? Nothing is deleted.")) return;
                  await client.restore(sceneId, version.id);
                  await load();
                }}
              >
                Restore
              </button>
            ) : null}
          </div>
        ))}
    </>
  );
}
