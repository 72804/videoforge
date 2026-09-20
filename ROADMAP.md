# Docprod roadmap

This document records product direction that is **not** in the current pipeline.

Phase 8 implements sourced web research, a citation dossier, and a Turkish documentary script.
Phase 9 compiles that script into a semantic scene plan. It does **not** generate assets
and does **not** implement the creator-control surfaces below.

---

## LATE-STAGE CREATOR CONTROLS

**Status: DEFERRED / NOT IMPLEMENTED**

Do not treat any of these as available in Phase 8.

### 1. Prompt-driven custom content creation

Deferred:

- generate a new scene from a prompt
- change an existing visual using a prompt
- custom narration prompt
- custom document/map graphic prompt
- custom SFX/music prompt
- arbitrary user-provided creative instructions

The research/script models use fixed, versioned instructions. There is no free-form creative prompt console.

### 2. Scene-by-scene timeline editor

Deferred:

- timeline UI
- inspect scenes in an editor
- reorder
- split
- merge
- trim/extend
- replace visual
- replace narration
- regenerate one scene
- disable/remove scene
- lock approved scene
- upload a manual replacement asset

Phase 8 stops after research and script review artifacts. It does not scene-plan or edit a timeline.

### 3. Model/provider chooser

Deferred:

- research model picker
- writing model picker
- image model picker
- video model picker
- TTS model picker
- transcription/alignment model picker
- global defaults UI
- per-project overrides UI
- per-scene overrides

Phase 8 exposes **config defaults only** (`RESEARCH_MODEL`, `DOSSIER_MODEL`, `WRITER_MODEL`, `VIDEO_MODEL`, `MUSIC_MODEL`, and existing image/TTS settings). There is no chooser UI. Google media adapters remain provider-neutral config, not a UI picker.

### 4. Versioning / manual override safety

Deferred:

- scene revisions
- undo/revert
- preserve approved assets
- compare generations
- never overwrite locked human decisions

Paid stages may reuse a cached successful result when the request hash is unchanged. That is not a revision history or lock system.

---

## PHASE 12 — QUALITY ROUTER / CINEMATIC ENGINE

**Status: PLANNING IMPLEMENTED / PRODUCTION EXECUTION NOT ENABLED**

Code, tests, and dry-run cost plans exist. Paid multi-model production is **not**
wired to a one-shot execute command.

Implemented:

- production classes and quality profiles (`ECONOMY` … `LOCAL_ONLY`)
- capability catalog + dry-run cost planner
- greedy budget allocation
- dialogue / performance request objects + unimplemented adapters
- provider-status / model-catalog / quality-plan CLI

### Deferred creator UI

- quality-profile selector
- per-scene provider override
- model picker
- scene lock / regen scene
- performance driving-video upload
- audio provider override
- cost slider / budget control
- preview-before-spend

Do not treat these as available in the current CLI beyond dry-run reports.

