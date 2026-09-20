# Telegram product audit (Phase 13A)

Classification of the current `docprod` repository for a Telegram Mini App
product. The generation engine stays. Birko and Maple stay as regression
fixtures. No paid calls are part of this phase.

## GENERIC ENGINE

Reusable without a documentary/drama story:

- Provider adapters (`providers/google_veo.py`, `openai_image.py`, TTS, Whisper, Lyria)
- Paid cache + Veo journal + remote-job recovery
- Cost accounting (`providers/pricing.py`, quality cost planner)
- Quality catalog, router, production classes, capability specs
- Character reference modes `CUSTOM` / `AUTO_GENERATED` / `HYBRID`
- Identity versions and custom_v2 still binding
- FFmpeg renderer, local camera motion, mix/mux, subtitles
- Settings gates: `allow_paid_apis`, `--confirm-paid`
- Hashing, JSON stores, local `ProjectPaths`

## DOCUMENTARY-SPECIFIC

- Research / dossier / citation pipeline (`research/`, `writing/`)
- Wikimedia/archive + Pexels stock
- Semantic documentary scene planner
- Maple warehouse visual families and historical repair helpers
- Default CLI flow around sourced documentary episodes

## DRAMA-SPECIFIC

- `drama/story.py` hardcoded Birko/Kemal/Müge beats
- `plan_custom_drama.py` / `produce_custom_drama.py`
- Character display maps (`DISPLAY = {birko, kemal, muge}`)
- Locked V2 routes in `quality/locked.py`
- Drama uniqueness / timeline helpers

## CANARY-SPECIFIC

- Default CLI `--project birko_kemal_drama_canary`
- Final names `birko_kemal_drama_v1.mp4` / `_v2.mp4`
- Maple canary historical cost totals
- Beat IDs `b06`…`b18` as production keys
- Filesystem project IDs (`^[A-Za-z][A-Za-z0-9_-]{0,62}$`) instead of UUIDs

## PRODUCT-READY (with an adapter layer)

- Scene planning data (`Scene`, `GenerationSpec`) once IDs are decoupled
- Quality profiles as customer `quality_profile`
- Model catalog as the seed of the Telegram catalog
- Custom character stills as identity sources
- Veo I2V + mute/trim into a timeline window
- Cache/journal semantics for async jobs

## NEEDS-GENERALIZATION

| Assumption | Why it blocks a Telegram user |
|---|---|
| `Project.id` is a filesystem slug, not a UUID | Cannot be a Telegram user or opaque product id |
| `target_duration_seconds` required and `> 0` | Blocks `AUTO` duration |
| `Scene.id` must match `scene_<digits>` | Product scenes should be UUIDs with `order_index` |
| Chronological `start`/`end` required on every scene | Editor needs independent duration + reorder |
| Narration required unless visual bridge | Prompt-first videos may be dialogue-only |
| CLI defaults to Birko canary | Arbitrary users cannot share that project |
| Character ids `birko`/`kemal`/`muge` | Arbitrary character names/counts |
| Locked 8-beat Veo plan | Arbitrary scene counts and which shots animate |
| Engine `Project` has no `user_id` | No multi-tenant ownership |
| Local `projects/<id>/` only | Needs object storage later |
| Quote/payment absent | Paid providers can run from CLI flags |
| No initData auth | Client-supplied ids would be forgeable |

## Arbitrary prompt / characters / duration / user

Today a new story is either Maple research or `build_birko_script()`. There is
no first-class `TelegramUser`, no Stars quote, and no scene-local regeneration
API. Phase 13A adds those product entities **beside** the engine. Wiring the
engine to execute a product `GenerationPlan` is Phase 13B–13D.
