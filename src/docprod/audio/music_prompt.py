from __future__ import annotations

from docprod.audio.sound_models import MusicSection, SonicProfile

INSTRUMENTAL_CONSTRAINTS = (
    "INSTRUMENTAL ONLY. NO LYRICS. NO VOCALS. NO SPOKEN WORDS. "
    "Designed to sit beneath spoken documentary narration."
)


def lyria_prompt(section: MusicSection, profile: SonicProfile) -> str:
    duration = max(1.0, section.end - section.start)
    knots = _timing_blocks(section)
    avoid = ", ".join(
        part
        for part in [
            section.avoid,
            "lyrics",
            "vocals",
            "spoken words",
            "giant trailer climaxes",
            "fake archival police radio",
            "fake court audio",
        ]
        if part
    )
    return (
        f"Instrumental documentary score, no vocals.\n"
        f"{INSTRUMENTAL_CONSTRAINTS}\n"
        f"Channel profile: {profile.genre}; {profile.tone}; muted percussion; "
        f"controlled low pulse; room for speech.\n"
        f"Story purpose: {section.purpose}\n"
        f"Mood: {section.mood}\n"
        f"Tension trajectory: {section.tension_start:.2f} → peak {section.tension_peak:.2f} "
        f"→ {section.tension_end:.2f}\n"
        f"Energy trajectory: {section.energy_start:.2f} → {section.energy_end:.2f}\n"
        f"BPM range: {section.bpm_range}\n"
        f"Density: {section.density}; brightness: {section.brightness}; "
        f"tonal direction: {section.tonal_direction}\n"
        f"Instrumentation: {section.instrumentation}\n"
        f"Transition in: {section.transition_in}; out: {section.transition_out}\n"
        f"Approximate duration: {duration:.0f} seconds.\n"
        f"Avoid: {avoid}\n"
        f"Structure (creative guidance, not frame-accurate):\n{knots}"
    )


def _timing_blocks(section: MusicSection) -> str:
    duration = max(8.0, section.end - section.start)
    b = duration * 0.28
    c = duration * 0.62
    d = duration * 0.82
    e = duration
    return (
        f"0:00–{_fmt(b)}\n"
        f"Sparse {section.mood}, density {section.density}, energy {section.energy_start:.2f}.\n"
        f"{_fmt(b)}–{_fmt(c)}\n"
        f"Introduce restrained motion as tension moves toward {section.tension_peak:.2f}.\n"
        f"{_fmt(c)}–{_fmt(d)}\n"
        f"Hold investigative pulse while leaving room for narration.\n"
        f"{_fmt(d)}–{_fmt(e)}\n"
        f"Recede toward energy {section.energy_end:.2f} for the section close."
    )


def _fmt(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60}:{total % 60:02d}"
