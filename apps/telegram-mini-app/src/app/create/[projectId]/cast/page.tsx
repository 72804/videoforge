"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { FriendGroupCastScreen } from "@/screens/FriendGroupCast";

export default function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  return (
    <AuthGate>
      <FriendGroupCastScreen projectId={projectId} />
    </AuthGate>
  );
}
