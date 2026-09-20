export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m === 0) return `${s}s`;
  return `~${m}m ${String(s).padStart(2, "0")}s`;
}

export function statusLabel(status: string): string {
  const map: Record<string, string> = {
    draft: "Draft",
    planned: "Draft",
    quoted: "Waiting for payment",
    awaiting_payment: "Waiting for payment",
    generating: "Generating",
    partial: "Ready",
    ready: "Ready",
    failed: "Failed",
    archived: "Archived",
  };
  return map[status] || status;
}

export function lineItemLabel(type: string): string {
  const map: Record<string, string> = {
    script: "Story & planning",
    still: "Images",
    video: "Video animation",
    tts: "Voice",
    music: "Music",
    render: "Final render",
    alignment: "Timing",
    sfx: "Sound",
  };
  return map[type] || type;
}

export function invalidationMessage(flags: string[]): string {
  if (flags.includes("video") && flags.includes("image")) {
    return "Image and video need to be regenerated because this scene changed.";
  }
  if (flags.includes("video")) {
    return "Video needs to be regenerated because the scene image or motion changed.";
  }
  if (flags.includes("image")) {
    return "The scene image needs to be regenerated.";
  }
  if (flags.includes("render")) {
    return "The final video will need a new render.";
  }
  return "Saved.";
}

export function stageLabel(unit: string): string {
  const map: Record<string, string> = {
    script: "Story",
    images: "Creating images",
    video: "Animating scenes",
    audio: "Voice & music",
    render: "Final render",
  };
  return map[unit] || unit;
}

export function durationPayload(choice: string, custom: string): {
  duration_mode: "AUTO" | "FIXED";
  target_duration_seconds: number | null;
} {
  if (choice === "AUTO") return { duration_mode: "AUTO", target_duration_seconds: null };
  const seconds = choice === "custom" ? Number(custom) : Number(choice);
  return { duration_mode: "FIXED", target_duration_seconds: seconds };
}

export const SURPRISES = [
  "Create a dark comedy about two roommates who discover a mysterious box in their apartment.",
  "A quiet librarian finds a letter that was never meant to be opened.",
  "Two street musicians accidentally start a city-wide rumor.",
];
