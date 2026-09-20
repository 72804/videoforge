"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { SceneEditorScreen } from "@/screens/SceneEditor";

export default function Page({
  params,
}: {
  params: Promise<{ id: string; sceneId: string }>;
}) {
  const { id, sceneId } = use(params);
  return (
    <AuthGate>
      <SceneEditorScreen projectId={id} sceneId={sceneId} />
    </AuthGate>
  );
}
