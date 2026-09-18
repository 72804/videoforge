from __future__ import annotations

from docprod.models.script import NarrationScript, Utterance, WordTiming
from docprod.planning.models import round_time


def _word_timings(text: str, start: float, end: float) -> list[WordTiming]:
    tokens = text.split()
    if not tokens:
        return []
    weights = [max(1, len(token)) for token in tokens]
    total = sum(weights)
    span = end - start
    cursor = start
    words: list[WordTiming] = []
    for index, token in enumerate(tokens):
        piece = span * (weights[index] / total)
        word_end = end if index == len(tokens) - 1 else cursor + piece
        word_end = min(end, max(word_end, cursor + 0.04))
        if word_end <= cursor:
            word_end = min(end, cursor + 0.04)
        words.append(
            WordTiming(
                word=token,
                start=round_time(cursor),
                end=round_time(word_end),
            )
        )
        cursor = word_end
    return words


def _utterance(
    uid: str,
    text: str,
    start: float,
    end: float,
    *,
    with_words: bool,
) -> Utterance:
    return Utterance(
        id=uid,
        text=text,
        start=round_time(start),
        end=round_time(end),
        words=_word_timings(text, start, end) if with_words else [],
    )


def build_narration_demo(*, language: str, project_title: str | None = None) -> NarrationScript:
    """Fictional ~45–60s narration fixture. No real case material."""
    lang = language.strip().lower().split("-")[0]
    if lang == "tr":
        return _turkish_fixture()
    return _english_fixture()


def _turkish_fixture() -> NarrationScript:
    rows: list[tuple[str, str, float, bool, float]] = [
        # id, text, duration, words, gap_after
        (
            "utt_0001",
            "İstanbul'daki tren istasyonu akşam saatlerinde neredeyse boştu.",
            4.2,
            True,
            0.0,
        ),
        (
            "utt_0002",
            "Koyu paltolu bir adam son vagondan indi.",
            3.0,
            True,
            0.35,
        ),
        (
            "utt_0003",
            "Bankın üzerinde unutulmuş bir evrak çantası duruyordu.",
            3.4,
            True,
            0.0,
        ),
        (
            "utt_0004",
            "Adam çantayı aldı ve peron boyunca yürüdü.",
            3.2,
            True,
            0.0,
        ),
        (
            "utt_0005",
            "İçinden bir tomar para ve yırtık bir fotoğraf çıktı.",
            3.5,
            False,
            2.5,
        ),
        ("utt_0006", "Durdu.", 1.1, True, 0.0),
        (
            "utt_0007",
            (
                "İstasyonun kuzey çıkışına doğru koşarak gitti, telefonunu açtı, "
                "polise haber verdi ve çantanın içindeki raporu yüksek sesle okumaya "
                "başladı çünkü kimse geri dönmemişti."
            ),
            10.4,
            True,
            0.0,
        ),
        (
            "utt_0008",
            "Polis memurları beş dakika sonra perona girdi.",
            3.6,
            True,
            0.0,
        ),
        (
            "utt_0009",
            "Gazetedeki küçük bir haber kupürü delil gibi duruyordu.",
            3.4,
            True,
            0.0,
        ),
        (
            "utt_0010",
            "Haritada işaretli rota kuzey kapısına gidiyordu.",
            3.2,
            False,
            0.0,
        ),
        (
            "utt_0011",
            "Adam kaçan birini kovaladı ama kalabalık peronda iz kayboldu.",
            3.8,
            True,
            0.0,
        ),
        (
            "utt_0012",
            "Araba istasyon önünde ani fren yaptı.",
            2.8,
            True,
            0.0,
        ),
        (
            "utt_0013",
            "Mahkeme tutanağı henüz yoktu; sadece o rapor vardı.",
            3.4,
            True,
            0.0,
        ),
    ]
    return _from_rows(rows, language="tr")


def _english_fixture() -> NarrationScript:
    rows: list[tuple[str, str, float, bool, float]] = [
        (
            "utt_0001",
            "The train station in the city was almost empty in the evening.",
            4.2,
            True,
            0.0,
        ),
        (
            "utt_0002",
            "A man in a dark coat stepped off the last car.",
            3.0,
            True,
            0.35,
        ),
        (
            "utt_0003",
            "An abandoned briefcase sat upright on the bench.",
            3.4,
            True,
            0.0,
        ),
        (
            "utt_0004",
            "The man grabbed the case and walked along the platform.",
            3.2,
            True,
            0.0,
        ),
        (
            "utt_0005",
            "Inside he found a stack of money and a torn photograph.",
            3.5,
            False,
            2.5,
        ),
        ("utt_0006", "He stopped.", 1.1, True, 0.0),
        (
            "utt_0007",
            (
                "He ran toward the north exit of the station, opened his phone, "
                "called the police, and read the report inside the case out loud "
                "because nobody had come back for it."
            ),
            10.4,
            True,
            0.0,
        ),
        (
            "utt_0008",
            "Police officers entered the platform five minutes later.",
            3.6,
            True,
            0.0,
        ),
        (
            "utt_0009",
            "A newspaper clipping looked like evidence on the bench.",
            3.4,
            True,
            0.0,
        ),
        (
            "utt_0010",
            "The map marked a route toward the north exit.",
            3.2,
            False,
            0.0,
        ),
        (
            "utt_0011",
            "The man chased someone through the crowd but lost the trail.",
            3.8,
            True,
            0.0,
        ),
        (
            "utt_0012",
            "A car slammed its brakes in front of the station.",
            2.8,
            True,
            0.0,
        ),
        (
            "utt_0013",
            "There was no court record yet, only that report.",
            3.4,
            True,
            0.0,
        ),
    ]
    return _from_rows(rows, language="en")


def _from_rows(
    rows: list[tuple[str, str, float, bool, float]],
    *,
    language: str,
) -> NarrationScript:
    utterances: list[Utterance] = []
    cursor = 0.0
    texts: list[str] = []
    for uid, text, duration, with_words, gap_after in rows:
        start = cursor
        end = cursor + duration
        utterances.append(_utterance(uid, text, start, end, with_words=with_words))
        texts.append(text)
        cursor = end + gap_after
    return NarrationScript(
        language=language,
        full_text=" ".join(texts),
        utterances=utterances,
    )
