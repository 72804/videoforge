# Pipeline optimization — BEFORE (Phase 10F)

Labels: **MEASURED** vs **ESTIMATED** vs **REFERENCE**. Never mixed silently.

## Full project (MEASURED)

| Item | Value |
|---|---|
| `src/docprod` Python modules | 153 files, 936,199 bytes |
| maple_heist_canary artifacts | 538 files, 1,018,706,200 bytes (~972 MiB) |
| repo `cache/` | 1 empty placeholder |
| exact-duplicate extra bytes | 284,412,377 (34 groups) |
| visual_v3 | 64,528,124 bytes, 1280×720 h264 yuv420p, 430.867 s |
| scenes | 67 |
| last visual_v3 cache | 43 hits / 24 misses, `segment_workers=4` in manifest |

Largest duplicate extras are repeated Pexels stock `source.mp4` copies per scene folder (safe to content-address later; **not** destructively rewritten in this pass).

## Stage table

| stage | current_runtime | current_paid_cost | API_requests | CPU | I/O | cacheability | parallelizable | quality_sensitivity | optimization_candidate |
|---|---|---|---|---|---|---|---|---|---|
| research/script/TTS/Whisper | frozen | $0 (this phase) | 0 | n/a | read | high | no | high | no |
| visual_v3 | last pass 43/24 cache (MEASURED) | $0 | 0 | high | high | high | yes (already 4) | high | low |
| Veo 2×8s | ESTIMATED serial 2×provider | **$0.80 REFERENCE** | 2 | low | clip download | none | yes | high | yes |
| Lyria 2 songs | ESTIMATED serial | **$0.16 REFERENCE** | 2 | low | wav | none | maybe | high | yes |
| mix/loudnorm | ESTIMATED; narration loudnorm 4.599s MEASURED | $0 | 0 | med | wav | analysis uncached | no | high | yes |
| final mux | reencode analog **8.896s MEASURED** | $0 | 0 | encode | 64MB | n/a | no | high if reencoded | **yes** |

## Cost baseline (REFERENCE, pricing 2026-09-19)

- Veo 3.1 Lite 720p: $0.05/s × 16 s = **$0.80**
- Lyria 3.5: $0.08/song × 2 = **$0.16**
- Expected Phase 11: **$0.96**
- Identical rerun without paid cache: **$0.96 again**

## Bottlenecks

1. No durable Veo/Lyria request cache → identical retries rebill.
2. Invalid Veo image payloads could hit the network (previous malformed File attempt).
3. Tight/unbounded operation polling.
4. Final production mux re-encoded video.
5. Loudnorm re-scanned unchanged files.
6. SHA256/ffprobe repeated on unchanged large files.
7. Serial independent Veo shots.
8. JSON rewritten even when identical (mtime invalidation).
9. Empty sound library still allowed embedding matcher config.
10. Stock copies duplicated on disk (~284 MB extra).

## Quality constraints carried into implementation

Do not drop HIGH_VALUE shots, do not shorten Veo below 8 s (8.38/6 > 1.07 retime), do not collapse 2 story-arc Lyria songs into 1.
