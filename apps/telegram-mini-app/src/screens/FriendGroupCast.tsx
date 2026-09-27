"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import type { Character, Persona, User } from "@/lib/types";

const TRAITS = [
  "chaotic",
  "overconfident",
  "quiet",
  "jealous",
  "sarcastic",
  "always hungry",
  "thinks he's the leader",
];

export function FriendGroupCastScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [rows, setRows] = useState<Character[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [friends, setFriends] = useState<User[]>([]);
  const [name, setName] = useState("");
  const [traits, setTraits] = useState<string[]>([]);
  const [role, setRole] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [chars, mine, pal] = await Promise.all([
      client.characters(projectId),
      client.personas(),
      client.friends(),
    ]);
    setRows(chars);
    setPersonas(mine);
    setFriends(pal);
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, [projectId]);

  function toggle(trait: string) {
    setTraits((cur) => (cur.includes(trait) ? cur.filter((t) => t !== trait) : [...cur, trait]));
  }

  async function addStandalone() {
    setBusy(true);
    setError(null);
    try {
      const created = await client.createCharacter(projectId, {
        name,
        personality_traits: traits,
        role_archetype: role,
      });
      if (file) await client.uploadReference(created.id, file);
      setName("");
      setTraits([]);
      setRole("");
      setFile(null);
      await load();
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not add.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Select Cast</h1>
      <p className="lede">Friends or your characters. Photos keep faces consistent.</p>
      {rows.map((row) => (
        <div key={row.id} className="card">
          <strong>{row.name}</strong>
          <div className="lede">{(row.personality_traits || []).join(" · ") || row.description}</div>
        </div>
      ))}
      <h2>My Friends</h2>
      {friends.length === 0 ? <p className="lede">No friends yet.</p> : null}
      {friends.map((friend) => (
        <button
          key={friend.id}
          className="btn ghost"
          type="button"
          disabled={busy}
          onClick={() =>
            client
              .cast(projectId, { friend_user_id: friend.id })
              .then(load)
              .catch((err) => setError(err instanceof ClientError ? err.message : "Cast failed."))
          }
        >
          + {friend.display_name || friend.first_name || friend.username}
        </button>
      ))}
      <h2>My Characters</h2>
      {personas.map((persona) => (
        <button
          key={persona.id}
          className="btn ghost"
          type="button"
          disabled={busy}
          onClick={() =>
            client
              .cast(projectId, { persona_id: persona.id })
              .then(load)
              .catch((err) => setError(err instanceof ClientError ? err.message : "Cast failed."))
          }
        >
          + {persona.name}
        </button>
      ))}
      <h2>New character</h2>
      <div className="field">
        <label htmlFor="cast-name">Name</label>
        <input id="cast-name" data-testid="char-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label>Traits</label>
        <div className="chip-row">
          {TRAITS.map((trait) => (
            <button
              key={trait}
              type="button"
              className={`chip ${traits.includes(trait) ? "on" : ""}`}
              data-testid={`trait-${trait}`}
              onClick={() => toggle(trait)}
            >
              {trait}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="role">Role</label>
        <input id="role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="the leader, the skeptic…" />
      </div>
      <div className="field">
        <label htmlFor="photo">Photo</label>
        <input
          id="photo"
          data-testid="char-photo"
          type="file"
          accept="image/*"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
      </div>
      {error ? <p className="error">{error}</p> : null}
      <button className="btn ghost" data-testid="add-character" disabled={busy || name.trim().length < 1} onClick={addStandalone}>
        + Add Character
      </button>
      <div style={{ height: 12 }} />
      <button className="btn primary" data-testid="continue-cast" onClick={() => router.push(`/create/${projectId}/situation`)}>
        Continue
      </button>
    </>
  );
}
