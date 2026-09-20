export const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV || "development";
export const IS_DEV = APP_ENV === "development";
export const API_BASE = resolveApiBase(APP_ENV, process.env.NEXT_PUBLIC_API_BASE_URL || "");

export function resolveApiBase(appEnv: string, rawBase: string): string {
  const base = rawBase.replace(/\/$/, "");
  if (appEnv !== "production") return base;
  if (!base || base === "/" || base === ".") return "";
  if (/localhost|127\.0\.0\.1/i.test(base) || !base.startsWith("https://")) {
    throw new Error(
      "Production Mini App requires same-origin API calls, or NEXT_PUBLIC_API_BASE_URL as a public https URL (not localhost).",
    );
  }
  if (/\/api(\/v1)?$/i.test(base)) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL must be the site origin only (no /api or /api/v1 suffix).",
    );
  }
  return base;
}

export function apiUrl(path: string): string {
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}
