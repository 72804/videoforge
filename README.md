# Documentary Video Pipeline (`docprod`)

Local-first CLI for an AI-assisted documentary YouTube production system.

**Current phase: 0 + 1** — repository/toolchain bootstrap and typed domain foundation.
No research, TTS, image/video generation, or FFmpeg rendering yet.

## Purpose

Eventually:

`TOPIC → research → outline → script → TTS → timestamps → scene planner → visuals →
subtitles → sound → timeline → render → titles/thumbnails`

The scene planner (not implemented yet) will choose the cheapest suitable visual
strategy per beat. This repo currently defines the schemas, project layout, and
safety gates that later stages will use.

## Setup

Requires **Python 3.12** (via [uv](https://docs.astral.sh/uv/)) and **FFmpeg / ffprobe**
on `PATH` (Homebrew `ffmpeg` on macOS).

```bash
uv sync
uv run docprod doctor
```

Copy `.env.example` to `.env` only if you need to change local defaults.
Do not set `ALLOW_PAID_APIS=true` unless you intentionally allow billed calls.
Phase 1 never calls paid APIs.

## Commands

```bash
uv run docprod doctor
uv run pytest
uv run docprod init-project demo --title "Demo" --language tr --duration 30
uv run docprod make-demo demo
uv run docprod status demo
uv run docprod show-project demo
uv run docprod export-schemas tmp/schemas
```

Lint:

```bash
uv run ruff check .
```

## Project folder structure

```
projects/<project_id>/
  project.json
  job.json
  stages/
    05_scenes.json      # written by make-demo
  artifacts/
    audio/
    visuals/
    subtitles/
    render/
  logs/
```

## Paid API safety

`ALLOW_PAID_APIS` defaults to **false**. Future paid adapters must call
`require_paid_apis_enabled(provider_name)` before any network call. Tests do not
require API keys.

## Testing

```bash
uv run pytest
```

Tests are local and network-free.

## Intentionally not implemented yet

- Research / source dossier / LLM script generation
- Real TTS and word-level alignment
- Image, stock, archive, or video generation
- Scene planner policy (2–6s beats)
- FFmpeg timeline assembly / final render
- Music, SFX, subtitles burn-in
- Thumbnails, titles, UI
- Databases, queues, Docker, FastAPI
