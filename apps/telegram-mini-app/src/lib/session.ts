const TOKEN_KEY = "docprod.session.token";
const USER_KEY = "docprod.session.user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function getUserJson(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(USER_KEY);
}

export function saveSession(token: string, user: unknown): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
  window.sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.sessionStorage.removeItem(USER_KEY);
}
