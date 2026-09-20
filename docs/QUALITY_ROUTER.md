# Quality router

Phase 12 adds a **capability-driven cinematic quality router**. It classifies each
scene, scores story/motion/dialogue needs, and allocates generation budget. It does
**not** call paid APIs.

## Production classes

`STATIC_CINEMATIC`, `SIMPLE_MOTION`, `REACTION_SHOT`, `DIALOGUE_SHOT`,
`HERO_CINEMATIC`, `PERFORMANCE_SHOT`, `MUSIC_SYNCED_PERFORMANCE`,
`ESTABLISHING_SHOT`, `ARCHIVAL_SHOT`, `TITLE_CARD`, `TRANSITION_SHOT`

Static cinematic stills plus local camera motion remain a first-class outcome.
Video is used when **motion changes the experience**, not because video is
generically “better”.

## Quality profiles

| Profile | Paid video | Image | TTS | Music |
|---|---|---|---|---|
| ECONOMY | almost none | Flare / existing | OpenAI (existing) | Lyria if already used |
| BALANCED | cheap I2V on top beats | Flare; Sunburst for refs | OpenAI | Lyria |
| PREMIUM | more I2V + premium slots | Sunburst refs | Eleven v3 slot | Eleven Music slot |
| MAX_QUALITY | highest configured | Sunburst | Eleven | Eleven Music |
| LOCAL_ONLY | local models only | ComfyUI | Chatterbox | ACE-Step |

`LOCAL_ONLY` never selects a paid implemented model. Missing local servers are
`UNCONFIGURED` / `OFFLINE`, not silently replaced with OpenAI/Google.

## Routing

1. Classify (`beat_id` hints + heuristics).
2. Score dimensions 0–1 (not a single opaque number).
3. Decide whether video is warranted (`wants_video`).
4. Greedy budget: `utility = quality_gain * story_importance / cost`.
5. Fall back along a chain ending in `local-camera`.

Overrides: `must_video`, `must_static`, `must_performance`, `locked_provider`,
`music_sync_required`, `intentional_callback`.

## Providers and fallbacks

Catalog lives in `docprod.quality.catalog`. Pricing is centralized
(`PricingSpec` + existing `providers/pricing.py` known rates). Unknown list
prices stay `UNRESOLVED`. Do not invent dollars.

Unimplemented families (Kling, Seedance, Wan hosted, Runway, Higgsfield
Genjutsu, Eleven, Stable Audio) have adapter boundaries that raise
`UnimplementedProviderError` rather than guessed HTTP payloads.

## Cost planning

`EpisodeCostPlan` lines are tagged `KNOWN` / `ESTIMATED` / `UNRESOLVED`.
Upgrade mode (`upgrade_existing=true`) does **not** re-cost locked images,
TTS, or music already produced.

## Cache

`generic_paid_request_hash` / `video_cache_hash` / `tts_cache_hash` /
`music_cache_hash` / `sfx_cache_hash` include prompts, media hashes, duration,
and settings. `--force-regenerate-paid` remains the only bypass.

Async providers may journal `RemoteJobState` (same states as Veo recovery).

## Local providers

`LOCAL_LLM_BASE_URL`, `LOCAL_IMAGE_BASE_URL`, `LOCAL_VIDEO_BASE_URL`,
`LOCAL_TTS_BASE_URL`, `LOCAL_MUSIC_BASE_URL`. Optional ping only if
`QUALITY_PING_LOCAL=true` (off by default so huge models are not started).

## Dialogue and performance

Default production is **fully automated**:

`SCRIPT → IMAGES → VIDEO → DIALOGUE → MUSIC → SFX → FINAL RENDER`

Human recordings are optional quality inputs, never pipeline dependencies.
`allow_manual_inputs` defaults to **false**. `manual_input_required` on a route
is true only for models like Act-Two/Genjutsu, and those models are **skipped**
unless a driving video already exists, an automatic driver can be generated, or
the user explicitly sets `allow_manual_inputs=true`.

`DIALOGUE_SHOT` fallback (first implemented hop wins):

1. `audio-driven-lipsync` (catalog placeholder; no guessed payload)
2. native-audio video (e.g. Veo Standard catalog)
3. premium I2V with implied speech (Runway Gen-4.5) — hide exact mouth articulation
4. Veo 3.1 Fast / Veo Lite
5. still + narration / local camera

`AudioDrivenDialogueRequest` is distinct from `DrivingPerformanceRequest`.
Act-Two remains implemented for optional use; it is not the default.

Driving-video CLI (`validate-driving-video`, recording guides) stays in the repo
as **optional** tooling.

## Character refs

`CharacterProfile` / `CharacterReferenceSet`. Timeline/video hashes should
include canonical ref hashes.

## CLI

```
quality-plan <project> --profile balanced
quality-plan <project> --all-profiles
provider-status
model-catalog
character-import <project> <character> <image> [image...]
character-status <project>
character-set-primary <project> <character> <reference>
character-contact-sheet <project>
character-migration-plan <project>
migrate-character-stills <project> [--confirm-paid] [--hard-cap-usd 2.0]
```

Dry-run only. There is no command that fires every premium route.

## Phase 12B providers

Implemented (payload + cache + dry-run, **no generation**):

- Runway `gen4.5` I2V (2–10s) and `act_two` (driving video 3–30s)
- ElevenLabs `eleven_v3` TTS, `eleven_text_to_sound_v2` SFX, `/v1/music`

Documented-unimplemented:

- Higgsfield Genjutsu (product page only; no REST schema on docs.higgsfield.ai)
- Higgsfield Kling I2V (console-discovered schemas, not in public index)
- Seedance I2V (official blog shows T2V only)

Chosen non-Google general I2V: **Runway Gen-4.5**.

Duration: Veo Lite is always 8s billed. Gen-4.5 bills `ceil(scene window)` in 2–10s
(not a default 10s). Prefer Gen-4.5 when shorter beats would waste Veo seconds.

Birko V2 reuses stills, Cedar, Lyria, generic SFX. Output names: `birko_kemal_drama_v1.mp4` kept; `birko_kemal_drama_v2.mp4` for a future approved generate.

Locked Balanced V2 video (no Act-Two):

| Beat | Model |
|---|---|
| b06, b09, b13, b14, b18 | Veo 3.1 Lite |
| b07, b15, b17 | Runway Gen-4.5 |

b07 is implied-dialogue I2V (cola, glance, smirk/wink) — not lip-sync.

## Birko canary dry-run (zero spend)

`birko_kemal_drama_canary` — 24 timeline scenes (21 narrative beats + 3 title
cards). Upgrade mode does not re-cost locked images/TTS/music. Veo Lite clips
are 8s at $0.05/s when selected.

| Profile | Static | Simple | Reaction | Dialogue | Hero | Perf | Video s | Prem. video s | TTS | Music | Prem. SFX | Known $ | Unresolved |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ECONOMY | 12 | 2 | 2 | 1 | 2 | 1 | 0 | 0 | gpt-4o-mini-tts | lyria-3.5 | 0 | 0.00 | none |
| BALANCED | 12 | 2 | 2 | 1 | 2 | 1 | 64 | 0 | gpt-4o-mini-tts | lyria-3.5 | 0 | 3.60 | none |
| PREMIUM | 12 | 2 | 2 | 1 | 2 | 1 | 64 | 32 | eleven-v3 | eleven-music | 1 | 1.60 | performance, premium_video, sfx |
| MAX_QUALITY | 12 | 2 | 2 | 1 | 2 | 1 | 64 | 64 | eleven-v3 | eleven-music | 1 | 0.00 | performance, premium_video, sfx |
| LOCAL_ONLY | 12 | 2 | 2 | 1 | 2 | 1 | 48 | 0 | chatterbox | ace-step | 0 | 0.00 | none |

PREMIUM/MAX known dollars drop because some slots have **UNRESOLVED** list prices.
BALANCED V2 is Veo 3.1 Lite only for eight locked beats (**0 Runway / Act-Two calls**).
Hard video cap: `$3.20` (`8 × 8s × $0.05`). Later still-migration spend is separate.

## Custom character references

Canonical identity photos live under `projects/<id>/inputs/characters/<character_id>/`
(`.jpg` `.jpeg` `.png` `.webp`). Generated portraits remain in
`artifacts/visuals/character_refs/` and are never deleted by import. The project
manifest is `artifacts/characters/character_manifest.json`.

Modes: `AUTO_GENERATED` (default, current behavior), `CUSTOM` (user photos are
locked canonical identity), `HYBRID` (custom canonical plus optional derived
views). Downstream providers must call `resolve_character_references(...)` and
must not invent character paths. CUSTOM never falls back to another identity.

V1 episode assets keep their historical generated identities. Importing custom
photos does not reinterpret V1. `execute-birko-v2` stops with
`CUSTOM_CHARACTER_IDENTITY_MISMATCH` if custom identities would mix with old
stills unless an explicit mix allowance is set.

Workflow (zero spend until you approve regeneration):

1. `character-import` custom photos (copies only; originals untouched).
2. `character-status` and `character-contact-sheet` for review.
3. `character-set-primary` if more than one photo exists.
4. `character-migration-plan` to see which stills would need regeneration.
5. `migrate-character-stills <project>` dry-run (writes preflight; **0 paid calls**).
6. `migrate-character-stills <project> --confirm-paid` to generate `artifacts/visuals/custom_v2/`
   (never overwrites V1 stills). OpenAI `images.edit` accepts a list of reference files
   (adapter max 16); one primary identity photo is bound per visible character so
   three-person scenes (b15) keep Birko, Müge, and Kemal.
7. Execute video upgrades from those migrated stills (I2V start frames).

Maple `$0.06698` is the **7-image batch total**, not a per-image price. Birko's 24
image calls were ~`$0.371` attributable usage. Prospective still-migration cost is
**ESTIMATED** from that usage (~`$0.015458`/call observed), not a list price.
Hard image-spend cap for migration: `$1.00`. Later Veo Lite video cap is `$3.20`.

## Future UI (not built)

See ROADMAP: profile selector, per-scene override, cost slider, driving-video
upload, preview-before-spend.
