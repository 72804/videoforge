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

`DialogueShotRequest` and `PerformanceShotRequest` are provider-neutral.
Music-synced beats must not route to ordinary text-to-video unless the model
lists performance/driving capabilities.

Driving video must not be a celebrity likeness.

## Character refs

`CharacterProfile` / `CharacterReferenceSet`. Timeline/video hashes should
include canonical ref hashes.

## CLI

```
quality-plan <project> --profile balanced
quality-plan <project> --all-profiles
provider-status
model-catalog
```

Dry-run only. There is no command that fires every premium route.

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

PREMIUM/MAX known dollars drop because Veo Fast/Standard, Eleven, and SFX
slots have **UNRESOLVED** list prices; the planner never invents a dollar
value. BALANCED is the spendable plan: eight Veo Lite clips on b06, b07, b09,
b13, b14, b15, b17, b18.

## Future UI (not built)

See ROADMAP: profile selector, per-scene override, cost slider, driving-video
upload, preview-before-spend.
