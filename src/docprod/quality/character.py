from __future__ import annotations

from docprod.quality.character_refs import character_set_from_manifest
from docprod.quality.specs import CharacterReferenceSet
from docprod.storage.paths import ProjectPaths


def character_set_for_drama(paths: ProjectPaths | None = None) -> CharacterReferenceSet:
    return character_set_from_manifest(paths)


def ref_hashes_for_scene(character_ids: list[str], charset: CharacterReferenceSet) -> list[str]:
    by_id = {p.character_id: p for p in charset.profiles}
    out: list[str] = []
    for cid in character_ids:
        key = cid if str(cid).startswith("ref_") else f"ref_{cid}"
        profile = by_id.get(key) or by_id.get(cid)
        if profile is None:
            continue
        out.extend(profile.generation_hashes)
        if profile.identity_version:
            out.append(profile.identity_version)
    return out
