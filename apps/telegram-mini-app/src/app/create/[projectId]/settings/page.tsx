"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { CreateSettingsScreen } from "@/screens/CreateSettings";

export default function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  return (
    <AuthGate>
      <CreateSettingsScreen projectId={projectId} />
    </AuthGate>
  );
}
