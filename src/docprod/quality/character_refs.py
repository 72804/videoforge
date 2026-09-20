from __future__ import annotations

import math
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from docprod.drama.story import CHARACTER_REF_PLAN
from docprod.models.scene import ScenePlan
from docprod.providers.openai_image import OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES
from docprod.providers.pricing import (
    BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD,
    BIRKO_DRAMA_IMAGE_PAID_CALLS,
    IMAGE_MIGRATION_HARD_CAP_USD,
    MAPLE_7_IMAGE_BATCH_TOTAL_USD,
    estimated_image_migration_usd,
)
from docprod.quality.enums import CostConfidence, ReferenceMode
from docprod.quality.specs import CharacterProfile, CharacterReferenceSet
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import load_json, save_json
from docprod.storage.paths import ProjectPaths

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MIN_SHORT_SIDE = 256
MAX_BYTES = 80 * 1024 * 1024
IMAGE_COST_ESTIMATE_USD = None  # no per-image list price; see providers.pricing
IDENTITY_MISMATCH = "CUSTOM_CHARACTER_IDENTITY_MISMATCH"
UI_OPERATIONS = (
    "upload_character",
    "replace_character",
    "add_reference_angle",
    "choose_primary",
    "lock_identity",
    "view_references",
    "remove_reference",
    "regenerate_character",
    "apply_to_future_scenes",
    "apply_to_entire_episode",
)
# Request-level adapter capacity (files in one generate/edit call).
PROVIDER_TASK_LIMITS: dict[tuple[str, str], int] = {
    ("openai", "image"): OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES,
    ("google", "image"): 4,
    ("google", "i2v"): 0,
    ("runway", "i2v"): 0,
    ("runway", "dialogue"): 1,
    ("runway", "performance"): 1,
    ("runway", "image"): 1,
}
# Angles of the SAME character. Scene bind uses one primary per identity.
PER_CHARACTER_ANGLE_LIMITS: dict[tuple[str, str], int] = {
    ("openai", "image"): 2,
    ("google", "image"): 2,
    ("runway", "image"): 1,
}


class CharacterRefRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    width: int = 0
    height: int = 0
    aspect_ratio: str = ""
    source: str = "user_supplied"
    created_at: str = ""
    locked: bool = False
    primary: bool = False
    role: str = "unknown"
    validation: str = "ok"


class CharacterManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str
    display_name: str = ""
    reference_mode: ReferenceMode = ReferenceMode.AUTO_GENERATED
    custom_references: list[CharacterRefRecord] = Field(default_factory=list)
    generated_references: list[CharacterRefRecord] = Field(default_factory=list)
    canonical_references: list[str] = Field(default_factory=list)
    sha256: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    source: str = "pipeline_generated"
    created_at: str = ""
    locked: bool = False
    primary_reference: str = ""
    identity_version: str = ""
    description: str = ""


class CharacterManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    updated_at: str = ""
    characters: list[CharacterManifestEntry] = Field(default_factory=list)
    ui_operations: tuple[str, ...] = UI_OPERATIONS
    applies_to_future_generations_only: bool = True


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    aspect_ratio: str = ""
    sha256: str = ""
    size_bytes: int = 0


@dataclass
class ResolvedCharacterRefs:
    character_id: str
    mode: ReferenceMode
    identity_version: str
    paths: list[Path]
    primary: Path | None
    locked: bool
    uploaded_to_provider: bool = False


@dataclass
class IdentityMismatch:
    code: str
    characters: list[str]
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class MigrationRow:
    scene_id: str
    characters: list[str]
    old_versions: dict[str, str]
    new_versions: dict[str, str]
    regeneration_required: bool


def normalize_character_id(raw: str) -> str:
    value = str(raw or "").strip().lower().replace(" ", "_")
    if value.startswith("ref_"):
        value = value[4:]
    if not value or not all(ch.isalnum() or ch in {"_", "-"} for ch in value):
        raise ValueError(f"Unsafe character id {raw!r}")
    return value


def generated_ref_stem(character_id: str) -> str:
    cid = normalize_character_id(character_id)
    return f"ref_{cid}"


def identity_version(character_id: str, mode: ReferenceMode, hashes: list[str]) -> str:
    cid = normalize_character_id(character_id)
    kind = {
        ReferenceMode.AUTO_GENERATED: "generated",
        ReferenceMode.CUSTOM: "custom",
        ReferenceMode.HYBRID: "hybrid",
    }[mode]
    index = 1 if mode is ReferenceMode.AUTO_GENERATED else 2
    digest = content_hash(
        {"character_id": cid, "mode": mode.value, "sha256": list(hashes)}
    )
    if not hashes:
        return f"{cid}:v0-none"
    return f"{cid}:v{index}-{kind}-{digest[:8]}"


def validate_character_image(path: Path) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return ValidationResult(False, ["file_missing"])
    size = path.stat().st_size
    if size <= 0:
        return ValidationResult(False, ["zero_byte"], size_bytes=size)
    if size > MAX_BYTES:
        errors.append("file_too_large")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        errors.append(f"unsupported_format:{suffix or 'none'}")
    digest = file_sha256(path)
    width = height = 0
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            fmt = (image.format or "").lower()
        if fmt not in {"jpeg", "png", "webp"}:
            errors.append(f"undecodable_or_unsupported:{fmt or 'unknown'}")
    except (UnidentifiedImageError, OSError, ValueError):
        errors.append("corrupt_or_undecodable")
        return ValidationResult(False, errors, warnings, 0, 0, "", digest, size)
    short = min(width, height)
    if short < MIN_SHORT_SIDE:
        errors.append(f"extremely_low_resolution:{width}x{height}")
    ratio = _aspect_label(width, height)
    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        width=width,
        height=height,
        aspect_ratio=ratio,
        sha256=digest,
        size_bytes=size,
    )


def _aspect_label(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "0"
    gcd = math.gcd(width, height)
    return f"{width // gcd}:{height // gcd}"


def _role_from_name(name: str) -> str:
    stem = Path(name).stem.lower().replace("-", "_")
    mapping = {
        "front": "front",
        "face": "front",
        "portrait": "front",
        "three_quarter": "three_quarter",
        "threequarter": "three_quarter",
        "3q": "three_quarter",
        "full_body": "full_body",
        "fullbody": "full_body",
        "side": "side",
        "profile": "profile",
    }
    return mapping.get(stem, "unknown")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _rel(paths: ProjectPaths, path: Path) -> str:
    try:
        return path.resolve().relative_to(paths.root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _abs(paths: ProjectPaths, rel: str) -> Path:
    return (paths.root / rel).resolve()


def _plan_meta() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in CHARACTER_REF_PLAN:
        cid = normalize_character_id(str(item["id"]))
        out[cid] = {
            "display_name": str(item.get("character") or cid),
            "description": str(item.get("prompt") or ""),
            "role": str(item.get("role") or ""),
        }
    return out


def _generated_files(paths: ProjectPaths, character_id: str) -> list[Path]:
    folder = paths.generated_character_refs_dir()
    stem = generated_ref_stem(character_id)
    found: list[Path] = []
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = folder / f"{stem}{suffix}"
        if candidate.is_file():
            found.append(candidate)
    return found


def _record_from_path(
    paths: ProjectPaths,
    path: Path,
    *,
    source: str,
    locked: bool,
    primary: bool,
    validation: ValidationResult | None = None,
) -> CharacterRefRecord:
    qc = validation or validate_character_image(path)
    return CharacterRefRecord(
        path=_rel(paths, path),
        sha256=qc.sha256 or file_sha256(path),
        width=qc.width,
        height=qc.height,
        aspect_ratio=qc.aspect_ratio,
        source=source,
        created_at=_now(),
        locked=locked,
        primary=primary,
        role=_role_from_name(path.name),
        validation="ok" if qc.ok else ",".join(qc.errors),
    )


def _refresh_entry(entry: CharacterManifestEntry) -> CharacterManifestEntry:
    if entry.reference_mode is ReferenceMode.CUSTOM:
        canonical = [item.path for item in entry.custom_references]
        source = "user_supplied"
        locked = True
        hashes = [item.sha256 for item in entry.custom_references]
    elif entry.reference_mode is ReferenceMode.HYBRID:
        canonical = [item.path for item in entry.custom_references] or [
            item.path for item in entry.generated_references
        ]
        source = "hybrid"
        locked = True
        hashes = [item.sha256 for item in entry.custom_references] or [
            item.sha256 for item in entry.generated_references
        ]
    else:
        canonical = [item.path for item in entry.generated_references]
        source = "pipeline_generated"
        locked = False
        hashes = [item.sha256 for item in entry.generated_references]
    dims = [
        f"{item.width}x{item.height}"
        for item in [*entry.custom_references, *entry.generated_references]
        if item.width and item.height
    ]
    primary = entry.primary_reference
    if not primary and canonical:
        primary = canonical[0]
        for item in entry.custom_references:
            item.primary = item.path == primary
    entry.canonical_references = canonical
    entry.sha256 = hashes
    entry.dimensions = dims
    entry.source = source
    entry.locked = locked
    entry.primary_reference = primary
    entry.identity_version = identity_version(entry.character_id, entry.reference_mode, hashes)
    if not entry.created_at:
        entry.created_at = _now()
    return entry


def empty_entry(
    character_id: str, *, display_name: str = "", description: str = ""
) -> CharacterManifestEntry:
    cid = normalize_character_id(character_id)
    return CharacterManifestEntry(
        character_id=cid,
        display_name=display_name or cid,
        description=description,
        created_at=_now(),
    )


def load_manifest(paths: ProjectPaths) -> CharacterManifest:
    path = paths.character_manifest_json()
    if path.is_file():
        payload = load_json(path)
        if isinstance(payload, dict):
            return CharacterManifest.model_validate(payload)
    return CharacterManifest(project_id=paths.root.name, updated_at=_now())


def save_manifest(paths: ProjectPaths, manifest: CharacterManifest) -> Path:
    dest = paths.character_manifest_json()
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest.updated_at = _now()
    manifest.project_id = paths.root.name
    save_json(dest, manifest.model_dump(mode="json"))
    return dest


def bootstrap_manifest(paths: ProjectPaths) -> CharacterManifest:
    """Discover generated + custom files. Never deletes generated refs."""
    manifest = load_manifest(paths)
    by_id = {item.character_id: item for item in manifest.characters}
    meta = _plan_meta()
    ids = set(meta) | set(by_id)
    if paths.character_inputs_root().is_dir():
        for folder in paths.character_inputs_root().iterdir():
            if folder.is_dir():
                ids.add(normalize_character_id(folder.name))
    gen_dir = paths.generated_character_refs_dir()
    if gen_dir.is_dir():
        for file in gen_dir.iterdir():
            if file.suffix.lower() in SUPPORTED_SUFFIXES and file.stem.startswith("ref_"):
                ids.add(normalize_character_id(file.stem))
    for cid in sorted(ids):
        entry = by_id.get(cid) or empty_entry(
            cid,
            display_name=meta.get(cid, {}).get("display_name", cid),
            description=meta.get(cid, {}).get("description", ""),
        )
        generated: list[CharacterRefRecord] = []
        seen_gen = {item.sha256 for item in entry.generated_references}
        for path in _generated_files(paths, cid):
            rec = _record_from_path(
                paths, path, source="pipeline_generated", locked=False, primary=False
            )
            if rec.sha256 in seen_gen:
                existing = next(
                    item for item in entry.generated_references if item.sha256 == rec.sha256
                )
                generated.append(existing)
            else:
                generated.append(rec)
                seen_gen.add(rec.sha256)
        if generated:
            entry.generated_references = generated
        custom: list[CharacterRefRecord] = []
        folder = paths.character_input_dir(cid)
        if folder.is_dir():
            known = {item.sha256: item for item in entry.custom_references}
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                rec = _record_from_path(
                    paths,
                    path,
                    source="user_supplied",
                    locked=True,
                    primary=False,
                )
                custom.append(known.get(rec.sha256, rec))
        if custom and entry.reference_mode is ReferenceMode.AUTO_GENERATED:
            # Files appeared on disk without import CLI — treat as CUSTOM lock.
            entry.reference_mode = ReferenceMode.CUSTOM
        if custom:
            entry.custom_references = custom
            if not entry.primary_reference:
                entry.primary_reference = custom[0].path
        by_id[cid] = _refresh_entry(entry)
    manifest.characters = [by_id[cid] for cid in sorted(by_id)]
    save_manifest(paths, manifest)
    return manifest


def import_character_images(
    paths: ProjectPaths,
    character_id: str,
    images: list[Path],
) -> tuple[CharacterManifestEntry, list[str]]:
    cid = normalize_character_id(character_id)
    dest_dir = paths.character_input_dir(cid)
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest = bootstrap_manifest(paths)
    entry = next((item for item in manifest.characters if item.character_id == cid), None)
    if entry is None:
        meta = _plan_meta().get(cid, {})
        entry = empty_entry(cid, display_name=meta.get("display_name", cid))
        manifest.characters.append(entry)
    notes: list[str] = []
    existing_hashes = {item.sha256 for item in entry.custom_references}
    first_custom = len(entry.custom_references) == 0
    for source in images:
        src = Path(source).expanduser().resolve()
        qc = validate_character_image(src)
        if not qc.ok:
            raise ValueError(f"{src}: {', '.join(qc.errors)}")
        if qc.sha256 in existing_hashes:
            notes.append(f"duplicate_hash_skipped={src.name}")
            continue
        dest = _duplicate_safe_dest(dest_dir, src, qc.sha256)
        if dest.exists() and file_sha256(dest) == qc.sha256:
            notes.append(f"already_present={dest.name}")
        else:
            shutil.copyfile(src, dest)
            notes.append(f"copied={dest.name}")
        rec = _record_from_path(
            paths,
            dest,
            source="user_supplied",
            locked=True,
            primary=False,
            validation=qc,
        )
        rec.sha256 = qc.sha256
        rec.width = qc.width
        rec.height = qc.height
        rec.aspect_ratio = qc.aspect_ratio
        entry.custom_references.append(rec)
        existing_hashes.add(qc.sha256)
        if first_custom:
            entry.primary_reference = rec.path
            rec.primary = True
            first_custom = False
    entry.reference_mode = ReferenceMode.CUSTOM
    entry.locked = True
    entry = _refresh_entry(entry)
    for item in entry.custom_references:
        item.primary = item.path == entry.primary_reference
        item.locked = True
    manifest.characters = [
        entry if item.character_id == cid else item for item in manifest.characters
    ]
    save_manifest(paths, manifest)
    return entry, notes


def _duplicate_safe_dest(dest_dir: Path, source: Path, digest: str) -> Path:
    suffix = source.suffix.lower() or ".jpg"
    candidate = dest_dir / source.name
    if not candidate.exists():
        return candidate
    if file_sha256(candidate) == digest:
        return candidate
    hashed = dest_dir / f"{source.stem}-{digest[:8]}{suffix}"
    if not hashed.exists() or file_sha256(hashed) == digest:
        return hashed
    index = 2
    while True:
        alt = dest_dir / f"{source.stem}-{digest[:8]}-{index}{suffix}"
        if not alt.exists() or file_sha256(alt) == digest:
            return alt
        index += 1


def set_primary_reference(
    paths: ProjectPaths, character_id: str, reference: str
) -> CharacterManifestEntry:
    cid = normalize_character_id(character_id)
    manifest = bootstrap_manifest(paths)
    entry = next((item for item in manifest.characters if item.character_id == cid), None)
    if entry is None or not entry.custom_references:
        raise ValueError(f"No custom references for {cid}")
    needle = str(reference).replace("\\", "/")
    match = None
    for item in entry.custom_references:
        if item.path == needle or Path(item.path).name == Path(needle).name:
            match = item
            break
        if needle in item.path:
            match = item
            break
    if match is None:
        raise ValueError(f"Reference {reference!r} not found for {cid}")
    entry.primary_reference = match.path
    for item in entry.custom_references:
        item.primary = item.path == match.path
    entry = _refresh_entry(entry)
    manifest.characters = [
        entry if item.character_id == cid else item for item in manifest.characters
    ]
    save_manifest(paths, manifest)
    return entry


def should_generate_identity_sheet(paths: ProjectPaths, character_id: str) -> bool:
    cid = normalize_character_id(character_id)
    manifest_missing = not paths.character_manifest_json().is_file()
    custom_missing = not paths.character_input_dir(cid).is_dir()
    if manifest_missing and custom_missing:
        return True
    manifest = bootstrap_manifest(paths)
    entry = next((item for item in manifest.characters if item.character_id == cid), None)
    if entry is None:
        return True
    if entry.reference_mode is ReferenceMode.CUSTOM and entry.locked:
        return False
    return True


def resolve_character_references(
    paths: ProjectPaths,
    character_id: str,
    *,
    provider: str = "",
    task: str = "image",
    model_id: str = "",
) -> ResolvedCharacterRefs:
    _ = model_id
    cid = normalize_character_id(character_id)
    manifest = bootstrap_manifest(paths) if paths.root.exists() else CharacterManifest(
        project_id="none"
    )
    entry = next((item for item in manifest.characters if item.character_id == cid), None)
    if entry is None:
        files = _generated_files(paths, cid)
        version = identity_version(
            cid, ReferenceMode.AUTO_GENERATED, [file_sha256(p) for p in files]
        )
        return ResolvedCharacterRefs(
            cid, ReferenceMode.AUTO_GENERATED, version, files, files[0] if files else None, False
        )
    custom_paths = [_abs(paths, item.path) for item in entry.custom_references if item.path]
    custom_paths = [path for path in custom_paths if path.is_file()]
    generated_paths = [_abs(paths, item.path) for item in entry.generated_references if item.path]
    generated_paths = [path for path in generated_paths if path.is_file()]
    selected: list[Path] = []
    if entry.reference_mode is ReferenceMode.CUSTOM:
        if not custom_paths:
            raise ValueError(
                f"CUSTOM identity {cid} has no usable local references; "
                "refusing silent fallback to another identity"
            )
        selected = _select_subset(custom_paths, entry.primary_reference, provider, task, paths)
    elif entry.reference_mode is ReferenceMode.HYBRID:
        pool = custom_paths or generated_paths
        if custom_paths:
            extra = [path for path in generated_paths if path not in custom_paths]
            pool = custom_paths + extra
        selected = _select_subset(pool, entry.primary_reference, provider, task, paths)
    else:
        selected = _select_subset(
            generated_paths, entry.primary_reference, provider, task, paths
        )
    primary = None
    if entry.primary_reference:
        candidate = _abs(paths, entry.primary_reference)
        if candidate.is_file() and candidate in selected:
            primary = candidate
    if primary is None and selected:
        primary = selected[0]
    return ResolvedCharacterRefs(
        character_id=cid,
        mode=entry.reference_mode,
        identity_version=entry.identity_version,
        paths=selected,
        primary=primary,
        locked=entry.locked,
        uploaded_to_provider=False,
    )


def _select_subset(
    pool: list[Path],
    primary_rel: str,
    provider: str,
    task: str,
    paths: ProjectPaths,
) -> list[Path]:
    if not pool:
        return []
    key = (provider.lower(), task.lower())
    request_limit = PROVIDER_TASK_LIMITS.get(key)
    if request_limit is not None and request_limit <= 0:
        return []
    limit = PER_CHARACTER_ANGLE_LIMITS.get(key)
    if limit is None:
        limit = 2 if task == "image" else 1
    if request_limit is not None:
        limit = min(limit, request_limit)
    if limit <= 0:
        return []
    ordered: list[Path] = []
    if primary_rel:
        primary = _abs(paths, primary_rel)
        if primary in pool:
            ordered.append(primary)
    role_rank = {"front": 0, "three_quarter": 1, "full_body": 2, "side": 3, "profile": 4}
    rest = [path for path in pool if path not in ordered]
    rest.sort(key=lambda path: (role_rank.get(_role_from_name(path.name), 9), path.name))
    for path in rest:
        ordered.append(path)
        if len(ordered) >= limit:
            break
    return ordered[:limit]


def bind_scene_identity_references(
    paths: ProjectPaths,
    character_ids: list[str],
    *,
    provider: str = "openai",
    task: str = "image",
) -> list[tuple[str, Path, str]]:
    """One identity-preserving reference per visible character. Never silent-drop."""
    bound: list[tuple[str, Path, str]] = []
    for raw in character_ids:
        cid = normalize_character_id(raw)
        resolved = resolve_character_references(paths, cid, provider=provider, task=task)
        primary = resolved.primary or (resolved.paths[0] if resolved.paths else None)
        if primary is None:
            raise ValueError(f"No identity reference available for {cid}")
        bound.append((cid, primary, resolved.identity_version))
    if (
        len(bound) > OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES
        and provider == "openai"
        and task == "image"
    ):
        missing = [cid for cid, _, _ in bound[OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES:]]
        raise ValueError(
            f"Would drop character identities {missing}; adapter max is "
            f"{OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES}. Do not generate this scene."
        )
    return bound


def detect_identity_mismatch(
    paths: ProjectPaths,
    plan: ScenePlan | None = None,
    *,
    allow_identity_mix: bool = False,
) -> IdentityMismatch | None:
    if allow_identity_mix:
        return None
    manifest = bootstrap_manifest(paths)
    changed: list[str] = []
    details: list[str] = []
    for entry in manifest.characters:
        if entry.reference_mode is ReferenceMode.AUTO_GENERATED:
            continue
        if not entry.custom_references:
            continue
        gen_hashes = [item.sha256 for item in entry.generated_references]
        custom_hashes = [item.sha256 for item in entry.custom_references]
        if _character_covered_by_custom_v2(paths, plan, entry.character_id):
            continue
        if gen_hashes and gen_hashes != custom_hashes:
            changed.append(entry.character_id)
            old_gen = identity_version(
                entry.character_id, ReferenceMode.AUTO_GENERATED, gen_hashes
            )
            details.append(
                f"{entry.character_id} custom {entry.identity_version} != generated {old_gen}"
            )
        elif _stills_exist_for_character(paths, plan, entry.character_id):
            changed.append(entry.character_id)
            details.append(f"{entry.character_id} has custom identity and existing V1 stills")
    if not changed:
        return None
    return IdentityMismatch(
        code=IDENTITY_MISMATCH,
        characters=changed,
        message=(
            f"{IDENTITY_MISMATCH}: custom identities {', '.join(changed)} would mix with "
            "existing V1 generated-character stills. Regenerate affected stills or pass an "
            "explicit mix allowance."
        ),
        details=details,
    )


def _character_covered_by_custom_v2(
    paths: ProjectPaths, plan: ScenePlan | None, character_id: str
) -> bool:
    if plan is None:
        return False
    cid = normalize_character_id(character_id)
    needed = False
    for scene in plan.scenes:
        chars = [normalize_character_id(c) for c in (scene.metadata or {}).get("characters") or []]
        if cid not in chars:
            continue
        needed = True
        if not paths.custom_v2_scene_image(scene.id).is_file():
            return False
    return needed


def _stills_exist_for_character(
    paths: ProjectPaths, plan: ScenePlan | None, character_id: str
) -> bool:
    if plan is None:
        visuals = paths.visuals_dir
        if not visuals.is_dir():
            return False
        return any(
            (folder / "image.jpg").is_file() or (folder / "image.jpeg").is_file()
            for folder in visuals.iterdir()
            if folder.is_dir() and folder.name.startswith("scene_")
        )
    cid = normalize_character_id(character_id)
    for scene in plan.scenes:
        chars = [normalize_character_id(c) for c in (scene.metadata or {}).get("characters") or []]
        if cid in chars and paths.scene_image_path(scene.id).is_file():
            return True
    return False


def plan_character_migration(paths: ProjectPaths, plan: ScenePlan) -> list[MigrationRow]:
    manifest = bootstrap_manifest(paths)
    by_id = {item.character_id: item for item in manifest.characters}
    rows: list[MigrationRow] = []
    for scene in plan.scenes:
        chars = [normalize_character_id(c) for c in (scene.metadata or {}).get("characters") or []]
        if not chars:
            continue
        old: dict[str, str] = {}
        new: dict[str, str] = {}
        needed = False
        meta_versions = _scene_recorded_versions(paths, scene.id)
        for cid in chars:
            entry = by_id.get(cid)
            gen = _generated_files(paths, cid)
            old_hashes = [file_sha256(path) for path in gen]
            old_ver = meta_versions.get(cid) or identity_version(
                cid, ReferenceMode.AUTO_GENERATED, old_hashes
            )
            new_ver = entry.identity_version if entry else old_ver
            old[cid] = old_ver
            new[cid] = new_ver
            if old_ver != new_ver:
                needed = True
        rows.append(
            MigrationRow(
                scene_id=scene.id,
                characters=chars,
                old_versions=old,
                new_versions=new,
                regeneration_required=needed,
            )
        )
    return rows


def _scene_recorded_versions(paths: ProjectPaths, scene_id: str) -> dict[str, str]:
    meta = paths.scene_image_meta(scene_id)
    if not meta.is_file():
        return {}
    try:
        payload = load_json(meta)
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("character_identity_versions") or {}
    if not isinstance(raw, dict):
        return {}
    return {normalize_character_id(str(k)): str(v) for k, v in raw.items()}


def migration_summary(rows: list[MigrationRow]) -> dict[str, Any]:
    regen = [row for row in rows if row.regeneration_required]
    calls = len(regen)
    return {
        "scenes": len(rows),
        "regeneration_required": calls,
        "estimated_image_generation_calls": calls,
        "estimated_cost_usd": estimated_image_migration_usd(calls) if calls else 0.0,
        "cost_confidence": CostConfidence.ESTIMATED.value,
        "cost_basis": (
            f"Birko {BIRKO_DRAMA_IMAGE_PAID_CALLS} image calls attributable "
            f"${BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD} (not a list price). "
            f"Maple ${MAPLE_7_IMAGE_BATCH_TOTAL_USD} was a 7-image BATCH total."
        ),
        "hard_cap_usd": IMAGE_MIGRATION_HARD_CAP_USD,
        "paid_calls": 0,
    }


def character_set_from_manifest(paths: ProjectPaths | None) -> CharacterReferenceSet:
    if paths is None:
        profiles = []
        for item in CHARACTER_REF_PLAN:
            cid = normalize_character_id(str(item["id"]))
            profiles.append(
                CharacterProfile(
                    character_id=str(item["id"]),
                    name=str(item.get("character") or cid),
                    description=str(item.get("prompt") or ""),
                    appearance_notes=str(item.get("role") or ""),
                    reference_mode=ReferenceMode.AUTO_GENERATED,
                    identity_version=identity_version(cid, ReferenceMode.AUTO_GENERATED, []),
                )
            )
        return CharacterReferenceSet(project_id="drama", profiles=profiles)
    manifest = bootstrap_manifest(paths)
    profiles: list[CharacterProfile] = []
    for entry in manifest.characters:
        cid_ref = generated_ref_stem(entry.character_id)
        profiles.append(
            CharacterProfile(
                character_id=cid_ref,
                name=entry.display_name,
                description=entry.description,
                canonical_refs=entry.canonical_references,
                appearance_notes=entry.reference_mode.value,
                generation_hashes=[item.sha256 for item in entry.generated_references],
                reference_mode=entry.reference_mode,
                locked=entry.locked,
                identity_version=entry.identity_version,
                custom_references=[item.path for item in entry.custom_references],
                generated_references=[item.path for item in entry.generated_references],
                primary_reference=entry.primary_reference,
            )
        )
    return CharacterReferenceSet(
        project_id=paths.root.name,
        profiles=profiles,
        manifest_path=str(paths.character_manifest_json()),
        ui_operations=UI_OPERATIONS,
    )


def status_rows(paths: ProjectPaths) -> list[dict[str, Any]]:
    manifest = bootstrap_manifest(paths)
    rows: list[dict[str, Any]] = []
    for entry in manifest.characters:
        rows.append(
            {
                "character": entry.display_name,
                "character_id": entry.character_id,
                "mode": entry.reference_mode.value,
                "custom_refs": len(entry.custom_references),
                "generated_refs": len(entry.generated_references),
                "canonical": list(entry.canonical_references),
                "validation": [item.validation for item in entry.custom_references]
                or [item.validation for item in entry.generated_references]
                or ["n/a"],
                "dimensions": list(entry.dimensions),
                "aspect_ratios": [
                    item.aspect_ratio
                    for item in [*entry.custom_references, *entry.generated_references]
                    if item.aspect_ratio
                ],
                "sha256": list(entry.sha256),
                "identity_version": entry.identity_version,
                "locked": entry.locked,
                "primary": entry.primary_reference,
            }
        )
    return rows


def contact_sheet_entries(paths: ProjectPaths) -> list[tuple[str, str, Path]]:
    manifest = bootstrap_manifest(paths)
    entries: list[tuple[str, str, Path]] = []
    for entry in manifest.characters:
        for rec in entry.custom_references:
            marker = "CUSTOM*" if rec.primary else "CUSTOM"
            path = _abs(paths, rec.path)
            entries.append((entry.display_name, marker, path))
        for rec in entry.generated_references:
            path = _abs(paths, rec.path)
            entries.append((entry.display_name, "GENERATED", path))
    return entries


def prepare_character_input_dirs(paths: ProjectPaths, character_ids: list[str]) -> list[Path]:
    created: list[Path] = []
    for raw in character_ids:
        cid = normalize_character_id(raw)
        folder = paths.character_input_dir(cid)
        folder.mkdir(parents=True, exist_ok=True)
        created.append(folder)
    bootstrap_manifest(paths)
    return created
