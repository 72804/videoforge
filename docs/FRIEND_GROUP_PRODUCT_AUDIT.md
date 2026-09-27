# Friend Group product audit (Phase 17)

Read-only survey of overlaps before the friend-group MVP. No paid calls.

## Existing product surface

- **Telegram Mini App** (`apps/telegram-mini-app`): prompt → characters → settings → quote → mock generate.
- **Users**: `TelegramUser` is Telegram id + name. No profile, friends, visibility, or consent.
- **Projects**: owner-only via `_require_project`. `ContentType` includes `custom_story` but no `friend_group`.
- **Characters**: project-scoped `Character` + `CharacterReference`. Name/description/lock/photo only. No traits, voices, linked users, or library personas.
- **Engine planning**: `engine_bridge.build_engine_spec` plus Phase 12 `quality/router.py` + `quality/profiles.py`. Canary still hardcodes `FIRST_CANARY_PROVIDERS` (Luna / Flare / Veo Lite / mini-tts).
- **Real jobs**: Telegram default `GENERATION_MODE=mock`. `RealGenerationWorker` is `LIVE_DISABLED` except local canary.

## Quality router vs product planning

| Layer | Role today |
| --- | --- |
| `quality/catalog.py` | Model registry |
| `quality/profiles.py` | Economy / Balanced / Premium / Max / Local Only |
| `quality/router.py` | Per-shot video + still routing |
| `engine_bridge` | Product plan freeze; script/TTS/music IDs from canary map |
| `FIRST_CANARY_PROVIDERS` | Phase 16B local canary only |

Phase 17 unifies **customer** planning on catalog + profiles. Canary map stays for `--stage` compatibility and is not the product default.

## Providers already implemented (HTTP adapters exist)

- OpenAI images (`gpt-image-2.5-flare` default; model is configurable — Sunburst needs no second adapter)
- OpenAI TTS (`gpt-4o-mini-tts`, single voice `cedar` in Settings)
- Google Veo Lite I2V
- Runway Gen-4.5 and Act-Two
- Eleven v3 TTS, Eleven music, Eleven SFX
- Google Lyria
- Whisper alignment (documentary renderer)

Not wired into the Telegram generate path: Eleven, Lyria mix, multi-voice, Sunburst policy, GPT-6.

## Birko / Maple

- Locked drama engine: `drama/story.py`, `pipeline/produce_custom_drama.py`, `execute_birko_v2.py`
- Canonical refs: `projects/birko_kemal_drama_canary/artifacts/visuals/character_refs/ref_{birko,kemal,muge}.jpg` (do not overwrite)
- Maple is documentary, not the friend-group wedge

Phase 17 imports Birko/Kemal/Müge as **locked personas** pointing at those paths. Episode 2 is a **DRAFT project** on the same friend-group models. No second Birko generator.

## Privacy / auth today

- Session JWT from Telegram initData
- Project access = owner only
- No PUBLIC/FRIENDS visibility, no “videos with me”, no cast consent

## Local canary

`projects/videoforge_local_canary` remains artifacts + resume state. Do not execute. Not the product-development path.

## Gaps this phase fills

Profiles, friendships, visibility, cast consent, library personas vs project snapshots, voice profiles, multi-speaker story spec, GPT-6 catalog + routing, Sunburst/Flare policy, audio mix + burn-in subtitle contract, series continuity, Mini App friend-group UX.
