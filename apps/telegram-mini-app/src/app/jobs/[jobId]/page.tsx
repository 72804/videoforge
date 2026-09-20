"use client";
import { use } from "react";
import { AuthGate } from "@/components/AuthGate";
import { GenerateScreen } from "@/screens/GenerateScreen";

export default function Page({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = use(params);
  return (
    <AuthGate>
      <GenerateScreen jobId={jobId} />
    </AuthGate>
  );
}
