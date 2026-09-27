from __future__ import annotations

from dataclasses import dataclass, field

from docprod.drama import DEFAULT_PROJECT_ID

REFS_RELATIVE = f"projects/{DEFAULT_PROJECT_ID}/artifacts/visuals/character_refs"

LOCKED_EPISODE_2_PREMISE = (
    "Birko invites everyone to Krispy Kreme, secretly tells each person that "
    "someone else is paying, then disappears when the huge bill arrives. "
    "Kemal gets stuck with the bill. "
    "HG knows what Birko has done and deliberately makes the situation worse for fun. "
    "Erni acts innocent while manipulating both sides. "
    "Musti rage-baits everyone and escalates the chaos. "
    "Müge mostly cares about who ordered the expensive box / expensive items. "
    "Ending: Birko is revealed outside the café casually eating the last donut."
)

LOCKED_EPISODE_2_ENDING = (
    "Birko is revealed outside the café casually eating the last donut."
)

EPISODE_2_SETTING = {
    "location": "Krispy Kreme café",
    "language": "tr",
    "primary_tone": "drama",
    "secondary_tone": "absurd / dark comedy generated naturally from character behavior",
    "cast": ("Birko", "Kemal", "Müge", "Erni", "HG", "Musti"),
    "situation": LOCKED_EPISODE_2_PREMISE,
    "conflict": "Payment trap; Kemal stuck with the bill; group chaos",
    "joke_event": "ENGINE_OWNED",
    "required_line": None,
    "required_prop": "ENGINE_OWNED after story generation",
    "ending": LOCKED_EPISODE_2_ENDING,
    "ending_options": ("locked_outside_donut_reveal",),
    "duration": "45-60s",
    "recommended_test_duration_seconds": (45, 60),
    "premise_locked": True,
    "structure_locked": False,
}

GROUP_DYNAMIC = (
    "Six distinct speaking rhythms. Comedy/drama from clash: Birko quiet schemer; "
    "Kemal unlucky good guy; Müge flirtatious materialist; Erni cute hidden manipulator; "
    "HG devilish chaos instigator; Musti young rage-bait gremlin. "
    "Nicknames and catchphrases recur occasionally, never spam."
)


@dataclass(frozen=True)
class BirkoCastMember:
    slug: str
    name: str
    display_name: str
    aliases: tuple[str, ...] = ()
    role_archetype: str = ""
    description: str = ""
    personality_traits: tuple[str, ...] = ()
    behavioral_quirks: tuple[str, ...] = ()
    catchphrases: tuple[str, ...] = ()
    relationships: dict[str, str] = field(default_factory=dict)
    appearance_notes: str = ""
    voice_notes: str = ""
    never_do: tuple[str, ...] = ()
    expected_ref_filenames: tuple[str, ...] = ()
    lock_if_ref_exists: bool = False
    always_locked: bool = False


BIRKO_CAST: tuple[BirkoCastMember, ...] = (
    BirkoCastMember(
        slug="birko",
        name="Birko",
        display_name="Birko",
        role_archetype="schemer / scammer / unreliable mastermind",
        description=(
            "Hain, dolandırıcı, fırsatçı. Az konuşur; kısa, alakasız, sinir bozucu cevaplar. "
            "Yakalanınca suçu kabul etmez, konuyu saptırır. Gereğinden emin. Kilolu, fiziksel "
            "eforda nefesi kesilir. Kötü niyeti bazen istemeden komik durur."
        ),
        personality_traits=(
            "manipulative",
            "dishonest",
            "opportunistic",
            "quiet",
            "deadpan",
            "greedy",
            "stubborn",
            "low-energy",
            "unexpectedly confident",
        ),
        behavioral_quirks=(
            "Ciddi sorulara tek kelimelik cevap verir.",
            "Bazen sadece 'dog' der.",
            "Bazen sadece 'zorsun' der.",
            "Fiziksel efor sonrası konuşurken nefesi kesilir.",
            "Bariz suçlu olsa bile sakin davranmaya çalışır.",
            "İnsanların neden kızdığını anlamıyormuş gibi yapar.",
        ),
        catchphrases=("dog", "zorsun"),
        relationships={
            "Kemal": (
                "Eski çocukluk arkadaşı. Birko'nun davranışları Kemal'i sık mağdur eder; "
                "eski dostluktan garip bir bağ kalır."
            ),
            "Müge": (
                "Karısı. Güven/romantizmden çok kaos, çıkar, kıskançlık ve karşılıklı manipülasyon."
            ),
        },
        appearance_notes=(
            "Preserve locked Birko identity. Heavy-set. Breathlessness as physical comedy; "
            "do not make every scene a weight joke."
        ),
        voice_notes=(
            "Ağır, rahat, biraz nefesli, heyecansız, deadpan. Kısa cevapları komik kılan "
            "düşük enerjili erkek sesi."
        ),
        never_do=(
            "Uzun ve samimi bir özür konuşması yapmak.",
            "Hemen suçunu kabul etmek.",
            "Karşılığında hiçbir şey almadan fedakârlık yapmak.",
            "Gereksiz yere uzun konuşmak.",
        ),
        expected_ref_filenames=("ref_birko.jpg",),
        always_locked=True,
    ),
    BirkoCastMember(
        slug="kemal",
        name="Kemal",
        display_name="Kemal",
        role_archetype="unlucky good guy / emotional center / frequent victim",
        description=(
            "İyi kalpli, saflığa yakın şans verir, sürekli haksızlığa uğrar. Sabırlıdır ama "
            "üst üste gelince patlar. Ara sıra sigara içer. Grubun vicdanlısı; saçmalığı ilk "
            "fark edenlerden."
        ),
        personality_traits=(
            "kind-hearted",
            "unlucky",
            "patient",
            "loyal",
            "frustrated",
            "relatively normal",
            "emotional",
            "forgiving",
        ),
        behavioral_quirks=(
            "Her şey kontrolden çıkınca bir süre sessizce izler.",
            "Sinirlenince grubun saçmalığını sorgular.",
            "Stresli anlarda ara sıra sigara içebilir.",
            "Birko'ya güvenmemesi gerektiğini bildiği halde bazen yine güvenir.",
        ),
        catchphrases=(),
        relationships={
            "Birko": (
                "Eski çocukluk arkadaşı. Birko'nun kim olduğunu bilir ama ortak geçmiş yüzünden "
                "tamamen kopamaz."
            ),
            "Müge": (
                "Eski hoşlandığı / geçmiş romantik bağ. Müge şu an Birko ile evli; bu geçmiş "
                "rahatsız, kıskanç veya komik durumlar yaratabilir."
            ),
        },
        appearance_notes="Preserve locked Kemal identity/reference images.",
        voice_notes=(
            "Normal genç yetişkin erkek sesi. Yorgun/bezmiş. Sinirlenince enerji yükselir. "
            "Grubun en doğal konuşanı."
        ),
        never_do=(
            "Bir arkadaşını sırf para için bilinçli şekilde dolandırmak.",
            "Birko kadar soğukkanlı hainlik yapmak.",
            "Açık bir haksızlığı tepkisiz kabullenmek.",
        ),
        expected_ref_filenames=("ref_kemal.jpg",),
        always_locked=True,
    ),
    BirkoCastMember(
        slug="muge",
        name="Müge",
        display_name="Müge",
        aliases=("Muge",),
        role_archetype="social manipulator / flirt / money-motivated wildcard",
        description=(
            "Aşırı flörtöz, sınır zorlar, ilgi ve lüks sever. Kişilik çoğu zaman yapmacık; "
            "ihtiyaca göre farklı yüz. İstediğinde manipülatif. Drama'dan bazen eğlenir."
        ),
        personality_traits=(
            "flirtatious",
            "materialistic",
            "charming",
            "manipulative",
            "dramatic",
            "socially confident",
            "opportunistic",
            "unpredictable",
        ),
        behavioral_quirks=(
            "Birinden bir şey isteyince aniden çok tatlı davranabilir.",
            "Para veya pahalı bir şey görünce tavrı değişebilir.",
            "Aynı olayın farklı kişilere farklı versiyonlarını anlatabilir.",
            "Tartışmada kendini masum göstermeye çalışabilir.",
        ),
        catchphrases=(),
        relationships={
            "Birko": "Evli. Kaotik, zaman zaman çıkar ilişkisine benzeyen dinamik.",
            "Kemal": (
                "Eski sevgili / geçmiş romantik ilişki. "
                "Birko'nun olduğu ortamda gerilim veya komedi."
            ),
        },
        appearance_notes=(
            "Current identity: user photo set. Primary is the close-up smile still "
            "(canonical ref_muge.jpg). Extra angle ref_muge_alt.jpg. "
            "V1 generated portrait archived as ref_muge_v1_archive.jpg — do not mix it "
            "into live identity (different face)."
        ),
        voice_notes=(
            "Kendinden emin, flörtöz, gerektiğinde aşırı tatlı; sinirlenince hızla sertleşen "
            "yetişkin kadın sesi."
        ),
        never_do=(
            "Para veya sosyal avantaj tamamen önemsizmiş gibi davranmak.",
            "Drama fırsatını fark etmemek.",
            "Çıkarı olmadan uzun süre tamamen saf/masum rolünde kalmak.",
        ),
        expected_ref_filenames=("ref_muge.jpg", "ref_muge_alt.jpg"),
        always_locked=True,
    ),
    BirkoCastMember(
        slug="erni",
        name="Erni",
        display_name="Erni",
        role_archetype='deceptively cute manipulator / "baby" character',
        description=(
            "Dışarıdan Barbie-benzeri, çiçek-böcek, saf ve sevimli; aslında sinsi ve hesapçı. "
            "Grubun baby'si gibi sunar, saf/aptal rolü oynar, herkese baby diye hitap eder. "
            "Küçümserken bile tatlı ton."
        ),
        personality_traits=(
            "cute",
            "deceptive",
            "playful",
            "feminine",
            "calculating",
            "mischievous",
            "observant",
            "passive-aggressive",
        ),
        behavioral_quirks=(
            "Ciddi tartışmanın ortasında bile 'baby' diyebilir.",
            "Kötü bir fikirden sonra masum görünmeye çalışır.",
            "Kendi manipülasyonunu hiç anlamamış gibi davranır.",
            "Kızdırırken tatlı sesini koruyabilir.",
        ),
        catchphrases=("Sen daha babysin.", "Baby...", "Baby yapma."),
        relationships={
            "Birko": "Genellikle 'Baby naber?' gibi aşırı rahat ve sevimli yaklaşır.",
            "Kemal": "Görünce abartılı 'Aaaa babyyyy!' diyebilir.",
            "Müge": "Müge drama çıkarınca 'Baby yapma.' diyebilir.",
        },
        appearance_notes=(
            "Barbie-inspired aesthetic without copying a copyrighted character. "
            "Bright, glamorous, playful; cute look vs mischievous behavior. Recurring identity."
        ),
        voice_notes=(
            "Barbie-doll, genç yetişkin kadın, yüksek/parlak/aşırı tatlı, kelimeleri uzatabilir. "
            "Masum tonun altında hafif alay."
        ),
        never_do=(
            "Sinsi tarafını doğrudan kabul etmek.",
            "Uzun süre tamamen ciddi konuşmak.",
            "'Baby' kelimesini hiç kullanmamak.",
            "Manipülasyonunun planlı olduğunu itiraf etmek.",
        ),
        expected_ref_filenames=("ref_erni.jpg",),
        lock_if_ref_exists=True,
    ),
    BirkoCastMember(
        slug="hg",
        name="HG",
        display_name="HG",
        aliases=("Hüseyin", "Huseyin", "şeytan", "seytan"),
        role_archetype="devil / chaos instigator / dark-humor character",
        description=(
            "İlk bakışta iyi, sakin, yardımsever; aslında en şeytani fikirler ondan. "
            "HG veya şeytan diye hitap edilir. Kaostan eğlenir, karanlık mizah, çabuk sinir, "
            "provoke eder, kötü fikirleri normal öneri gibi söyler, kışkırtır."
        ),
        personality_traits=(
            "funny",
            "dark",
            "evil",
            "provocative",
            "charismatic",
            "hot-tempered",
            "clever",
            "chaotic",
            "deceptive",
        ),
        behavioral_quirks=(
            "Çok kötü bir öneriyi sakin sesle sunabilir.",
            "İnsanları özel lakaplarla çağırır.",
            "Ortam yeterince kaotik değilse daha da karıştırır.",
            "Sinirlenince sakin rapper tavrı bir anda patlar.",
        ),
        catchphrases=("doggy",),
        relationships={
            "Birko": "Birko'ya 'Dayiiii!' diye seslenir.",
            "Kemal": "Kemal'e 'Kemalooom!' diye seslenir.",
            "Müge": "Müge'ye 'Bozuk pasta.' diye hitap eder.",
        },
        appearance_notes=(
            "Devilish energy without literal horns. Streetwear / rapper-adjacent can fit. "
            "Relaxed posture vs malicious ideas."
        ),
        voice_notes=(
            "Rapper-like, cool/relaxed, hafif karanlık/tehditkâr. Düşük tempo; sinirlenince "
            "hızlı ve sert erkek sesi."
        ),
        never_do=(
            "Kaos için mükemmel fırsatı kaçırmak.",
            "Kendisine 'şeytan' denmesine ciddi alınmak.",
            "Grubun uzun süre tamamen sakin kalmasına izin vermek.",
            "Kötü fikrinden suçluluk açıkça göstermek.",
        ),
        expected_ref_filenames=("ref_hg.jpg", "ref_HG.jpg", "ref_huseyin.jpg"),
        lock_if_ref_exists=True,
    ),
    BirkoCastMember(
        slug="musti",
        name="Musti",
        display_name="Musti",
        role_archetype="rage-bait chaos gremlin / youngest member",
        description=(
            "Berbat davranıp 'ben berbat biri değilim' diye savunur. Rage bait, genç, "
            "uzun kahkahada midem bulanır/kusabilir, garip sesler, hızlı konu değişimi, "
            "dağınık enerji. Sessizlikte anlamsız sesle bozar."
        ),
        personality_traits=(
            "annoying",
            "chaotic",
            "childish",
            "energetic",
            "provocative",
            "impulsive",
            "loud",
            "absurd",
            "shameless",
        ),
        behavioral_quirks=(
            "Rastgele garip sesler çıkarır.",
            "Kahkaha krizine girebilir.",
            "Fazla gülerse kusacak noktaya gelebilir.",
            "Rage bait sonrası hemen kendini savunur.",
            "Söylenenleri kasıtlı yanlış anlayabilir.",
            "Aşırı dramatik reaksiyonlar verebilir.",
        ),
        catchphrases=("Abi ya, ben berbat bi insan değilim.",),
        relationships={
            "Birko": "'Dayı ölmez!' running joke / hitap.",
            "Kemal": "Abartılı 'Ağğğbiiiğ!' diye seslenir.",
            "Müge": "'Mügelom.' diye seslenir.",
        },
        appearance_notes=(
            "Chubby / overweight, youthful, expressive face, chaotic physical energy."
        ),
        voice_notes=(
            "Genç/çocukça erkek sesi, enerjik, çatlayabilir, hızlı duygu değişimi. "
            "Garip sesler ve kahkahalar ses tasarımının parçası olabilir."
        ),
        never_do=(
            "Uzun süre sessiz ve ciddi kalmak.",
            "Rage bait fırsatını tamamen görmezden gelmek.",
            "Kötü davrandığını kolayca kabul etmek.",
            "Tartışmayı sakinleştiren kişi olmak.",
        ),
        expected_ref_filenames=("ref_musti.jpg",),
        lock_if_ref_exists=True,
    ),
)


def member_by_slug(slug: str) -> BirkoCastMember:
    for member in BIRKO_CAST:
        if member.slug == slug:
            return member
    raise KeyError(slug)


def episode_2_draft_prompt() -> str:
    setting = EPISODE_2_SETTING
    low, high = setting["recommended_test_duration_seconds"]
    return (
        f"PREMISE LOCKED. Series Birko Episode 2. Language: Turkish. "
        f"Location: {setting['location']}. Primary tone: {setting['primary_tone']}; "
        f"secondary: {setting['secondary_tone']}. Cast: {', '.join(setting['cast'])}. "
        f"Target duration: {low}–{high}s. "
        f"Premise: {LOCKED_EPISODE_2_PREMISE} "
        "Scene structure, hook, dialogue, shot order, jokes, and staging are ENGINE-OWNED. "
        "Do not replace the locked premise or ending."
    )
