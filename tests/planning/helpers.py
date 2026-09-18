from __future__ import annotations

from docprod.models.script import NarrationScript, Utterance, WordTiming
from docprod.planning.models import round_time
from docprod.planning.profile import ScenePlannerProfile

PROFILE = ScenePlannerProfile()


def words_for(text: str, start: float, end: float) -> list[WordTiming]:
    tokens = text.split()
    span = end - start
    out: list[WordTiming] = []
    cursor = start
    weight = max(1, len(tokens))
    for i, token in enumerate(tokens):
        piece = span / weight
        word_end = end if i == len(tokens) - 1 else cursor + piece
        out.append(WordTiming(word=token, start=round_time(cursor), end=round_time(word_end)))
        cursor = word_end
    return out


def utterance(
    uid: str,
    text: str,
    start: float,
    end: float,
    *,
    timed: bool = True,
) -> Utterance:
    return Utterance(
        id=uid,
        text=text,
        start=start,
        end=end,
        words=words_for(text, start, end) if timed else [],
    )


def script_from(*utts: Utterance, language: str = "en") -> NarrationScript:
    return NarrationScript(
        language=language,
        full_text=" ".join(item.text for item in utts),
        utterances=list(utts),
    )
