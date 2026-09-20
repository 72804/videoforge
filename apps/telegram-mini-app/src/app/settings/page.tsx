"use client";
import { AuthGate } from "@/components/AuthGate";
import { SettingsScreen } from "@/screens/SettingsScreen";

export default function Page() {
  return (
    <AuthGate>
      <SettingsScreen />
    </AuthGate>
  );
}
