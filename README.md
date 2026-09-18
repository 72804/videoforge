# Documentary Video Pipeline (`docprod`)

Local-first CLI for an AI-assisted documentary YouTube production system.

**Current phase: 2** — deterministic scene planner on top of the Phase 0/1 foundation.
No research, TTS, image/video generation, or FFmpeg rendering yet.

## Purpose

Eventually:

`TOPIC → research → outline → script → TTS → timestamps → scene planner → visuals →
subtitles → sound → timeline → render → titles/thumbnails`

The scene planner converts a timed `NarrationScript` into a `ScenePlan` using
documentary production rules (2–6s beats, cheap strategies first, AI video budget).

## Setup

Requires **Python 3.12** (via [uv](https://docs.astral.sh/uv/)) and **FFmpeg / ffprobe**
on `PATH` (Homebrew `ffmpeg` on macOS).

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
uv run docprod status demo
uv run docprod show-project demo
uv run docprod export-schemas tmp/schemas
```

`plan-scenes` is idempotent: a second run with the same narration, seed, and profile
skips. Use `--force` to replan.

Phase 1 fixture (hand-authored scenes, not the planner):

```bash
uv run docprod make-demo demo
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
    04_narration.json   # timed narration (make-narration-demo)
    05_scenes.json      # ScenePlan (plan-scenes or make-demo)
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
require API keys. `LOG_LEVEL` is applied via the standard-library logger.

## Testing

```bash
uv run pytest
```

Tests are local and network-free.

## Intentionally not implemented yet

- Research / source dossier / LLM script generation
- Real TTS and word-level alignment
- Image, stock, archive, or video generation
- FFmpeg timeline assembly / final render
- Music, SFX, subtitles burn-in
- Thumbnails, titles, UI
- Databases, queues, Docker, FastAPI
