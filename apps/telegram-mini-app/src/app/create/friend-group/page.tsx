"use client";
import { AuthGate } from "@/components/AuthGate";
import { FriendGroupStartScreen } from "@/screens/FriendGroupStart";

export default function Page() {
  return (
    <AuthGate>
      <FriendGroupStartScreen />
    </AuthGate>
  );
}
