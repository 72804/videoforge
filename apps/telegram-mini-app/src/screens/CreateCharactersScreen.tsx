"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { client } from "@/lib/api";
import { ClientError } from "@/lib/errors";
import type { Character } from "@/lib/types";

export function CreateCharactersScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [rows, setRows] = useState<Character[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [photos, setPhotos] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);

  async function load() {
    const list = await client.characters(projectId);
    setRows(list);
    void Promise.all(
      list
        .filter((row) => row.primary_reference_id)
        .map(async (row) => {
          try {
            const url = await client.authPhoto(row.id);
            setPhotos((cur) => ({ ...cur, [row.id]: url }));
          } catch {
            /* optional photo */
          }
        }),
    );
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof ClientError ? err.message : "Could not load."));
  }, [projectId]);

  async function addCharacter() {
    setBusy(true);
    setError(null);
    setUpload(editingId ? "Saving…" : "Saving character…");
    try {
      if (editingId) {
        await client.patchCharacter(editingId, { name, description });
        if (file) {
          setUpload("Uploading photo…");
          await client.uploadReference(editingId, file);
        }
        setEditingId(null);
      } else {
        const created = await client.createCharacter(projectId, { name, description });
        if (file) {
          setUpload("Uploading photo…");
          await client.uploadReference(created.id, file);
        }
      }
      setName("");
      setDescription("");
      setFile(null);
      setPreview(null);
      setUpload("");
      await load();
    } catch (err) {
      setError(err instanceof ClientError ? err.message : "Could not add character.");
      setUpload("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Characters</h1>
      <p className="lede">Characters are optional. A photo helps keep faces consistent.</p>
      {rows.map((row) => (
        <div className="card" key={row.id} style={{ display: "flex", gap: 12 }}>
          {photos[row.id] ? (
            <img className="photo" src={photos[row.id]} alt={row.name} />
          ) : (
            <div className="photo" aria-hidden />
          )}
          <div>
            <strong>{row.name}</strong>
            <p className="lede" style={{ margin: "4px 0 0" }}>{row.description || "No description"}</p>
            <div className="row" style={{ marginTop: 8 }}>
              <button
                className="btn ghost"
                type="button"
                onClick={() => {
                  setEditingId(row.id);
                  setName(row.name);
                  setDescription(row.description);
                }}
              >
                Edit
              </button>
              <button className="btn ghost" type="button" onClick={() => client.deleteCharacter(row.id).then(load)}>
                Remove
              </button>
            </div>
          </div>
        </div>
      ))}
      {rows.length === 0 ? <p className="lede">No characters yet.</p> : null}
      <div className="card">
        <div className="field">
          <label htmlFor="cname">Name</label>
          <input id="cname" data-testid="char-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Kemal" />
        </div>
        <div className="field">
          <label htmlFor="cdesc">Description</label>
          <textarea id="cdesc" data-testid="char-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Quiet, polite man in his early 30s..." />
        </div>
        <label className="btn ghost" htmlFor="photo">
          {preview ? "Replace photo" : "Add Photo"}
        </label>
        <input
          id="photo"
          className="hidden"
          type="file"
          accept="image/*"
          data-testid="char-photo"
          onChange={(e) => {
            const next = e.target.files?.[0] || null;
            setFile(next);
            setPreview(next ? URL.createObjectURL(next) : null);
          }}
        />
        {preview ? <img className="photo" style={{ marginTop: 12 }} src={preview} alt="Upload preview" /> : null}
        {upload ? <p className="lede">{upload}</p> : null}
        {error ? <p className="error">{error}</p> : null}
        <button className="btn" style={{ marginTop: 12 }} disabled={busy || !name.trim()} onClick={addCharacter} data-testid="add-character">
          {busy ? "Adding…" : editingId ? "Save character" : "+ Add Character"}
        </button>
      </div>
      <div className="row">
        <button className="btn ghost" onClick={() => router.push(`/create/${projectId}/settings`)}>
          Skip characters
        </button>
        <button className="btn primary" data-testid="continue-characters" onClick={() => router.push(`/create/${projectId}/settings`)}>
          Continue
        </button>
      </div>
    </>
  );
}
