export type Appearance = "dark" | "light" | "system";

const KEY = "docprod.appearance";

export function getAppearance(): Appearance {
  if (typeof window === "undefined") return "dark";
  const raw = window.localStorage.getItem(KEY);
  if (raw === "light" || raw === "system" || raw === "dark") return raw;
  return "dark";
}

export function setAppearance(value: Appearance): void {
  window.localStorage.setItem(KEY, value);
  applyAppearance();
}

export function resolvedTheme(appearance: Appearance, prefersDark = true): "dark" | "light" {
  if (appearance === "light") return "light";
  if (appearance === "system") return prefersDark ? "dark" : "light";
  return "dark";
}

export function applyAppearance(): "dark" | "light" {
  if (typeof document === "undefined") return "dark";
  const prefersDark =
    typeof window === "undefined" ||
    !window.matchMedia ||
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = resolvedTheme(getAppearance(), prefersDark);
  document.documentElement.dataset.theme = theme;
  return theme;
}
