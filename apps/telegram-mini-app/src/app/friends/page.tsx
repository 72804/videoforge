"use client";
import { AuthGate } from "@/components/AuthGate";
import { FriendsScreen } from "@/screens/FriendsScreen";

export default function Page() {
  return (
    <AuthGate>
      <FriendsScreen />
    </AuthGate>
  );
}
