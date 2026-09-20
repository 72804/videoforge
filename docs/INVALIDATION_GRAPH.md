# Invalidation graph

Deterministic stale flags after product edits. Implemented in
`docprod.product.invalidation.effects_for`.

| Event | Image | Video | Render |
|---|---|---|---|
| Character reference changed | stale (scenes using that character) | stale | stale |
| Scene visual prompt changed | stale | stale | stale |
| Scene motion prompt changed | **valid** | stale | stale |
| Scene video model changed | **valid** | stale | stale |
| Scene image model changed | stale | stale | stale |
| Scene characters changed | stale | stale | stale |
| Scene duration changed | stale (if frame coverage changes) | stale | stale |
| Scene order changed | **valid** | **valid** | stale |
| Scene deleted | n/a | n/a | stale |
| Replacement image uploaded | **valid** (new image) | stale | stale |
| Replacement video uploaded | **valid** | **valid** (new video) | stale |

Regenerating scene N creates a new `SceneVersion` for N only.
Scenes 1…N−1 keep their active versions and assets.

A stale render must not be exported as final until `render_project()` runs
again. Generated scene assets remain reusable when only order changed.
