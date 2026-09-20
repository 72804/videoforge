from __future__ import annotations

from docprod.drama.story import CHARACTER_REF_PLAN
from docprod.quality.specs import CharacterProfile, CharacterReferenceSet
from docprod.storage.hashing import file_sha256
from docprod.storage.paths import ProjectPaths


def character_set_for_drama(paths: ProjectPaths | None = None) -> CharacterReferenceSet:
    profiles: list[CharacterProfile] = []
    for item in CHARACTER_REF_PLAN:
        hashes: list[str] = []
        refs: list[str] = []
        if paths is not None:
            candidate = paths.visuals_dir / "character_refs" / f"{item['id']}.jpg"
            if candidate.is_file():
                refs.append(str(candidate))
                hashes.append(file_sha256(candidate))
        profiles.append(
            CharacterProfile(
                character_id=str(item["id"]),
                name=str(item["character"]),
                description=str(item.get("prompt") or ""),
                canonical_refs=refs,
                appearance_notes=str(item.get("role") or ""),
                generation_hashes=hashes,
            )
        )
    project_id = paths.root.name if paths is not None else "drama"
    return CharacterReferenceSet(project_id=project_id, profiles=profiles)


def ref_hashes_for_scene(character_ids: list[str], charset: CharacterReferenceSet) -> list[str]:
    by_id = {p.character_id: p for p in charset.profiles}
    out: list[str] = []
    for cid in character_ids:
        key = cid if cid.startswith("ref_") else f"ref_{cid}"
        profile = by_id.get(key) or by_id.get(cid)
        if profile:
            out.extend(profile.generation_hashes)
    return out
