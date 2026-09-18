# Documentary Video Pipeline (`docprod`)

Local-first CLI for an AI-assisted documentary YouTube production system.

**Current phase: 3** — deterministic scene planner plus an FFmpeg **development
placeholder preview renderer**. This is for inspecting pacing/cuts/captions, not
final picture generation.

## Purpose

Eventually:

`TOPIC → research → outline → script → TTS → timestamps → scene planner → visuals →
subtitles → sound → timeline → render → titles/thumbnails`

Today the planner writes `05_scenes.json`. `render-preview` turns that plan into a
watchable 720p MP4 using FFmpeg-native placeholder cards, motion approximations,
burned-in captions, and silent AAC audio. It does **not** generate AI images, AI
video, stock, archive, or paid TTS.

## Setup

Requires **Python 3.12** (via [uv](https://docs.astral.sh/uv/)) and **FFmpeg / ffprobe**
with **libass** (`subtitles` filter) and **drawtext**. Homebrew’s default `ffmpeg`
formula does **not** include those; install `ffmpeg-full` (keg-only). `docprod`
prefers `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` automatically, or set
`DOCPROD_FFMPEG`.

```bash
uv sync
uv run docprod doctor
```

Copy `.env.example` to `.env` only if you need to change local defaults.
Do not set `ALLOW_PAID_APIS=true` unless you intentionally allow billed calls.

## Commands

```bash
uv run docprod doctor
uv run pytest
uv run docprod init-project demo --title "Demo" --language tr --duration 60 --seed 42
uv run docprod make-narration-demo demo --language tr
uv run docprod plan-scenes demo
uv run docprod inspect-scenes demo
uv run docprod render-preview demo --workers 2
uv run docprod inspect-render demo
uv run docprod render-scene demo scene_0004
uv run docprod status demo
```

`plan-scenes` and `render-preview` are idempotent when inputs are unchanged.
`render-preview --force` re-runs the stage but reuses valid scene-segment caches.
`render-preview --no-cache` re-encodes every segment.

## Project folder structure

```
projects/<project_id>/
  project.json
  job.json
  stages/
    04_narration.json
    05_scenes.json
  artifacts/render/preview/
    captions.srt
    captions.ass
    segments/scene_0001.mp4
    concat.txt
    documentary_preview.mp4
    render_manifest.json
```

## Paid API safety

`ALLOW_PAID_APIS` defaults to **false**. Tests do not require API keys.

## Testing

```bash
uv run pytest
uv run ruff check .
```

## Intentionally not implemented yet

- Research / source dossier / LLM script generation
- Real TTS and word-level alignment
- Image, stock, archive, or video generation
- Final 1080p/4K export profiles
- Music, SFX
- Thumbnails, titles, UI
- Databases, queues, Docker, FastAPI
