from __future__ import annotations

from docprod.stock.models import StockCreditRecord, StockCreditsManifest, StockSourceManifest
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import ProjectPaths


def rebuild_credits(paths: ProjectPaths, project_id: str) -> StockCreditsManifest:
    records: list[StockCreditRecord] = []
    if paths.stock_dir.is_dir():
        for meta in sorted(paths.stock_dir.glob("*/source.meta.json")):
            try:
                item = load_model(meta, StockSourceManifest)
            except (OSError, ValueError):
                continue
            records.append(
                StockCreditRecord(
                    scene_id=item.scene_id,
                    provider=item.provider,
                    creator=item.creator_name,
                    source_url=item.source_page_url,
                    provider_video_id=item.provider_video_id,
                )
            )
    manifest = StockCreditsManifest(project_id=project_id, sources=records)
    paths.credits_dir.mkdir(parents=True, exist_ok=True)
    save_model(paths.stock_credits_json(), manifest)
    lines = ["Stock footage credits", ""]
    for item in records:
        lines.append(f"{item.scene_id}: {item.creator} / {item.provider} / {item.source_url}")
    paths.stock_credits_txt().write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest
