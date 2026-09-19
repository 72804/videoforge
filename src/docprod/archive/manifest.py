from __future__ import annotations

from datetime import UTC, datetime

from docprod.archive.licensing import attribution_text
from docprod.archive.models import ArchiveCreditsManifest, ArchiveSourceManifest
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import ProjectPaths


def record_archive_credit(
    paths: ProjectPaths, project_id: str, record: ArchiveSourceManifest
) -> None:
    path = paths.archive_credits_json()
    if path.is_file():
        manifest = load_model(path, ArchiveCreditsManifest)
        sources = [item for item in manifest.sources if item.asset_unit_id != record.asset_unit_id]
        sources.append(record)
        manifest = manifest.model_copy(update={"sources": sources})
    else:
        manifest = ArchiveCreditsManifest(project_id=project_id, sources=[record])
    save_model(path, manifest)
    _append_credits_txt(paths, record)


def _append_credits_txt(paths: ProjectPaths, record: ArchiveSourceManifest) -> None:
    line = (
        f"Wikimedia Commons: {record.title} — {record.artist or record.credit} — "
        f"{record.license_short_name} — {record.description_url}\n"
    )
    dest = paths.stock_credits_txt()
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    if record.description_url not in existing:
        dest.write_text(existing + line, encoding="utf-8")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def credit_from_candidate(
    unit_id: str, candidate, local_path: str, sha256: str
) -> ArchiveSourceManifest:
    return ArchiveSourceManifest(
        asset_unit_id=unit_id,
        title=candidate.title,
        description_url=candidate.description_url,
        file_url=candidate.file_url,
        artist=candidate.artist,
        credit=candidate.credit,
        license_short_name=candidate.license_short_name,
        license_url=candidate.license_url,
        usage_terms=candidate.usage_terms,
        attribution_text=attribution_text(candidate),
        attribution_required=candidate.attribution_required,
        restrictions=candidate.restrictions,
        retrieved_at=utc_now(),
        sha256=sha256,
        local_path=local_path,
        width=candidate.width,
        height=candidate.height,
    )
