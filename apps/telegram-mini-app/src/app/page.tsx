"use client";
import { AuthGate } from "@/components/AuthGate";
import { HomeScreen } from "@/screens/HomeScreen";

export default function Page() {
  return (
    <AuthGate>
      <HomeScreen />
    </AuthGate>
  );
}
