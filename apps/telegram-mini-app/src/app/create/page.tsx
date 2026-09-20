"use client";
import { AuthGate } from "@/components/AuthGate";
import { CreatePromptScreen } from "@/screens/CreatePrompt";

export default function Page() {
  return (
    <AuthGate>
      <CreatePromptScreen />
    </AuthGate>
  );
}
