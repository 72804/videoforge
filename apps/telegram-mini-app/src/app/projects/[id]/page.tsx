"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { ProjectScreen } from "@/screens/ProjectScreen";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <AuthGate>
      <ProjectScreen projectId={id} />
    </AuthGate>
  );
}
