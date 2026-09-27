"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { FriendGroupSituationScreen } from "@/screens/FriendGroupSituation";

export default function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  return (
    <AuthGate>
      <FriendGroupSituationScreen projectId={projectId} />
    </AuthGate>
  );
}
