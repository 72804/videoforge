from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from docprod.drama.planner import compile_drama_scene_plan
from docprod.drama.story import build_birko_script
from docprod.pipeline.generate_drama_visuals import plan_drama_visual_jobs
from docprod.quality.character import character_set_for_drama
from docprod.quality.character_refs import (
    IDENTITY_MISMATCH,
    detect_identity_mismatch,
    identity_version,
    import_character_images,
    plan_character_migration,
    resolve_character_references,
    set_primary_reference,
    should_generate_identity_sheet,
    validate_character_image,
)
from docprod.quality.enums import ReferenceMode
from docprod.storage.hashing import file_sha256
from docprod.storage.paths import ProjectPaths, ensure_project_layout


def _jpeg(
    path: Path,
    *,
    size: tuple[int, int] = (640, 800),
    color: tuple[int, int, int] = (20, 40, 60),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")
    return path


def _project(tmp_path: Path) -> ProjectPaths:
    paths = ProjectPaths(tmp_path / "demo_chars")
    ensure_project_layout(paths)
    return paths


def test_auto_generated_backwards_compatible(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    generated = paths.generated_character_refs_dir() / "ref_birko.jpg"
    _jpeg(generated, color=(1, 2, 3))
    charset = character_set_for_drama(paths)
    by_id = {p.character_id: p for p in charset.profiles}
    assert by_id["ref_birko"].reference_mode is ReferenceMode.AUTO_GENERATED
    assert by_id["ref_birko"].locked is False
    assert Path(by_id["ref_birko"].canonical_refs[0]).name == "ref_birko.jpg"
    assert generated.is_file()


def test_import_multiple_primary_and_lock(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    generated = paths.generated_character_refs_dir() / "ref_birko.jpg"
    _jpeg(generated, color=(9, 9, 9))
    original = tmp_path / "incoming" / "front.jpg"
    other = tmp_path / "incoming" / "three_quarter.jpg"
    _jpeg(original, color=(10, 20, 30))
    _jpeg(other, size=(900, 1200), color=(40, 50, 60))
    before = original.read_bytes()
    entry, notes = import_character_images(paths, "birko", [original, other])
    assert original.read_bytes() == before
    assert entry.reference_mode is ReferenceMode.CUSTOM
    assert entry.locked is True
    assert entry.primary_reference.endswith("front.jpg")
    assert len(entry.custom_references) == 2
    assert generated.is_file()
    assert any("copied=" in note for note in notes)
    entry = set_primary_reference(paths, "birko", "three_quarter.jpg")
    assert entry.primary_reference.endswith("three_quarter.jpg")


def test_duplicate_hash_skipped(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    src = tmp_path / "face.jpg"
    _jpeg(src, color=(11, 12, 13))
    import_character_images(paths, "kemal", [src])
    entry, notes = import_character_images(paths, "kemal", [src])
    assert len(entry.custom_references) == 1
    assert any("duplicate_hash" in note for note in notes)


def test_duplicate_safe_filename(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    dest_dir = paths.character_input_dir("muge")
    dest_dir.mkdir(parents=True)
    clash = dest_dir / "front.jpg"
    _jpeg(clash, color=(1, 1, 1))
    incoming = tmp_path / "front.jpg"
    _jpeg(incoming, color=(2, 2, 2))
    entry, _notes = import_character_images(paths, "muge", [incoming])
    names = {Path(item.path).name for item in entry.custom_references}
    assert "front.jpg" in names
    assert any(name.startswith("front-") for name in names)


def test_validation_rejects_corrupt_and_tiny(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.jpg"
    _jpeg(tiny, size=(32, 32))
    qc = validate_character_image(tiny)
    assert qc.ok is False
    assert any("extremely_low_resolution" in err for err in qc.errors)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not-an-image")
    qc2 = validate_character_image(bad)
    assert qc2.ok is False
    phone = tmp_path / "phone.jpg"
    _jpeg(phone, size=(3024, 4032), color=(80, 80, 80))
    assert validate_character_image(phone).ok is True


def test_resolver_priority_and_provider_subset(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    generated = paths.generated_character_refs_dir() / "ref_birko.jpg"
    _jpeg(generated, color=(3, 3, 3))
    a = tmp_path / "front.jpg"
    b = tmp_path / "three_quarter.jpg"
    c = tmp_path / "full_body.jpg"
    _jpeg(a, color=(10, 0, 0))
    _jpeg(b, color=(0, 10, 0))
    _jpeg(c, color=(0, 0, 10))
    import_character_images(paths, "birko", [a, b, c])
    image_refs = resolve_character_references(paths, "birko", provider="openai", task="image")
    assert image_refs.mode is ReferenceMode.CUSTOM
    assert len(image_refs.paths) == 2
    assert image_refs.primary is not None
    assert image_refs.uploaded_to_provider is False
    i2v = resolve_character_references(paths, "birko", provider="runway", task="i2v")
    assert i2v.paths == []
    auto = resolve_character_references(paths, "kemal", provider="openai", task="image")
    assert auto.mode is ReferenceMode.AUTO_GENERATED


def test_custom_does_not_fallback_to_other_identity(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    _jpeg(paths.generated_character_refs_dir() / "ref_kemal.jpg", color=(4, 5, 6))
    src = tmp_path / "birko.jpg"
    _jpeg(src, color=(7, 8, 9))
    import_character_images(paths, "birko", [src])
    dest = paths.character_input_dir("birko") / "birko.jpg"
    dest.unlink()
    with pytest.raises(ValueError, match="refusing silent fallback"):
        resolve_character_references(paths, "birko", provider="openai", task="image")


def test_identity_version_stable_and_changes_with_hash(tmp_path: Path) -> None:
    path = _jpeg(tmp_path / "a.jpg", color=(1, 2, 3))
    digest = file_sha256(path)
    a = identity_version("birko", ReferenceMode.CUSTOM, [digest])
    b = identity_version("birko", ReferenceMode.CUSTOM, [digest])
    assert a == b
    assert a.startswith("birko:v2-custom-")
    other = identity_version("birko", ReferenceMode.CUSTOM, [digest + "ff"])
    assert other != a
    gen = identity_version("birko", ReferenceMode.AUTO_GENERATED, [digest])
    assert gen.startswith("birko:v1-generated-")


def test_v1_generated_refs_preserved_and_mismatch(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    generated = paths.generated_character_refs_dir() / "ref_birko.jpg"
    _jpeg(generated, color=(15, 15, 15))
    still = paths.scene_image_path("scene_0008")
    _jpeg(still, color=(16, 16, 16))
    src = tmp_path / "new_birko.jpg"
    _jpeg(src, color=(90, 10, 10))
    import_character_images(paths, "birko", [src])
    assert generated.is_file()
    script = build_birko_script(project_id="demo_chars")
    plan = compile_drama_scene_plan(script)
    mismatch = detect_identity_mismatch(paths, plan)
    assert mismatch is not None
    assert mismatch.code == IDENTITY_MISMATCH
    assert "birko" in mismatch.characters
    allowed = detect_identity_mismatch(paths, plan, allow_identity_mix=True)
    assert allowed is None
    rows = plan_character_migration(paths, plan)
    birko_rows = [row for row in rows if "birko" in row.characters]
    assert birko_rows
    assert any(row.regeneration_required for row in birko_rows)


def test_custom_skips_identity_sheet_generation(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    src = tmp_path / "front.jpg"
    _jpeg(src)
    import_character_images(paths, "birko", [src])
    assert should_generate_identity_sheet(paths, "birko") is False
    assert should_generate_identity_sheet(paths, "kemal") is True
    script = build_birko_script(project_id="demo_chars")
    plan = compile_drama_scene_plan(script)
    jobs, _cfg = plan_drama_visual_jobs(paths, plan)
    ref_ids = {job.job_id for job in jobs if job.kind == "character_ref"}
    assert "ref_birko" not in ref_ids
    assert "ref_kemal" in ref_ids


def test_no_network_activity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("network call is not allowed")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    paths = _project(tmp_path)
    src = tmp_path / "front.jpg"
    _jpeg(src, color=(22, 33, 44))
    import_character_images(paths, "muge", [src])
    resolve_character_references(paths, "muge", provider="openai", task="image")
    character_set_for_drama(paths)
    detect_identity_mismatch(paths)
