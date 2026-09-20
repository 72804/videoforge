"use client";
import { AuthGate } from "@/components/AuthGate";
import { ProjectsScreen } from "@/screens/ProjectsScreen";

export default function Page() {
  return (
    <AuthGate>
      <ProjectsScreen />
    </AuthGate>
  );
}
