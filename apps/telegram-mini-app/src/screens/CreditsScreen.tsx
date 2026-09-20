"use client";

import { useEffect, useState } from "react";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import type { Usage } from "@/lib/types";

const LABELS: Record<string, string> = {
  PURCHASE: "Simulated credit",
  GENERATION_DEBIT: "Video generation",
  REFUND: "Refund",
  ADJUSTMENT: "Adjustment",
  PROMO_CREDIT: "Promo credit",
};

export function CreditsScreen() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .usage()
      .then(setUsage)
      .catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, []);

  const available = Math.max(0, (usage?.stars_purchased || 0) - (usage?.stars_debited || 0));

  return (
    <>
      <h1>Credits</h1>
      <div className="card">
        <div className="lede">Available</div>
        <div className="stars">{available} ⭐</div>
        <div className="sim">Simulated</div>
      </div>
      <h2>Recent activity</h2>
      {usage?.transactions.length === 0 ? <p className="lede">No generations yet.</p> : null}
      {usage?.transactions.map((txn) => (
        <div className="card" key={txn.id}>
          <strong>{LABELS[txn.type] || txn.type}</strong>
          <p>
            {txn.type === "GENERATION_DEBIT" ? "-" : "+"}
            {txn.stars} ⭐
          </p>
          {txn.simulated ? <div className="sim">Simulated</div> : null}
        </div>
      ))}
      {error ? <p className="error">{error}</p> : null}
    </>
  );
}
