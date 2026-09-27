"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import type { Project, User } from "@/lib/types";

export function ProfileScreen({ userId }: { userId?: string }) {
  const [me, setMe] = useState<User | null>(null);
  const [profile, setProfile] = useState<User | null>(null);
  const [mine, setMine] = useState<Project[]>([]);
  const [withMe, setWithMe] = useState<Project[]>([]);
  const [bio, setBio] = useState("");
  const [castOk, setCastOk] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .me()
      .then(async (self) => {
        setMe(self);
        const id = userId || self.id;
        const person = userId ? await client.profile(id) : self;
        setProfile(person);
        setBio(person.bio || "");
        setCastOk(Boolean(person.allow_friends_to_cast_me));
        const [own, tagged] = await Promise.all([
          client.profileVideos(id, false),
          client.profileVideos(id, true),
        ]);
        setMine(own);
        setWithMe(tagged);
      })
      .catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, [userId]);

  const self = me && profile && me.id === profile.id;

  async function save() {
    if (!self) return;
    try {
      await client.patchMe({ bio, allow_friends_to_cast_me: castOk });
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not save.");
    }
  }

  return (
    <>
      <h1>{profile?.display_name || profile?.first_name || "Profile"}</h1>
      <p className="lede">{profile?.username ? `@${profile.username}` : "VideoForge profile"}</p>
      {error ? <p className="error">{error}</p> : null}
      {self ? (
        <>
          <div className="field">
            <label htmlFor="bio">Bio</label>
            <textarea id="bio" value={bio} onChange={(e) => setBio(e.target.value)} />
          </div>
          <label className="lede">
            <input type="checkbox" checked={castOk} onChange={(e) => setCastOk(e.target.checked)} /> Allow friends to
            cast me
          </label>
          <button className="btn primary" onClick={save}>
            Save
          </button>
          <Link href="/settings" className="btn ghost" style={{ marginTop: 10 }}>
            App settings
          </Link>
        </>
      ) : null}
      <h2>My Videos</h2>
      {mine.length === 0 ? <p className="lede">Nothing visible.</p> : null}
      {mine.map((p) => (
        <Link key={p.id} href={`/projects/${p.id}`} className="card">
          {p.title}
        </Link>
      ))}
      <h2>Videos With Me</h2>
      {withMe.length === 0 ? <p className="lede">No tagged videos you can see.</p> : null}
      {withMe.map((p) => (
        <Link key={p.id} href={`/projects/${p.id}`} className="card">
          {p.title}
        </Link>
      ))}
    </>
  );
}
