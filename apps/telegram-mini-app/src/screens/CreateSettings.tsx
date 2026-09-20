"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import { durationPayload } from "@/lib/format";
import { telegram } from "@/lib/telegram";
import type { Model, Project } from "@/lib/types";

const DURATIONS = [
  { id: "AUTO", label: "Auto" },
  { id: "30", label: "30 sec" },
  { id: "60", label: "60 sec" },
  { id: "120", label: "2 min" },
  { id: "custom", label: "Custom" },
];

export function CreateSettingsScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [duration, setDuration] = useState("AUTO");
  const [custom, setCustom] = useState("45");
  const [aspect, setAspect] = useState("9:16");
  const [language, setLanguage] = useState("en");
  const [quality, setQuality] = useState("balanced");
  const [text, setText] = useState("auto");
  const [image, setImage] = useState("auto");
  const [video, setVideo] = useState("auto");
  const [voice, setVoice] = useState("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    telegram()?.BackButton.show();
    const back = () => router.push(`/create/${projectId}/characters`);
    telegram()?.BackButton.onClick(back);
    return () => {
      telegram()?.BackButton.offClick(back);
      telegram()?.BackButton.hide();
    };
  }, [projectId, router]);

  useEffect(() => {
    Promise.all([client.project(projectId), client.models()])
      .then(([p, m]) => {
        setProject(p);
        setModels(m);
        setAspect(p.aspect_ratio || "9:16");
        setLanguage(p.language || "en");
        setQuality(p.quality_profile || "balanced");
      })
      .catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, [projectId]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const duration_mode = durationPayload(duration, custom);
      await client.patchProject(projectId, {
        duration_mode: duration_mode.duration_mode,
        target_duration_seconds: duration_mode.target_duration_seconds,
        aspect_ratio: aspect,
        language: language === "auto" ? "en" : language,
        quality_profile: quality,
        default_text_model: text,
        default_image_model: image,
        default_video_model: video,
        default_voice_model: voice,
      });
      router.push(`/create/${projectId}/review`);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not save settings.");
    } finally {
      setBusy(false);
    }
  }

  const byCap = (cap: string) => models.filter((m) => m.capabilities.includes(cap) || m.id === "auto");

  return (
    <>
      <h1>Video settings</h1>
      {!project ? <div className="skeleton" /> : null}
      <div className="field">
        <label>Duration</label>
        <div className="chip-row">
          {DURATIONS.map((d) => (
            <button key={d.id} className={`chip ${duration === d.id ? "on" : ""}`} onClick={() => setDuration(d.id)}>
              {d.label}
            </button>
          ))}
        </div>
      </div>
      {duration === "custom" ? (
        <div className="field">
          <label htmlFor="secs">Custom seconds</label>
          <input id="secs" type="number" min={4} max={180} value={custom} onChange={(e) => setCustom(e.target.value)} />
        </div>
      ) : null}
      <div className="field">
        <label>Aspect ratio</label>
        <div className="chip-row">
          {["9:16", "16:9", "1:1"].map((a) => (
            <button key={a} className={`chip ${aspect === a ? "on" : ""}`} onClick={() => setAspect(a)}>
              {a}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="lang">Language</label>
        <select id="lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="auto">Auto</option>
          <option value="en">English</option>
          <option value="tr">Turkish</option>
        </select>
      </div>
      <div className="field">
        <label>Quality</label>
        <div className="chip-row">
          {[
            ["economy", "Economy"],
            ["balanced", "Balanced"],
            ["premium", "Premium"],
          ].map(([id, label]) => (
            <button key={id} className={`chip ${quality === id ? "on" : ""}`} onClick={() => setQuality(id)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <details className="advanced">
        <summary>Advanced models</summary>
        <p className="lede">Auto chooses the best model for your selected quality and cost.</p>
        {[
          ["Text model", text, setText, "text"],
          ["Image model", image, setImage, "image"],
          ["Video model", video, setVideo, "video"],
          ["Voice model", voice, setVoice, "tts"],
        ].map(([label, value, setter, cap]) => (
          <div className="field" key={String(label)}>
            <label>{label as string}</label>
            <select value={value as string} onChange={(e) => (setter as (v: string) => void)(e.target.value)}>
              {(byCap(cap as string).length ? byCap(cap as string) : models).map((m) => (
                <option key={m.id} value={m.id} disabled={!m.available && m.id !== "auto"}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </div>
        ))}
      </details>
      {error ? <p className="error">{error}</p> : null}
      <button className="btn primary" data-testid="continue-settings" disabled={busy} onClick={save}>
        {busy ? "Saving…" : "Continue"}
      </button>
    </>
  );
}
