"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { CreateCharactersScreen } from "@/screens/CreateCharactersScreen";

export default function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  return (
    <AuthGate>
      <CreateCharactersScreen projectId={projectId} />
    </AuthGate>
  );
}
