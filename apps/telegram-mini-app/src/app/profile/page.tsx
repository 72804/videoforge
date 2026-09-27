"use client";
import { AuthGate } from "@/components/AuthGate";
import { ProfileScreen } from "@/screens/ProfileScreen";

export default function Page() {
  return (
    <AuthGate>
      <ProfileScreen />
    </AuthGate>
  );
}
