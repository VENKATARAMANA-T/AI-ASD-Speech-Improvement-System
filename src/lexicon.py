"""The practice lexicon: Tamil vowels and simple words to pronounce.

Each entry carries the Tamil script, its romanisation, and an English meaning.
Every ``roman`` here is exactly what :mod:`src.translit` produces for that
word — a test enforces it — so the spelling shown as the prompt is the same one
an attempt is scored against, and the transliterator cannot silently drift away
from conventional spelling.
"""

from __future__ import annotations

from dataclasses import dataclass

from .translit import romanize


@dataclass(frozen=True)
class Entry:
    id: str
    tamil: str
    roman: str
    meaning: str
    category: str  # "vowel", "word" or "sentence"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tamil": self.tamil,
            "roman": self.roman,
            "meaning": self.meaning,
            "category": self.category,
        }


# உயிர் எழுத்து — the twelve Tamil vowels, in traditional order.
VOWELS: tuple[Entry, ...] = (
    Entry("v_a", "அ", "a", "short — as in 'about'", "vowel"),
    Entry("v_aa", "ஆ", "aa", "long — as in 'father'", "vowel"),
    Entry("v_i", "இ", "i", "short — as in 'it'", "vowel"),
    Entry("v_ii", "ஈ", "ee", "long — as in 'meet'", "vowel"),
    Entry("v_u", "உ", "u", "short — as in 'put'", "vowel"),
    Entry("v_uu", "ஊ", "oo", "long — as in 'boot'", "vowel"),
    Entry("v_e", "எ", "e", "short — as in 'egg'", "vowel"),
    Entry("v_ee", "ஏ", "ae", "long — as in 'aim'", "vowel"),
    Entry("v_ai", "ஐ", "ai", "as in 'eye'", "vowel"),
    Entry("v_o", "ஒ", "o", "short — as in 'off'", "vowel"),
    Entry("v_oo", "ஓ", "oa", "long — as in 'oat'", "vowel"),
    Entry("v_au", "ஔ", "au", "as in 'owl'", "vowel"),
)

# Twenty short, everyday words: family, body, and things around the house.
WORDS: tuple[Entry, ...] = (
    Entry("w_amma", "அம்மா", "amma", "mother", "word"),
    Entry("w_appa", "அப்பா", "appa", "father", "word"),
    Entry("w_aaya", "ஆயா", "aaya", "nanny", "word"),
    Entry("w_anna", "அண்ணா", "anna", "elder brother", "word"),
    Entry("w_akka", "அக்கா", "akka", "elder sister", "word"),
    Entry("w_thambi", "தம்பி", "thambi", "younger brother", "word"),
    Entry("w_thangai", "தங்கை", "thangai", "younger sister", "word"),
    Entry("w_paatti", "பாட்டி", "paatti", "grandmother", "word"),
    Entry("w_thaatha", "தாத்தா", "thaatha", "grandfather", "word"),
    Entry("w_veedu", "வீடு", "veedu", "house", "word"),
    Entry("w_poo", "பூ", "poo", "flower", "word"),
    Entry("w_maram", "மரம்", "maram", "tree", "word"),
    Entry("w_paal", "பால்", "paal", "milk", "word"),
    Entry("w_kai", "கை", "kai", "hand", "word"),
    Entry("w_kaal", "கால்", "kaal", "leg", "word"),
    Entry("w_kan", "கண்", "kan", "eye", "word"),
    Entry("w_vaai", "வாய்", "vaai", "mouth", "word"),
    Entry("w_meen", "மீன்", "meen", "fish", "word"),
    Entry("w_naai", "நாய்", "naai", "dog", "word"),
    Entry("w_poonai", "பூனை", "poonai", "cat", "word"),
)

# Ten short everyday sentences, two or three words each. Long enough for the
# recogniser to be reliable, short enough to say in one breath.
SENTENCES: tuple[Entry, ...] = (
    Entry("s_vanakkam", "வணக்கம் நண்பா", "vanakkam nanba", "hello, friend", "sentence"),
    Entry("s_varugiraen", "நான் வருகிறேன்", "naan varugiraen", "I am coming", "sentence"),
    Entry("s_ithu_veedu", "இது வீடு", "ithu veedu", "this is a house", "sentence"),
    Entry("s_athu_maram", "அது மரம்", "athu maram", "that is a tree", "sentence"),
    Entry("s_amma_vaa", "அம்மா வா", "amma vaa", "mother, come", "sentence"),
    Entry("s_paal_kudi", "பால் குடி", "paal kudi", "drink the milk", "sentence"),
    Entry("s_thanneer", "தண்ணீர் கொடு", "thanneer kodu", "give me water", "sentence"),
    Entry("s_nalla_naal", "நல்ல நாள்", "nalla naal", "good day", "sentence"),
    Entry("s_thamizh", "நான் தமிழ் பேசுவேன்", "naan thamizh paesuvaen", "I speak Tamil", "sentence"),
    Entry("s_pasi", "எனக்கு பசிக்கிறது", "enakku pasikkirathu", "I am hungry", "sentence"),
)

# Ten longer sentences, four or five words each: everyday statements with a
# subject, an object and a verb, the next step up from the short ones.
LONG_SENTENCES: tuple[Entry, ...] = (
    Entry("l_school", "நான் இன்று பள்ளிக்கு போகிறேன்",
          "naan indru pallikku poagiraen", "I am going to school today", "sentence"),
    Entry("l_cooking", "அம்மா வீட்டில் சமையல் செய்கிறாள்",
          "amma veettil samaiyal seykiraal", "mother is cooking at home", "sentence"),
    Entry("l_like_tamil", "எனக்கு தமிழ் மிகவும் பிடிக்கும்",
          "enakku thamizh migavum pidikkum", "I like Tamil very much", "sentence"),
    Entry("l_dog_runs", "அந்த நாய் வேகமாக ஓடுகிறது",
          "antha naai vaegamaaga oadugirathu", "that dog runs fast", "sentence"),
    Entry("l_milk_daily", "நான் தினமும் பால் குடிப்பேன்",
          "naan thinamum paal kudippaen", "I drink milk every day", "sentence"),
    Entry("l_sky", "இன்று வானம் மிகவும் அழகாக இருக்கிறது",
          "indru vaanam migavum azhagaaga irukkirathu", "the sky is very beautiful today", "sentence"),
    Entry("l_appa_work", "அப்பா காலையில் வேலைக்கு போகிறார்",
          "appa kaalaiyil vaelaikku poagiraar", "father goes to work in the morning", "sentence"),
    Entry("l_friend_reads", "என் நண்பன் புத்தகம் படிக்கிறான்",
          "en nanban puthagam padikkiraan", "my friend is reading a book", "sentence"),
    Entry("l_beach", "நாங்கள் நாளை கடற்கரைக்கு போகிறோம்",
          "naangal naalai kadarkaraikku poagiroam", "we are going to the beach tomorrow", "sentence"),
    Entry("l_story", "பாட்டி எனக்கு நல்ல கதை சொல்கிறாள்",
          "paatti enakku nalla kathai solkiraal", "grandmother tells me a good story", "sentence"),
)

ALL_ENTRIES: tuple[Entry, ...] = VOWELS + WORDS + SENTENCES + LONG_SENTENCES
_BY_ID: dict[str, Entry] = {entry.id: entry for entry in ALL_ENTRIES}


def get(entry_id: str) -> Entry | None:
    """Look up one entry, or None if the id is unknown."""
    return _BY_ID.get(entry_id)


def as_payload() -> dict:
    """The whole lexicon, grouped for the dropdown."""
    return {
        "vowels": [e.to_dict() for e in VOWELS],
        "words": [e.to_dict() for e in WORDS],
        "sentences": [e.to_dict() for e in SENTENCES],
        "long_sentences": [e.to_dict() for e in LONG_SENTENCES],
        "count": len(ALL_ENTRIES),
    }
