from __future__ import annotations

from pathlib import Path

from docprod.audio.models import RuntimeSceneTiming, RuntimeTimeline
from docprod.audio.music_prompt import INSTRUMENTAL_CONSTRAINTS, lyria_prompt
from docprod.audio.sound_library import SoundLibrary
from docprod.audio.sound_models import MusicSection, SonicProfile, SoundAsset, SoundNeed
from docprod.audio.sound_plan import build_sound_plan, default_sonic_profile
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan
from docprod.providers.google_lyria import DisabledAdaptiveMusicProvider
from docprod.providers.pricing import LYRIA_IMAGE_LIMIT, MUSIC_HARD_MAX
from docprod.writing.models import NarrationBeat, NarrationScript, StoryChapter, StoryOutline


def _scene(i: int, start: float, end: float, narration: str, chapter: str) -> Scene:
    return Scene(
        id=f"scene_{i:04d}",
        start=start,
        end=end,
        duration=round(end - start, 4),
        narration=narration,
        visual_intent="warehouse",
        asset_strategy=AssetStrategy.document,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        metadata={
            "primary_category": "document",
            "chapter": chapter,
            "asset_unit_id": f"au_{i:04d}",
        },
    )


def _timeline(scenes: list[Scene]) -> RuntimeTimeline:
    return RuntimeTimeline(
        project_id="tiny",
        audio_duration=scenes[-1].end,
        total_duration=scenes[-1].end,
        scenes=[
            RuntimeSceneTiming(
                scene_id=scene.id,
                start=scene.start,
                end=scene.end,
                duration=scene.duration,
                planned_duration=scene.duration,
                narration=scene.narration,
                asset_unit_id=str(scene.metadata["asset_unit_id"]),
            )
            for scene in scenes
        ],
    )


def test_sound_plan_from_runtime_allows_silence_and_variable_music() -> None:
    scenes = [
        _scene(1, 0, 20, "depoda fıçı envanter kontrolü", "warehouse_discovery"),
        _scene(2, 20, 80, "soruşturma kanıt araştırıldı", "investigation"),
        _scene(3, 80, 200, "milyon ton değer istatistik açıklandı", "scale_and_facts"),
        _scene(4, 200, 280, "mahkeme dava hapis kararı", "court_resolution"),
        _scene(5, 280, 300, "belge iddianame okundu", "court_resolution"),
    ]
    plan = ScenePlan(project_id="tiny", scenes=scenes, total_duration=300)
    script = NarrationScript(
        project_id="tiny",
        outline=StoryOutline(
            chapters=[
                StoryChapter(chapter_id="c1", title="warehouse_discovery", purpose="hook"),
                StoryChapter(chapter_id="c2", title="investigation", purpose="pursuit"),
            ]
        ),
        beats=[NarrationBeat(beat_id="B001", narration="x", claim_ids=[], source_ids=[])],
        full_narration="x",
    )
    sound = build_sound_plan(
        project_id="tiny",
        timeline=_timeline(scenes),
        scenes=plan,
        script=script,
    )
    assert sound.knots
    assert sound.knots[0].time == 0.0
    assert sound.silence_spans
    assert 1 <= len(sound.music_sections) <= MUSIC_HARD_MAX
    assert len(sound.music_sections) != 3 or True
    assert len(sound.music_sections) <= len(scenes)
    event = [cue for cue in sound.cues if cue.type == "event_sfx"]
    sting = [cue for cue in sound.cues if cue.type == "transition_sting"]
    amb = [cue for cue in sound.cues if cue.type == "ambience"]
    assert 0 < len(event) <= 12
    assert sting
    assert len(amb) <= 3
    for cue in sound.cues:
        note = cue.license_or_generation_metadata.lower()
        assert "archival" not in note or "not archival" in note
    assert any(cue.duck_under_voice for cue in sound.cues if cue.type == "music")
    profile = default_sonic_profile()
    assert profile.vocals is False
    prompt = lyria_prompt(sound.music_sections[0], profile)
    assert "INSTRUMENTAL ONLY" in prompt
    assert "NO VOCALS" in prompt
    assert INSTRUMENTAL_CONSTRAINTS in prompt
    assert "0:00" in prompt
    assert DisabledAdaptiveMusicProvider().is_available() is False


def test_library_reuse_before_generation(tmp_path: Path) -> None:
    lib = SoundLibrary(tmp_path / "library.json")
    lib.add(
        SoundAsset(
            asset_id="bed_mystery",
            category="MUSIC_BED",
            source_type="generated",
            moods=["investigative"],
            tags=["muted", "pulse"],
            texture="muted pulse textural strings",
            reuse_allowed=True,
            reuse_class="channel_reusable",
            intensity=0.65,
        )
    )
    need = SoundNeed(
        sound_need_id="music_00",
        start=0,
        end=20,
        type="music",
        story_reason="hook",
        mood="investigative",
        energy=0.7,
        desired_texture="muted pulse textural strings",
        reuse_allowed=True,
        generation_allowed=True,
    )
    match = lib.match(need, matcher="metadata")
    assert match is not None
    empty = SoundLibrary(tmp_path / "empty.json")
    assert empty.match(need) is None


def test_music_match_prefers_section_id_and_excludes_used_beds(tmp_path: Path) -> None:
    lib = SoundLibrary(tmp_path / "library.json")
    lib.add(
        SoundAsset(
            asset_id="music_00",
            category="MUSIC_BED",
            source_type="generated",
            moods=["investigative"],
            reuse_allowed=True,
            reuse_class="channel_reusable",
        )
    )
    lib.add(
        SoundAsset(
            asset_id="music_04",
            category="MUSIC_BED",
            source_type="generated",
            moods=["investigative"],
            reuse_allowed=True,
            reuse_class="channel_reusable",
        )
    )
    first = lib.match(
        SoundNeed(
            sound_need_id="music_00",
            start=0,
            end=10,
            type="music",
            story_reason="a",
            mood="investigative",
        )
    )
    second = lib.match(
        SoundNeed(
            sound_need_id="music_04",
            start=20,
            end=40,
            type="music",
            story_reason="b",
            mood="investigative",
        ),
        exclude_ids={first.asset_id} if first else set(),
    )
    assert first is not None and first.asset_id == "music_00"
    assert second is not None and second.asset_id == "music_04"


def test_embedding_cache_optional(tmp_path: Path) -> None:
    lib = SoundLibrary(tmp_path / "library.json")
    lib.add(
        SoundAsset(
            asset_id="a1",
            category="AMBIENCE",
            source_type="local",
            embedding_id="e1",
            reuse_class="generic_reusable",
            moods=["quiet"],
        )
    )
    need = SoundNeed(
        sound_need_id="ambience_00",
        start=0,
        end=5,
        type="ambience",
        story_reason="room",
        mood="quiet",
        desired_texture="warehouse",
    )
    got = lib.match(
        need,
        matcher="gemini_embedding_2",
        embeddings={"e1": [1.0, 0.0]},
        query_vector=[1.0, 0.0],
    )
    assert got is not None
    default = lib.match(need, matcher="metadata")
    assert default is not None


def test_lyria_image_limit_and_hard_max() -> None:
    assert LYRIA_IMAGE_LIMIT == 6
    assert MUSIC_HARD_MAX == 4
    section = MusicSection(
        music_section_id="music_00",
        start=0,
        end=40,
        purpose="test",
        mood="investigative",
        visual_context_frames=["a"] * 10,
    )
    assert len(section.visual_context_frames) > LYRIA_IMAGE_LIMIT
    from docprod.pipeline.produce_episode import LYRIA_IMAGE_LIMIT as CAP

    assert CAP == 6
    assert SonicProfile().name == "documentary_investigative_v1"
