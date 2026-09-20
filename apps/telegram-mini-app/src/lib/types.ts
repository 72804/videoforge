export type User = {
  id: string;
  telegram_user_id: number;
  username: string | null;
  first_name: string | null;
  language_code: string | null;
};

export type AuthResponse = { token: string; user: User };

export type Project = {
  id: string;
  title: string;
  status: string;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  scene_count: number;
  progress: Record<string, number> | null;
  updated_at: string;
  prompt?: string | null;
  duration_mode?: string | null;
  target_duration_seconds?: number | null;
  aspect_ratio?: string | null;
  language?: string | null;
  quality_profile?: string | null;
  default_image_model?: string | null;
  default_video_model?: string | null;
  default_text_model?: string | null;
  default_voice_model?: string | null;
  style?: string | null;
  active_job_id?: string | null;
  active_job_status?: string | null;
};

export type Character = {
  id: string;
  project_id: string;
  name: string;
  description: string;
  locked_identity: boolean;
  primary_reference_id: string | null;
};

export type Model = {
  id: string;
  display_name: string;
  capabilities: string[];
  quality_tier: string;
  available: boolean;
};

export type PlanLine = {
  type: string;
  model: string;
  quantity: number;
  estimated_provider_usd: number;
  customer_stars: number;
};

export type Plan = {
  plan_id: string;
  plan_hash: string;
  scene_count: number;
  duration_seconds: number;
  image_generations: number;
  video_generations: number;
  tts: number;
  music: number;
  customer_star_estimate: number;
  line_items: PlanLine[];
};

export type Quote = {
  quote_id: string;
  plan_hash: string;
  stars: number;
  expires_at: string;
  status: string;
  simulated: boolean;
};

export type WorkUnit = { type: string; completed: number; total: number };

export type Job = {
  job_id: string;
  project_id: string;
  status: string;
  work_units: WorkUnit[];
  current_stage: string;
  failure_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type Scene = {
  id: string;
  order_index: number;
  duration_seconds: number;
  characters: string[];
  status: string;
  production_class: string;
  image_model: string;
  video_model: string;
  locked: boolean;
  version_number: number;
  estimated_regeneration_stars: number;
  image_asset_version_id: string | null;
  video_asset_version_id: string | null;
  visual_prompt: string;
  motion_prompt: string;
};

export type SceneVersion = {
  id: string;
  scene_id: string;
  visual_prompt: string;
  motion_prompt: string;
  duration_seconds: number;
  image_model: string;
  video_model: string;
  created_at: string;
  image_asset_version_id?: string | null;
  video_asset_version_id?: string | null;
};

export type Usage = {
  transactions: {
    id: string;
    type: string;
    stars: number;
    simulated: boolean;
    created_at: string;
    project_id: string | null;
  }[];
  stars_debited: number;
  stars_purchased: number;
};

export type ApiError = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};
