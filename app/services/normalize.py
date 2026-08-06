"""Normalizacja brudnych danych z eksportu księgowego.

Moduł celowo nie zależy od Flaska ani od bazy — to czyste funkcje, żeby dało się
je testować bez podnoszenia aplikacji. Każda zwraca wynik razem z listą ostrzeżeń;
**żadna nie wyrzuca danych** — wartość, której nie da się znormalizować, wraca
jako ostrzeżenie, a oryginał zostaje zapisany osobno.

Wszystkie reguły wynikają z konkretnych przypadków w pliku źródłowym, nie z domysłów
— przykłady w komentarzach są autentyczne.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import phonenumbers
from stdnum.pl import nip as pl_nip

# ---------------------------------------------------------------------------
# Wynik normalizacji
# ---------------------------------------------------------------------------


@dataclass
class PhoneCandidate:
    """Pojedynczy numer wyłuskany z komórki arkusza."""

    raw: str
    e164: str | None = None
    label: str | None = None
    warning: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.e164 is not None


@dataclass
class FieldResult:
    """Wartość po normalizacji plus ewentualne ostrzeżenia."""

    value: str | None
    warnings: list[str] = field(default_factory=list)
    valid: bool = True


# ---------------------------------------------------------------------------
# Telefony
# ---------------------------------------------------------------------------

# Słowa-etykiety spotykane w kolumnie Telefon: "7611269  kom 505806328",
# "Piotr Bogacz tel: 668 147 312", "sekr. 655 122 710".
_PHONE_KEYWORDS = re.compile(
    r"\b(kom|tel|fax|faks|sekr|mob|komórka|komorka|biuro|dom)\b\.?\s*:?",
    re.IGNORECASE,
)

# Wszystko, co nie jest cyfrą, plusem ani separatorem — czyli imiona doklejone
# do numeru ("609855432-Jarosław", "+48668445867   Graf").
_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)

# Separatory rozdzielające DWA numery w jednej komórce.
# Uwaga na to, czego tu NIE ma:
#   * pojedyncza spacja — "889 869 505" to jeden numer, nie trzy;
#   * ukośnik — w całym pliku występuje raz, w "062/76 38 408", i jest tam
#     ozdobnikiem po numerze kierunkowym, nie separatorem.
_HARD_SEPARATORS = re.compile(
    r"""
      \s*[,;]\s*      # przecinek albo średnik: "691747038, 722 099 015"
    | \s{2,}          # dwie lub więcej spacji: "606420728   632767173"
    | \.\s+           # kropka ze spacją:       "697668112. 62 733 61 49"
    """,
    re.VERBOSE,
)

# Minimalna liczba cyfr, przy której fragment w ogóle warto próbować parsować.
# Krótsze to numery lokalne bez kierunkowego ("7649233", "517-81-71") — nie da
# się z nich odtworzyć pełnego numeru, więc trafiają do ostrzeżeń.
_MIN_DIGITS = 9


def _extract_label(fragment: str) -> tuple[str, str | None]:
    """Oddziela tekst (imię, „kom", „sekr.") od samego numeru.

    ``"609855432-Jarosław"`` → ``("609855432-", "Jarosław")``
    """
    without_keywords = _PHONE_KEYWORDS.sub(" ", fragment)
    words = [w for w in _LETTERS.findall(without_keywords) if len(w) > 1]
    digits_only = _LETTERS.sub(" ", without_keywords)
    label = " ".join(words).strip() or None
    return digits_only, label


def split_phone_cell(raw: str | None) -> list[str]:
    """Dzieli zawartość komórki na fragmenty, z których każdy może być numerem."""
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []
    # Ukośnik to ozdobnik po numerze kierunkowym, nie separator — zamieniamy na spację,
    # żeby "062/76 38 408" zlepiło się w jeden numer.
    text = text.replace("/", " ")
    parts = _HARD_SEPARATORS.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def normalize_phone(raw: str | None) -> PhoneCandidate:
    """Jeden fragment → numer w formacie E.164.

    Obsługuje wszystkie konwencje z pliku źródłowego::

        +48627528058     → +48627528058
        607137842        → +48607137842   (dziewięć cyfr, dokładamy kierunkowy kraju)
        601-092-947      → +48601092947
        889 869 505      → +48889869505
        62 7817107       → +48627817107   (stacjonarny)
        061 426 15 87    → +48614261587   (zero wiodące — dawny prefiks międzymiastowy)
        7649233          → None           (numer lokalny, bez kierunkowego)
        +486274148468    → None           (o cyfrę za dużo)
    """
    original = (raw or "").strip()
    if not original:
        return PhoneCandidate(raw=original, warning="pusty numer")

    cleaned, label = _extract_label(original)
    digits = re.sub(r"[^\d+]", "", cleaned)

    if not digits:
        return PhoneCandidate(raw=original, label=label, warning="brak cyfr w numerze")

    has_plus = digits.startswith("+")
    bare = digits.lstrip("+")

    # Zero wiodące to relikt sprzed 2009 roku (dawny prefiks międzymiastowy).
    # Zdejmujemy je tylko wtedy, gdy zostaje sensowne dziewięć cyfr.
    if not has_plus and bare.startswith("0") and len(bare) == 10:
        bare = bare[1:]

    if len(bare) < _MIN_DIGITS:
        return PhoneCandidate(
            raw=original,
            label=label,
            warning=f"za mało cyfr ({len(bare)}) — numer lokalny bez kierunkowego",
        )

    candidate = f"+{bare}" if has_plus else bare

    try:
        parsed = phonenumbers.parse(candidate, "PL")
    except phonenumbers.NumberParseException as exc:
        return PhoneCandidate(
            raw=original, label=label, warning=f"nie udało się sparsować ({exc})"
        )

    if not phonenumbers.is_valid_number(parsed):
        return PhoneCandidate(
            raw=original, label=label, warning="numer niepoprawny dla Polski"
        )

    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return PhoneCandidate(raw=original, e164=e164, label=label)


def normalize_phone_cell(raw: str | None) -> list[PhoneCandidate]:
    """Cała komórka → lista numerów. Zwraca też te nieparsowalne, z ostrzeżeniem."""
    fragments = split_phone_cell(raw)
    if not fragments:
        return []

    results: list[PhoneCandidate] = []
    seen: set[str] = set()
    for fragment in fragments:
        candidate = normalize_phone(fragment)
        # Ten sam numer zapisany dwa razy w jednej komórce zapisujemy raz.
        if candidate.e164 and candidate.e164 in seen:
            continue
        if candidate.e164:
            seen.add(candidate.e164)
        results.append(candidate)
    return results


def phone_search_variants(query: str) -> list[str]:
    """Warianty numeru do wyszukiwarki klientów.

    Użytkownik wpisze ``601092947``, ``601-092-947`` albo ``+48601092947``
    i za każdym razem musi dostać ten sam wynik (sekcja 6 specyfikacji).
    """
    digits = re.sub(r"[^\d+]", "", query or "")
    if len(re.sub(r"\D", "", digits)) < 6:
        return []

    variants: set[str] = set()
    candidate = normalize_phone(query)
    if candidate.e164:
        variants.add(candidate.e164)

    bare = digits.lstrip("+")
    if bare.startswith("0") and len(bare) == 10:
        bare = bare[1:]
    if bare:
        variants.add(bare)
        if not bare.startswith("48"):
            variants.add(f"+48{bare}")
        else:
            variants.add(f"+{bare}")
    return sorted(variants)


# ---------------------------------------------------------------------------
# NIP
# ---------------------------------------------------------------------------


def normalize_nip(raw: str | None) -> FieldResult:
    """NIP → same cyfry, z weryfikacją sumy kontrolnej.

    Formaty z pliku: ``617-101-01-49``, ``5140006040``, ``622-00-21-912``
    (nietypowe grupowanie, ale poprawne dziesięć cyfr). Sumy kontrolnej nie
    liczymy ręcznie — od tego jest ``stdnum``.
    """
    if not raw or not str(raw).strip():
        return FieldResult(value=None)

    text = str(raw).strip()
    digits = re.sub(r"\D", "", text)

    if not digits:
        return FieldResult(
            value=None, warnings=[f"NIP bez cyfr: {text!r}"], valid=False
        )
    if len(digits) != 10:
        return FieldResult(
            value=digits,
            warnings=[f"NIP ma {len(digits)} cyfr zamiast 10: {text!r}"],
            valid=False,
        )
    if not pl_nip.is_valid(digits):
        return FieldResult(
            value=digits,
            warnings=[f"NIP {text!r} nie przechodzi sumy kontrolnej"],
            valid=False,
        )
    return FieldResult(value=digits)


# ---------------------------------------------------------------------------
# Miasta
# ---------------------------------------------------------------------------

# Spójniki i przyimki, które w nazwach miejscowości zostają małą literą:
# „Nowe Miasto nad Wartą", „Kamionka pod Lasem".
_LOWERCASE_WORDS = {
    "nad",
    "pod",
    "przy",
    "za",
    "na",
    "w",
    "we",
    "i",
    "u",
    "do",
    "od",
    "koło",
    "kolo",
    "k",
}

# Skróty, które zostają wersalikami.
_UPPERCASE_WORDS = {"skr", "gm", "pgr", "rsp", "sкr"}


def _capitalize_part(part: str) -> str:
    """Wielka pierwsza litera, reszta mała — z myślnikami i kropkami."""
    if not part:
        return part
    # Człony rozdzielone myślnikiem: „Bielsko-Biała", „Kędzierzyn-Koźle"
    if "-" in part:
        return "-".join(_capitalize_part(chunk) for chunk in part.split("-"))
    if "." in part and len(part) > 1:
        return ".".join(_capitalize_part(chunk) for chunk in part.split("."))
    if not part[0].isalpha():
        # np. „(dawniej Kowalewo)" — wielka litera po nawiasie
        for i, ch in enumerate(part):
            if ch.isalpha():
                return part[:i] + part[i].upper() + part[i + 1 :].lower()
        return part
    return part[0].upper() + part[1:].lower()


def normalize_city(raw: str | None) -> FieldResult:
    """Miasto → Title Case odporny na polskie znaki.

    W pliku ta sama miejscowość występuje jako ``SOBÓTKA`` i ``Sobótka`` — bez
    ujednolicenia grupowanie po mieście produkuje fałszywe duplikaty
    (109 nazw wersalikami na 648 unikalnych).

    ``str.title()`` nie wystarcza: kapitalizuje spójniki („Nowe Miasto Nad Wartą")
    i rozjeżdża się na członach z myślnikiem.
    """
    if not raw or not str(raw).strip():
        return FieldResult(value=None)

    text = re.sub(r"\s+", " ", str(raw).strip())
    words = text.split(" ")
    out: list[str] = []

    for index, word in enumerate(words):
        bare = word.strip(".,").lower()
        if bare in _UPPERCASE_WORDS:
            out.append(word.upper())
        elif index > 0 and bare in _LOWERCASE_WORDS:
            out.append(word.lower())
        else:
            out.append(_capitalize_part(word))

    return FieldResult(value=" ".join(out))


def city_key(raw: str | None) -> str:
    """Klucz do porównywania miast — bez ogonków, małymi literami.

    Służy tylko do grupowania i wykrywania duplikatów, nie do wyświetlania.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKD", str(raw).strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ł", "l")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# ---------------------------------------------------------------------------
# Kod pocztowy
# ---------------------------------------------------------------------------

_POSTAL_OK = re.compile(r"^\d{2}-\d{3}$")


def normalize_postal(raw: str | None) -> FieldResult:
    """Kod pocztowy do formatu ``XX-XXX``. Pięć cyfr bez myślnika → dokładamy myślnik."""
    if not raw or not str(raw).strip():
        return FieldResult(value=None)

    text = str(raw).strip()
    if _POSTAL_OK.match(text):
        return FieldResult(value=text)

    digits = re.sub(r"\D", "", text)
    if len(digits) == 5:
        return FieldResult(value=f"{digits[:2]}-{digits[2:]}")

    return FieldResult(
        value=None,
        warnings=[f"kod pocztowy w nieznanym formacie: {text!r}"],
        valid=False,
    )


# ---------------------------------------------------------------------------
# Nazwy
# ---------------------------------------------------------------------------


def normalize_name(raw: str | None) -> FieldResult:
    """Nazwa klienta — tylko sprzątanie białych znaków.

    **Literówek nie poprawiamy automatycznie.** W pliku jest m.in.
    ``Gospodarstw Rolne Piotr Duras`` (brakuje „o") i ``Bernard Mir`` (ucięte
    nazwisko) — zgadywanie poprawnej formy przy 2000 rekordów zrobi więcej
    szkody niż pożytku. Podejrzane rekordy tylko oznaczamy ostrzeżeniem,
    a import nadaje im tag do ręcznego przeglądu.
    """
    if raw is None or not str(raw).strip():
        return FieldResult(value=None, warnings=["brak nazwy"], valid=False)

    text = re.sub(r"\s+", " ", str(raw).strip())
    warnings: list[str] = []

    if len(text) < 3:
        warnings.append(f"nazwa podejrzanie krótka: {text!r}")
    if not re.search(r"[^\W\d_]", text, re.UNICODE):
        warnings.append(f"nazwa bez liter: {text!r}")

    return FieldResult(value=text, warnings=warnings, valid=not warnings)


# ---------------------------------------------------------------------------
# Pozostałe pola
# ---------------------------------------------------------------------------

_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def normalize_email(raw: str | None) -> FieldResult:
    """Adres e-mail — przycięcie i małe litery (11 adresów w pliku jest wersalikami)."""
    if not raw or not str(raw).strip():
        return FieldResult(value=None)

    text = str(raw).strip().replace(" ", "").lower()
    if not _EMAIL_OK.match(text):
        return FieldResult(
            value=None, warnings=[f"adres e-mail niepoprawny: {raw!r}"], valid=False
        )
    return FieldResult(value=text)


def normalize_acronym(raw: str | None) -> FieldResult:
    """Akronim ZAWSZE jako tekst.

    ``"0156"`` i ``"156"`` to dwa różne rekordy — wiodące zera są znaczące,
    a w pliku występują dwie serie: czterocyfrowa i pięciocyfrowa.
    """
    if raw is None:
        return FieldResult(value=None)

    text = str(raw).strip()
    if not text:
        return FieldResult(value=None)

    # pandas z dtype=str potrafi mimo wszystko podać "156.0" — ratujemy taki zapis
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]

    return FieldResult(value=text)


def normalize_street(raw: str | None) -> FieldResult:
    """Ulica — sprzątanie białych znaków, bez ingerencji w treść.

    Rekord z miastem ``DOBRZYCA`` i ulicą ``Karmin`` jest poprawny (wieś w gminie),
    więc niespójności adresowych nie „naprawiamy".
    """
    if raw is None or not str(raw).strip():
        return FieldResult(value=None)
    return FieldResult(value=re.sub(r"\s+", " ", str(raw).strip()))
