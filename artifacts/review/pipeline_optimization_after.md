# Pipeline optimization — AFTER (Phase 10F)

Same methodology as `pipeline_optimization_before.md`. **MEASURED** / **ESTIMATED** / **REFERENCE** labeled.

Paid spend during this audit: **$0.00**. No Veo/Lyria/OpenAI/Whisper/Responses calls. `produce-episode --confirm-paid` was not run.

## Dry-run Phase 11 (MEASURED)

```
estimated_total_usd=0.96
video_seconds=16  video_cost_usd=0.8
music_generation_count=2  music_cost_usd=0.16
matcher=metadata  semantic_qc=false
actual_spend_usd=0.0
```

CLI wall ~2.96 s (planning only).

## Numerical summary

| Metric | Before | After |
|---|---|---|
| Phase 11 estimated paid (REFERENCE) | $0.96 | $0.96 first live run |
| Absolute first-run savings | — | **$0.00** (quality-preserving: still 2×8s Veo + 2 Lyria) |
| First-run cost reduction % | — | **0%** |
| Identical rerun paid | $0.96 | **$0.00** via paid cache |
| Cost avoided via paid cache (rerun) | $0 | **$0.96** |
| Music generations | 2 | **2** (1-song option REJECTED_QUALITY_RISK; would save $0.08 / 8.3%) |
| Veo generated seconds | 16 | **16** (6s REJECTED_QUALITY_RISK) |
| Expected final Phase 11 spend | $0.96 | **$0.96** then **$0** on identical retry |
| Cold mux (MEASURED analog) | 8.896 s reencode | **0.752 s** `-c:v copy` |
| Mux seconds saved / % / speedup | — | **8.144 s / 91.5% / 11.83×** |
| Warm loudnorm narration (MEASURED) | 4.599 s | **0.000 s** |
| SHA256 visual_v3 (MEASURED) | 0.0229 s | **0.0001 s** identity cache |
| Tiny 8-scene cold workers (MEASURED) | w1 0.668 s | w2 0.431 / w4 0.350 |
| Visual_v3 cache hit rate | 43/67 = 64.2% MEASURED | unchanged |
| Phase 11 visual scene rerenders | 0 of 67 (overlay path) | 0 of 67; overlay encode once then cached master |
| Paid requests first run | 4 | 4 |
| Paid requests identical second run | 4 | **0** |
| Polls at 900 s cap (ESTIMATED) | 900 ×1 s | **47** (5→20 s) |
| Storage maple | 1,018,706,200 B | same; **0** deleted |
| Duplicate extra bytes | 284,412,377 MEASURED | found, **not** removed (DEFERRED) |
| pytest / ruff | — | **309 passed** / **clean** |

Cold/warm **full** Phase 11 wall cannot be MEASURED without paid Veo/Lyria. ESTIMATED:

- Cold before: `T_veo1 + T_veo2 + T_lyria + T_mix + T_overlay + ~9 s mux`
- Cold after: `max(T_veo1,T_veo2) + T_lyria + T_mix + T_overlay + ~0.75 s mux`
- If both Veo calls ~equal, Veo wait ~**0.5×** serial.
- Warm after identical inputs: **0 paid**, skip overlay if `visual_master` hash matches, copy mux ~0.75 s, loudnorm analysis cached.

## Quality safety

**NO** implemented change to: resolution, FPS, production codec/CRF for scene renders, image/video/music/TTS/research models, scene timing, subtitle style/timing, visual selection, or sound-design semantics (still 2 HIGH_VALUE shots, 2 music sections, local generic SFX).

Stream-copy mux is **lossless** for the existing visual master.

## Remaining ranked ROI

1. Content-address/hardlink stock duplicates (~284 MB) — DEFERRED.
2. Overlap Lyria/mix prep during Veo poll — DEFERRED.
3. Stream Veo bytes instead of RAM `video_bytes` — low urgency (8 s 720p).
4. Optional VideoToolbox for **preview only** after A/B — not for final.
