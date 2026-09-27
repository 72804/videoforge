# Frontier creative stack (Phase 17B)

VideoForge routes **creative intent → task → capabilities → registry → eligible models → policy → execution**. There is no single best model per episode.

## Task specialists

| Task | Typical specialists |
| --- | --- |
| Story treatments | GPT-6 Astra (premium/flagship) |
| Script doctor | Claude Opus 5.5 (`claude-opus-5-5`) |
| Final script | GPT-6 Astra |
| Identity stills | Sunburst / Flare |
| Cinematic I2V | Veo Lite (implemented), Gen-4.5 (implemented) |
| Multi-reference | Seedance 2.5 reference-to-video (**catalog**) |
| Motion control | Kling 3.0 Motion Control Pro, Genjutsu (**catalog**) |
| Video edit/extend | Seedance 2.5 (**catalog**) |
| Dialogue voice | Eleven v3 premium; OpenAI TTS fallback |
| Motion graphics | Local FFmpeg first; Higgsfield Motion Designer optional AE/MCP |

Catalog models never auto-route until readiness is `ADAPTER_IMPLEMENTED` or `PRODUCTION_READY`.

## Readiness

`CATALOG_ONLY` → `ADAPTER_IMPLEMENTED` → `INTERNAL_CANARY` → `PRODUCTION_READY`

Capability maturity stays `CATALOG_CAPABILITY` / `IMPLEMENTED_CAPABILITY` / `TESTED_CAPABILITY`.

## Customer UX

Economy / Balanced / Premium (and later mood labels). Model IDs stay backend/admin.

## Birko Episode 2

Target stack is declared in `BIRKO_E2_TARGET_STACK`. Draft only. No treatments, no HTTP, no Stars.
