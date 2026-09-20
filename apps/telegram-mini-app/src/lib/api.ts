import { apiUrl } from "./config";
import { ClientError, networkMessage } from "./errors";
import { getToken } from "./session";
import type {
  AuthResponse,
  Character,
  Job,
  Model,
  Plan,
  Project,
  Quote,
  Scene,
  SceneVersion,
  Usage,
  User,
} from "./types";

function requestId(): string {
  return crypto.randomUUID();
}

async function parseError(response: Response): Promise<ClientError> {
  try {
    const body = await response.json();
    const err = body?.error || body;
    return new ClientError({
      code: err.code || "HTTP",
      message: err.message || response.statusText,
      details: err.details,
    });
  } catch {
    return new ClientError({ code: "HTTP", message: response.statusText });
  }
}

export async function api<T>(
  path: string,
  init: RequestInit & { json?: unknown; form?: FormData; idempotency?: string } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Request-ID", requestId());
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.idempotency) headers.set("Idempotency-Key", init.idempotency);
  let body: BodyInit | undefined = init.body as BodyInit | undefined;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  if (init.form) body = init.form;
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { ...init, headers, body });
  } catch {
    throw new ClientError({ code: "NETWORK", message: networkMessage() });
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return (await response.json()) as T;
  return (await response.arrayBuffer()) as T;
}

export const client = {
  authTelegram: (init_data: string) =>
    api<AuthResponse>("/api/v1/auth/telegram", { method: "POST", json: { init_data } }),
  devAuth: (telegram_user_id = 11, first_name = "Dev") =>
    api<AuthResponse>("/api/v1/dev/auth", {
      method: "POST",
      json: { telegram_user_id, first_name },
    }),
  models: () => api<Model[]>("/api/v1/models"),
  usage: () => api<Usage>("/api/v1/usage"),
  projects: () => api<Project[]>("/api/v1/projects"),
  project: (id: string) => api<Project>(`/api/v1/projects/${id}`),
  createProject: (body: Record<string, unknown>) =>
    api<Project>("/api/v1/projects", { method: "POST", json: body }),
  patchProject: (id: string, body: Record<string, unknown>) =>
    api<Project>(`/api/v1/projects/${id}`, { method: "PATCH", json: body }),
  characters: (projectId: string) =>
    api<Character[]>(`/api/v1/projects/${projectId}/characters`),
  createCharacter: (projectId: string, body: { name: string; description?: string }) =>
    api<Character>(`/api/v1/projects/${projectId}/characters`, { method: "POST", json: body }),
  patchCharacter: (id: string, body: Record<string, unknown>) =>
    api<Character>(`/api/v1/characters/${id}`, { method: "PATCH", json: body }),
  deleteCharacter: (id: string) =>
    api<{ status: string }>(`/api/v1/characters/${id}`, { method: "DELETE" }),
  uploadReference: (characterId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("role", "primary");
    form.append("make_primary", "true");
    return api(`/api/v1/characters/${characterId}/references`, { method: "POST", form });
  },
  characterPhoto: (id: string) => `/api/v1/characters/${id}/photo`,
  plan: (projectId: string, kind = "full_project", scene_id?: string) =>
    api<Plan>(`/api/v1/projects/${projectId}/plan`, {
      method: "POST",
      json: { kind, scene_id: scene_id ?? null },
    }),
  latestQuote: (projectId: string) =>
    api<{ quote: Quote; plan: Plan; payment_status: string }>(
      `/api/v1/projects/${projectId}/latest-quote`,
    ),
  quote: (projectId: string, plan_id: string) =>
    api<Quote>(`/api/v1/projects/${projectId}/quote`, { method: "POST", json: { plan_id } }),
  confirmPayment: (quoteId: string) =>
    api<Quote>(`/api/v1/dev/payments/${quoteId}/confirm`, {
      method: "POST",
      idempotency: `pay-${quoteId}`,
    }),
  createInvoice: (quoteId: string) =>
    api<{ invoice_url: string; stars: number; currency: string }>(
      `/api/v1/quotes/${quoteId}/telegram-invoice`,
      { method: "POST" },
    ),
  paymentStatus: (quoteId: string) =>
    api<{ quote_id: string; status: string }>(`/api/v1/quotes/${quoteId}/payment-status`),
  generate: (projectId: string, quote_id: string, kind = "full_project", scene_id?: string) =>
    api<{ job_id: string; status: string }>(`/api/v1/projects/${projectId}/generate`, {
      method: "POST",
      json: { quote_id, kind, scene_id: scene_id ?? null },
      idempotency: `gen-${quote_id}-${kind}-${scene_id ?? "all"}`,
    }),
  job: (id: string) => api<Job>(`/api/v1/jobs/${id}`),
  runWorker: (jobId: string) =>
    api<{ job_id: string; status: string }>(`/api/v1/dev/jobs/${jobId}/run`, { method: "POST" }),
  scenes: (projectId: string) => api<Scene[]>(`/api/v1/projects/${projectId}/scenes`),
  scene: (id: string) =>
    api<{
      scene: { id: string; locked: boolean; order_index: number };
      active_version: SceneVersion;
      versions: SceneVersion[];
    }>(`/api/v1/scenes/${id}`),
  patchScene: (id: string, body: Record<string, unknown>) =>
    api<{ scene_version: SceneVersion; invalidated: string[] }>(`/api/v1/scenes/${id}`, {
      method: "PATCH",
      json: body,
    }),
  lockScene: (id: string) => api(`/api/v1/scenes/${id}/lock`, { method: "POST" }),
  unlockScene: (id: string) => api(`/api/v1/scenes/${id}/unlock`, { method: "POST" }),
  versions: (id: string) =>
    api<{ active_version_id: string; versions: SceneVersion[] }>(`/api/v1/scenes/${id}/versions`),
  restore: (sceneId: string, versionId: string) =>
    api(`/api/v1/scenes/${sceneId}/restore/${versionId}`, { method: "POST" }),
  reorder: (projectId: string, scene_ids: string[]) =>
    api(`/api/v1/projects/${projectId}/scenes/reorder`, { method: "POST", json: { scene_ids } }),
  regenImage: (sceneId: string, quote_id: string) =>
    api<{ job_id: string; status: string }>(`/api/v1/scenes/${sceneId}/regenerate-image`, {
      method: "POST",
      json: { quote_id, kind: "scene_image", scene_id: sceneId },
      idempotency: `img-${sceneId}-${quote_id}`,
    }),
  regenVideo: (sceneId: string, quote_id: string) =>
    api<{ job_id: string; status: string }>(`/api/v1/scenes/${sceneId}/regenerate-video`, {
      method: "POST",
      json: { quote_id, kind: "scene_video", scene_id: sceneId },
      idempotency: `vid-${sceneId}-${quote_id}`,
    }),
  render: (projectId: string, quote_id: string) =>
    api<{ job_id: string; status: string }>(`/api/v1/projects/${projectId}/render`, {
      method: "POST",
      json: { quote_id, kind: "render" },
      idempotency: `render-${projectId}-${quote_id}`,
    }),
  media: async (assetVersionId: string): Promise<string> => {
    const token = getToken();
    const response = await fetch(apiUrl(`/api/v1/media/${assetVersionId}`), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw await parseError(response);
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  },
  authPhoto: async (characterId: string): Promise<string> => {
    const token = getToken();
    const response = await fetch(apiUrl(`/api/v1/characters/${characterId}/photo`), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error("no photo");
    return URL.createObjectURL(await response.blob());
  },
};

export type { User };
