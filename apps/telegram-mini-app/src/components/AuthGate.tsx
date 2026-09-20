"use client";

import { useEffect, useState, type ReactNode } from "react";
import { client } from "@/lib/api";
import { IS_DEV } from "@/lib/config";
import { ClientError } from "@/lib/errors";
import { clearSession, getToken, getUserJson, saveSession } from "@/lib/session";
import { applyTelegramTheme, telegram } from "@/lib/telegram";
import { BottomNav } from "./BottomNav";
import type { User } from "@/lib/types";

export function AuthGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const webapp = telegram();
    webapp?.ready();
    webapp?.expand();
    applyTelegramTheme(webapp);
    const stored = getToken();
    if (stored && getUserJson()) {
      setUser(JSON.parse(getUserJson() || "null"));
      setReady(true);
      return;
    }
    const init = webapp?.initData;
    if (init) {
      client
        .authTelegram(init)
        .then((res) => {
          saveSession(res.token, res.user);
          setUser(res.user);
        })
        .catch((err: ClientError) => setError(err.message))
        .finally(() => setReady(true));
      return;
    }
    setReady(true);
  }, []);

  async function devLogin() {
    setBusy(true);
    setError(null);
    try {
      const res = await client.devAuth(11, "Dev");
      saveSession(res.token, res.user);
      setUser(res.user);
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  if (!ready) {
    return (
      <div className="shell">
        <div className="skeleton" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="shell">
        {IS_DEV ? <div className="dev-banner">Development mode · simulated auth</div> : null}
        <h1>Create cinematic videos</h1>
        <p className="lede">Open this Mini App inside Telegram, or sign in with the development fixture.</p>
        {error ? <p className="error">{error}</p> : null}
        {IS_DEV ? (
          <button className="btn primary" onClick={devLogin} disabled={busy}>
            {busy ? "Signing in…" : "Dev login"}
          </button>
        ) : (
          <p className="lede">This product is designed to open from Telegram.</p>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="shell">
        {IS_DEV ? (
          <div className="dev-banner" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span>Development · simulated Stars · mock generation</span>
            <button
              className="btn ghost"
              style={{ width: "auto", minHeight: 32, padding: "0 12px" }}
              onClick={() => {
                clearSession();
                window.location.reload();
              }}
            >
              Sign out
            </button>
          </div>
        ) : null}
        {children}
      </div>
      <BottomNav />
    </>
  );
}
