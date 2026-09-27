"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import type { User } from "@/lib/types";

export function FriendsScreen() {
  const [friends, setFriends] = useState<User[]>([]);
  const [username, setUsername] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState("");

  function load() {
    client
      .friends()
      .then(setFriends)
      .catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }

  useEffect(() => {
    load();
  }, []);

  async function send() {
    setError(null);
    setOk("");
    try {
      await client.requestFriend({ username });
      setOk("Request sent.");
      setUsername("");
      load();
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not send request.");
    }
  }

  return (
    <>
      <h1>Friends</h1>
      <p className="lede">VideoForge friends are separate from Telegram contacts.</p>
      <div className="field">
        <label htmlFor="uname">Username</label>
        <input id="uname" data-testid="friend-username" value={username} onChange={(e) => setUsername(e.target.value)} />
      </div>
      <button className="btn primary" data-testid="friend-request" disabled={username.trim().length < 2} onClick={send}>
        Send request
      </button>
      {ok ? <p className="ok">{ok}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <h2>Your people</h2>
      {friends.length === 0 ? <p className="lede">No friends yet.</p> : null}
      {friends.map((friend) => (
        <Link key={friend.id} href={`/profile/${friend.id}`} className="card">
          <strong>{friend.display_name || friend.first_name || friend.username}</strong>
        </Link>
      ))}
    </>
  );
}
