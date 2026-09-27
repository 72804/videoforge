"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { ProfileScreen } from "@/screens/ProfileScreen";

export default function Page({ params }: { params: Promise<{ userId: string }> }) {
  const { userId } = use(params);
  return (
    <AuthGate>
      <ProfileScreen userId={userId} />
    </AuthGate>
  );
}
