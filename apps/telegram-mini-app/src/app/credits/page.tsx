"use client";
import { AuthGate } from "@/components/AuthGate";
import { CreditsScreen } from "@/screens/CreditsScreen";

export default function Page() {
  return (
    <AuthGate>
      <CreditsScreen />
    </AuthGate>
  );
}
