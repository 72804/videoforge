from __future__ import annotations

from dataclasses import dataclass

from docprod.audio.script import tokenize_display
from docprod.drama import DEFAULT_PROJECT_ID
from docprod.models.enums import Mood, TransitionType, VisualEffect
from docprod.writing.models import (
    WORDS_PER_MINUTE,
    NarrationBeat,
    NarrationScript,
    StoryChapter,
    StoryOutline,
)

CINEMATIC_PREFIX = (
    "Single photorealistic cinematic still, one camera, one coherent moment, "
    "Turkish neighborhood realism, 35mm grain, natural light, not glossy ad. "
)

KEMAL_LOOK = (
    "Baby Kemal: about 40, thinning dark hair, modest mustache, worn undershirt "
    "or cheap collared shirt, quiet trusting face that notices more than it shows."
)
BIRKO_LOOK = (
    "Hain Birko: about 35, gelled dark hair, thin gold chain, sharp polo, "
    "annoyingly confident, behaves as if every room belongs to him."
)
MUGE_LOOK = (
    "Müge: about 32, dark hair loosely tied, small gold studs, bored intelligence, "
    "makes her own bad decisions, not a prop."
)


def still(*parts: str) -> str:
    return CINEMATIC_PREFIX + " ".join(part.strip() for part in parts if part.strip())


@dataclass(frozen=True)
class DramaBeatSpec:
    beat_id: str
    chapter_id: str
    purpose: str
    narration: str
    visual_intent: str
    image_prompt: str
    mood: Mood
    effect: VisualEffect
    transition: TransitionType
    title_card: str | None = None
    sting: str | None = None
    characters: tuple[str, ...] = ()
    sfx: str | None = None


CHAPTERS = (
    StoryChapter(
        chapter_id="ch_names",
        title="İki İsim",
        purpose="cold open, Kemal/Müge, first Kemal’e yaz",
        beat_ids=["b01", "b02", "b03", "b03b", "b04", "b05", "b06", "b07"],
    ),
    StoryChapter(
        chapter_id="ch_inside",
        title="Birko İçeride",
        purpose="stairs, perfume, gossip, earring",
        beat_ids=["b08", "b09", "b10", "b11", "b12", "b13", "b13b"],
    ),
    StoryChapter(
        chapter_id="ch_ledger",
        title="Hesap Kapanır",
        purpose="confrontation and bakkal payoff",
        beat_ids=["b14", "b15", "b15b", "b16", "b17", "b18"],
    ),
)

BEATS: tuple[DramaBeatSpec, ...] = (
    DramaBeatSpec(
        beat_id="b01",
        chapter_id="ch_names",
        purpose="cold_open_ledger",
        narration="Mahallede sır tutulmaz. Bakkal defterine yazılır.",
        visual_intent="Cold open: morning bakkal ledger",
        image_prompt=still(
            "close three-quarter of a worn Turkish grocery counter at morning,",
            "open notebook ledger with unreadable scribbles, pencil, sun stripe,",
            "no people, no readable words, one still-life composition.",
        ),
        mood=Mood.mysterious,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        sfx="bakkal_ambience",
    ),
    DramaBeatSpec(
        beat_id="b02",
        chapter_id="ch_names",
        purpose="cold_open_names",
        narration=(
            "O yaz defterde iki isim yan yana gelmeye başladı: "
            "Hain Birko harcıyor, Baby Kemal ödüyordu."
        ),
        visual_intent="Same bakkal, different angle: two men, spend vs pay",
        image_prompt=still(
            "wide interior grocery, morning, from behind the counter.",
            BIRKO_LOOK,
            "taking a bottle without looking at the shopkeeper.",
            KEMAL_LOOK,
            "quietly placing cash on the far end of the same counter,",
            "two men, deep staging, no readable text.",
        ),
        mood=Mood.ominous,
        effect=VisualEffect.slow_pull_out,
        transition=TransitionType.cut,
        characters=("birko", "kemal"),
        sfx="bakkal_ambience",
    ),
    DramaBeatSpec(
        beat_id="t01",
        chapter_id="ch_names",
        purpose="chapter_title",
        narration="",
        visual_intent="Dark title card: İki İsim",
        image_prompt="",
        mood=Mood.ominous,
        effect=VisualEffect.none,
        transition=TransitionType.dip_to_black,
        title_card="İki İsim",
        sting="short whoosh into title",
    ),
    DramaBeatSpec(
        beat_id="b03",
        chapter_id="ch_names",
        purpose="kemal_home",
        narration="Baby Kemal üç katlı binanın en sakin adamıydı.",
        visual_intent="Kemal at home with tea",
        image_prompt=still(
            "medium interior, small kitchen table at dusk, hanging bulb.",
            KEMAL_LOOK,
            "tulip tea glass, sugar bowl, speaking calmly toward off-frame,",
            "one person only.",
        ),
        mood=Mood.sad,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("kemal",),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b03b",
        chapter_id="ch_names",
        purpose="kemal_habit",
        narration=(
            "Çayını şekerli içer, borcunu gününde kapatır, "
            "Müge’ye her akşam aynı şeyi söylerdi:"
        ),
        visual_intent="Kemal pouring sugar, same kitchen, new angle",
        image_prompt=still(
            "close three-quarter at the table, dusk, different axis from the medium kitchen shot.",
            KEMAL_LOOK,
            "dropping sugar into tea, mouth about to speak,",
            "one person only.",
        ),
        mood=Mood.sad,
        effect=VisualEffect.pan_right,
        transition=TransitionType.cut,
        characters=("kemal",),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b04",
        chapter_id="ch_names",
        purpose="yarin_da_boyle",
        narration="“Yarın da böyle.”",
        visual_intent="Close on the tea as the daily line lands",
        image_prompt=still(
            "macro-close tabletop, tulip tea glass, two sugar cubes, chipped saucer,",
            "no faces, dusk window in soft bokeh, one still-life, no text.",
        ),
        mood=Mood.sad,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b05",
        chapter_id="ch_names",
        purpose="muge_bored",
        narration=(
            "Müge’nin sorunu da tam buydu. Yarın gerçekten hep böyle geliyordu."
        ),
        visual_intent="Müge bored at the window",
        image_prompt=still(
            "over-shoulder interior, tungsten lamp.",
            MUGE_LOOK,
            "her own hand on a lace curtain, bored, street bokeh below,",
            "one woman only, no other figures.",
        ),
        mood=Mood.mysterious,
        effect=VisualEffect.pan_left,
        transition=TransitionType.cut,
        characters=("muge",),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b06",
        chapter_id="ch_names",
        purpose="birko_arrives",
        narration=(
            "Birko mahalleye geldiğinde kimse onu davet etmemişti. "
            "Ama üç gün içinde bakkalda kendi sandalyesi varmış gibi oturuyordu."
        ),
        visual_intent="Birko occupying a bakkal chair as if invited",
        image_prompt=still(
            "wide-from-doorway afternoon grocery, plastic chair beside the counter.",
            BIRKO_LOOK,
            "sitting as if the chair is his, one ankle crossed, occupying the aisle,",
            "shopkeeper small in frame, two people, no readable labels.",
        ),
        mood=Mood.ominous,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("birko",),
        sfx="bakkal_ambience",
    ),
    DramaBeatSpec(
        beat_id="b07",
        chapter_id="ch_names",
        purpose="o_oder_setup",
        narration="Bir kola aldı. “Kemal’e yaz.” Bakkal baktı. Birko göz kırptı. “O öder.”",
        visual_intent="Cola on the counter, wink, first Kemal’e yaz",
        image_prompt=still(
            "tight counter close-up, three-quarter on the customer, afternoon.",
            BIRKO_LOOK,
            "cola bottle on the wood, winking, pencil hovering over unreadable paper,",
            "shopkeeper facing him, two people, no readable text.",
        ),
        mood=Mood.chaotic,
        effect=VisualEffect.documentary_handheld,
        transition=TransitionType.cut,
        characters=("birko",),
        sfx="cola_set",
    ),
    DramaBeatSpec(
        beat_id="t02",
        chapter_id="ch_inside",
        purpose="chapter_title",
        narration="",
        visual_intent="Dark title card: Birko İçeride",
        image_prompt="",
        mood=Mood.tense,
        effect=VisualEffect.none,
        transition=TransitionType.dip_to_black,
        title_card="Birko İçeride",
        sting="short impact sting",
    ),
    DramaBeatSpec(
        beat_id="b08",
        chapter_id="ch_inside",
        purpose="stairs_knowledge",
        narration=(
            "Sonra Birko merdivenlerde fazla görünmeye başladı. "
            "Müge’nin çayını naneli içtiğini biliyordu. "
            "Üçüncü basamağın gıcırdadığını da."
        ),
        visual_intent="Birko on the stair landing, too at home",
        image_prompt=still(
            "low-angle stairwell, side window light, peeling paint.",
            BIRKO_LOOK,
            "sitting on a landing as if he lives there, one foot on the third step,",
            "one man only, empty stairs below.",
        ),
        mood=Mood.tense,
        effect=VisualEffect.pan_left,
        transition=TransitionType.cut,
        characters=("birko",),
        sfx="stairwell_tone",
    ),
    DramaBeatSpec(
        beat_id="b09",
        chapter_id="ch_inside",
        purpose="perfume",
        narration=(
            "Kemal bir akşam eve geldiğinde mutfakta Birko’nun parfümünü kokladı. "
            "“Birko mu geldi?”"
        ),
        visual_intent="Kemal in the kitchen doorway, catching perfume",
        image_prompt=still(
            "kitchen doorway frame, hanging bulb, night.",
            KEMAL_LOOK,
            "stopped mid-step smelling the air, one person only, tense pause.",
        ),
        mood=Mood.ominous,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("kemal",),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b10",
        chapter_id="ch_inside",
        purpose="boya_excuse",
        narration=(
            "Müge pencereyi açtı. “Boya kokusu.” Ev sekiz yıldır boyanmamıştı."
        ),
        visual_intent="Müge opening the window with the paint excuse",
        image_prompt=still(
            "from inside the kitchen toward the window, night air.",
            MUGE_LOOK,
            "pushing the sash up, face half-turned, unbothered,",
            "one woman only, no extra figures.",
        ),
        mood=Mood.tense,
        effect=VisualEffect.pan_right,
        transition=TransitionType.cut,
        characters=("muge",),
        sfx="window_open",
    ),
    DramaBeatSpec(
        beat_id="b11",
        chapter_id="ch_inside",
        purpose="sugar",
        narration="Kemal hiçbir şey söylemedi. Çayına bir şeker daha attı.",
        visual_intent="Kemal adding another sugar cube, saying nothing",
        image_prompt=still(
            "close tabletop from a new angle, Kemal's hand dropping a sugar cube",
            "into a tulip glass, his mouth closed, night kitchen edge in bokeh.",
            KEMAL_LOOK,
            "cropped at the chest, one person.",
        ),
        mood=Mood.sad,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("kemal",),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b12",
        chapter_id="ch_inside",
        purpose="gossip",
        narration=(
            "Sonra mahalle konuşmaya başladı. Salı günü. Küpe. "
            "Merdivendeki kahkaha. Kemal işteyken açılan kapı."
        ),
        visual_intent="Neighbors whispering in a tiny elevator",
        image_prompt=still(
            "tight scratched-metal elevator, sickly fluorescent.",
            "two older neighbors leaning together whispering, mouths close,",
            "no third person, no extra crowd, no readable signs.",
        ),
        mood=Mood.chaotic,
        effect=VisualEffect.documentary_handheld,
        transition=TransitionType.cut,
        sfx="elevator_tone",
    ),
    DramaBeatSpec(
        beat_id="b13",
        chapter_id="ch_inside",
        purpose="earring",
        narration=(
            "Müge artık saklamıyordu da. Küpeyi aynanın karşısında kendi taktı."
        ),
        visual_intent="Müge putting on the earring herself",
        image_prompt=still(
            "bathroom mirror close-up, cheap tiles.",
            MUGE_LOOK,
            "fastening a small gold earring herself, half her face in the glass,",
            "one person, no other figures in the reflection.",
        ),
        mood=Mood.tense,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("muge",),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b13b",
        chapter_id="ch_inside",
        purpose="muge_decision",
        narration=(
            "Birko onu zorlamamıştı. Karar kötü olabilir; yine de karar onundu."
        ),
        visual_intent="Müge leaving the mirror, owning the choice",
        image_prompt=still(
            "bathroom doorway looking back at the mirror, cheap tiles, new angle.",
            MUGE_LOOK,
            "turning away after putting the earring on, chin set,",
            "one person, empty hallway behind her.",
        ),
        mood=Mood.tense,
        effect=VisualEffect.slow_pull_out,
        transition=TransitionType.cut,
        characters=("muge",),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="t03",
        chapter_id="ch_ledger",
        purpose="chapter_title",
        narration="",
        visual_intent="Dark title card: Hesap Kapanır",
        image_prompt="",
        mood=Mood.tense,
        effect=VisualEffect.none,
        transition=TransitionType.dip_to_black,
        title_card="Hesap Kapanır",
        sting="short impact sting",
    ),
    DramaBeatSpec(
        beat_id="b14",
        chapter_id="ch_ledger",
        purpose="door",
        narration="Kemal gerçeği yine bir kahkahadan öğrendi. Kapıyı açtı.",
        visual_intent="Kemal opening the apartment door onto the laugh",
        image_prompt=still(
            "night corridor, apartment door swinging inward, warm interior spill.",
            KEMAL_LOOK,
            "hand on the handle, entering, one man in the corridor,",
            "no crowd.",
        ),
        mood=Mood.tense,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("kemal",),
        sfx="stairwell_tone",
    ),
    DramaBeatSpec(
        beat_id="b15",
        chapter_id="ch_ledger",
        purpose="confrontation",
        narration=(
            "Birko içeride, kendi eviymiş gibi rahattı. Müge kaçmadı. "
            "Birko yumruk bekledi. Kemal sadece başını salladı."
        ),
        visual_intent="Birko comfortable inside; Müge stands; Kemal calm",
        image_prompt=still(
            "narrow apartment interior, eye-level, overhead bulb, cracked plaster.",
            BIRKO_LOOK,
            "too comfortable on a sofa-edge.",
            MUGE_LOOK,
            "standing her ground, not hiding.",
            KEMAL_LOOK,
            "in the doorway, head slightly bowed as if nodding, three people only.",
        ),
        mood=Mood.tense,
        effect=VisualEffect.documentary_handheld,
        transition=TransitionType.cut,
        characters=("birko", "muge", "kemal"),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b15b",
        chapter_id="ch_ledger",
        purpose="take_the_debt",
        narration="“Kararın buysa gidin.” Sonra Birko’ya baktı. “Ama hesabını da götür.”",
        visual_intent="Kemal to Birko: take the debt with you",
        image_prompt=still(
            "tight two-shot, doorway, overhead bulb, different axis from the three-shot.",
            KEMAL_LOOK,
            "calm, looking at Birko, not raising a fist.",
            BIRKO_LOOK,
            "still seated, waiting for a punch that does not come, two people.",
        ),
        mood=Mood.ominous,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("kemal", "birko"),
        sfx="apartment_tone",
    ),
    DramaBeatSpec(
        beat_id="b16",
        chapter_id="ch_ledger",
        purpose="kemale_yaz_callback",
        narration=(
            "Ertesi sabah Birko bakkala girdi. Tezgâha kola bıraktı. “Kemal’e yaz.”"
        ),
        visual_intent="Morning: Birko sets cola down, same line as before, new angle",
        image_prompt=still(
            "low counter-height shot, morning side light, opposite side from the wink shot.",
            BIRKO_LOOK,
            "setting a plastic cola bottle on the wood with casual ownership,",
            "mouth mid-order, shopkeeper facing him, two people, no readable labels.",
        ),
        mood=Mood.ominous,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        characters=("birko",),
        sfx="cola_set",
    ),
    DramaBeatSpec(
        beat_id="b17",
        chapter_id="ch_ledger",
        purpose="ledger_closes",
        narration="Bakkal defteri kapattı. “Kemal artık seni ödemiyor.”",
        visual_intent="Grocer slamming the ledger shut",
        image_prompt=still(
            "telephoto from behind the counter, shopkeeper's weathered hand shutting",
            "a closed notebook, morning hard side light.",
            BIRKO_LOOK,
            "cropped at the chest across the counter, two people, no readable text.",
        ),
        mood=Mood.urgent,
        effect=VisualEffect.documentary_handheld,
        transition=TransitionType.cut,
        characters=("birko",),
        sfx="ledger_close",
    ),
    DramaBeatSpec(
        beat_id="b18",
        chapter_id="ch_ledger",
        purpose="own_pocket",
        narration=(
            "Birko o gün ilk kez cebine uzandı. "
            "Mahalle aşkı konuşur. Ama hesabı herkes kendi öder."
        ),
        visual_intent="Birko reaching into his own pocket; street beyond",
        image_prompt=still(
            "medium shot from the shop doorway looking in, late morning.",
            BIRKO_LOOK,
            "reluctantly reaching into his own trouser pocket, not cartoonish,",
            "cola still on the counter, shopkeeper waiting, two people,",
            "street visible behind camera implied, no readable text.",
        ),
        mood=Mood.hopeful,
        effect=VisualEffect.slow_pull_out,
        transition=TransitionType.cut,
        characters=("birko",),
        sfx="pocket",
    ),
)

LOGLINE = (
    "Birko her şeyi Kemal’e yazdırır; Müge kendi kararını verir; "
    "bakkal defteri hesabı kapatır."
)

CANONICAL_NARRATION = " ".join(
    beat.narration.strip() for beat in BEATS if beat.narration.strip()
)

CHARACTER_REF_PLAN = (
    {
        "id": "ref_kemal",
        "character": "Baby Kemal",
        "role": "generation input only; never a timeline visual",
        "prompt": still(
            "chest-up identity portrait, even window light, blank apartment wall.",
            KEMAL_LOOK,
            "neutral expression, looking slightly off camera, one person only.",
        ),
    },
    {
        "id": "ref_birko",
        "character": "Hain Birko",
        "role": "generation input only; never a timeline visual",
        "prompt": still(
            "chest-up identity portrait, even window light, blank apartment wall.",
            BIRKO_LOOK,
            "half-smile, looking into lens, one person only.",
        ),
    },
    {
        "id": "ref_muge",
        "character": "Müge",
        "role": "generation input only; never a timeline visual",
        "prompt": still(
            "chest-up identity portrait, even window light, blank apartment wall.",
            MUGE_LOOK,
            "unreadable calm, looking slightly off camera, one person only.",
        ),
    },
)


def build_birko_script(*, project_id: str = DEFAULT_PROJECT_ID) -> NarrationScript:
    spoken = [beat for beat in BEATS if beat.narration.strip()]
    full = CANONICAL_NARRATION
    words = len(tokenize_display(full))
    minutes = round(words / WORDS_PER_MINUTE, 2)
    chapters = []
    for chapter in CHAPTERS:
        chapters.append(
            chapter.model_copy(
                update={
                    "beat_ids": [
                        beat.beat_id for beat in spoken if beat.chapter_id == chapter.chapter_id
                    ]
                }
            )
        )
    return NarrationScript(
        project_id=project_id,
        language="tr",
        outline=StoryOutline(logline=LOGLINE, chapters=chapters),
        beats=[
            NarrationBeat(
                beat_id=beat.beat_id,
                narration=beat.narration,
                chapter=beat.chapter_id,
                purpose=beat.purpose,
            )
            for beat in spoken
        ],
        full_narration=full,
        word_count=words,
        estimated_runtime_minutes=minutes,
        writer_model="custom_drama_local_v3_exact",
        request_hash="custom-drama-local-v3-exact",
    )
