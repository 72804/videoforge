# Object storage

Placeholder bytes are not enough for real generation. Neon stores keys and metadata only.

## Choice: Cloudflare R2

S3-compatible, no egress fees to the internet, cheap Class A/B ops. Fits signed playback from the Mini App without proxying MP4s through Vercel.

AWS S3 is a drop-in via the same `S3CompatibleStorage` if R2 is unavailable.

## Backend

`docprod.product.s3_storage.S3CompatibleStorage` implements `StorageBackend`:

- `put_bytes` / `get_bytes` / `exists` / `delete`
- `signed_url` (SigV4, private objects)
- `metadata` (content type, size, checksum)

Credentials stay on API + worker processes. The browser only receives a time-limited GET URL (`GET /api/v1/media/{asset_version_id}` → 302).

## Keys

```text
projects/{project_id}/characters/{id}/ref/{version}
projects/{project_id}/scenes/{scene_id}/image/{version}
projects/{project_id}/scenes/{scene_id}/video/{version}
projects/{project_id}/audio/{kind}/{version}
projects/{project_id}/renders/{render_id}.mp4
projects/{project_id}/thumbs/{version}
```

## Database

`asset_versions` stores `storage_key`, `mime`, `byte_size`, `sha256`, provider/model, dimensions/duration. `renders.asset_version_id` points at the playable final.

## Retention (design only — no auto-delete yet)

| Category | Examples | Policy |
| --- | --- | --- |
| Permanent customer asset | final MP4, paid character refs | keep |
| Versioned editable asset | scene stills/clips, script versions | keep while project exists |
| Temporary intermediate | FFmpeg work files, provider scratch | expire later (30 days candidate) |

Do not automatically delete customer finals.

## CORS

Allow `https://videoforge-dusky.vercel.app` GET on the R2 bucket (or custom domain) so `<video src>` after redirect works.
