export const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV || "development";
export const IS_DEV = APP_ENV === "development";
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

export function apiUrl(path: string): string {
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}
