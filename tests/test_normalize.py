"""Testy normalizacji danych.

Wszystkie przypadki pochodzą z prawdziwego pliku ``poprawiona baza klientów...xlsx``
(1924 wiersze) albo z ``pokazowa.ods`` — żaden nie jest wymyślony. To miejsce,
w którym błąd po cichu zepsułby 2000 rekordów.
"""

from __future__ import annotations

import pytest

from app.services.normalize import (
    city_key,
    normalize_acronym,
    normalize_city,
    normalize_email,
    normalize_name,
    normalize_nip,
    normalize_phone,
    normalize_phone_cell,
    normalize_postal,
    phone_search_variants,
    split_phone_cell,
)

# ---------------------------------------------------------------------------
# Telefony
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # cztery konwencje wymienione w specyfikacji
        ("+48627528058", "+48627528058"),
        ("607137842", "+48607137842"),
        ("601-092-947", "+48601092947"),
        ("889 869 505", "+48889869505"),
        # stacjonarne — spacje w środku numeru NIE są separatorem
        ("62 7817107", "+48627817107"),
        ("62 74 13 529", "+48627413529"),
        ("62 761-82-54", "+48627618254"),
        ("627311566", "+48627311566"),
        # zero wiodące: dawny prefiks międzymiastowy, zniesiony w 2009
        ("061 426 15 87", "+48614261587"),
        ("0672615284", "+48672615284"),
        ("0601478051", "+48601478051"),
        ("0655736582", "+48655736582"),
        # ukośnik po numerze kierunkowym — ozdobnik, nie separator
        ("062/76 38 408", "+48627638408"),
        # numer z doklejonym imieniem
        ("609855432-Jarosław", "+48609855432"),
        ("503 039 818 Dariusz", "+48503039818"),
        ("781-901-034 Piotr", "+48781901034"),
    ],
)
def test_normalize_phone_valid(raw: str, expected: str) -> None:
    assert normalize_phone(raw).e164 == expected


@pytest.mark.parametrize(
    "raw",
    [
        "7649233",  # siedem cyfr, numer lokalny bez kierunkowego
        "741-36-85",
        "7618259",
        "72 97 46 19",  # osiem cyfr
        "+486274148468",  # o cyfrę za dużo
        "",
        "   ",
        "brak",
    ],
)
def test_normalize_phone_invalid(raw: str) -> None:
    result = normalize_phone(raw)
    assert result.e164 is None
    assert result.warning  # zawsze wiadomo, dlaczego się nie udało
    assert result.raw == raw.strip()  # oryginał nigdy nie ginie


def test_normalize_phone_extracts_label() -> None:
    assert normalize_phone("609855432-Jarosław").label == "Jarosław"
    # słowa-etykiety („kom", „tel") nie trafiają do nazwy
    assert normalize_phone("kom 505806328").label is None


# ---------------------------------------------------------------------------
# Dwa numery w jednej komórce
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # potrójna spacja
        ("606420728   632767173", ["+48606420728", "+48632767173"]),
        # przecinek
        ("691747038, 722 099 015", ["+48691747038", "+48722099015"]),
        ("515189852 , 510451736", ["+48515189852", "+48510451736"]),
        # średnik
        ("627612925  ; 506154779", ["+48627612925", "+48506154779"]),
        # dwa stacjonarne
        ("043 829-26-15  043 829-27-15", ["+48438292615", "+48438292715"]),
        # kropka jako separator
        ("63 725 90 81  . 504 164 012", ["+48637259081", "+48504164012"]),
        ("697668112. 62 733 61 49", ["+48697668112", "+48627336149"]),
        # słowo „kom" oddzielające numery
        ("7611269  kom 505806328", ["+48505806328"]),
    ],
)
def test_normalize_phone_cell_multiple(raw: str, expected: list[str]) -> None:
    valid = [candidate.e164 for candidate in normalize_phone_cell(raw) if candidate.e164]
    assert valid == expected


def test_second_number_without_area_code_is_kept_as_warning() -> None:
    """„65 517-81-70, 517-81-71" — drugi człon to numer lokalny.

    Pierwszy numer musi się sparsować, drugi ma zostać zapisany surowo,
    z ostrzeżeniem. Rekordu nie wyrzucamy.
    """
    results = normalize_phone_cell("65 517-81-70, 517-81-71")
    assert len(results) == 2
    assert results[0].e164 == "+48655178170"
    assert results[1].e164 is None
    assert results[1].raw == "517-81-71"


def test_single_spaces_do_not_split_a_number() -> None:
    assert len(normalize_phone_cell("889 869 505")) == 1
    assert len(normalize_phone_cell("62 74 13 529")) == 1


def test_duplicate_number_in_one_cell_is_stored_once() -> None:
    results = normalize_phone_cell("601092947, 601-092-947")
    assert [r.e164 for r in results] == ["+48601092947"]


def test_empty_cell_gives_no_phones() -> None:
    assert normalize_phone_cell(None) == []
    assert normalize_phone_cell("") == []
    assert normalize_phone_cell("   ") == []


def test_split_phone_cell_keeps_fragments() -> None:
    assert split_phone_cell("606420728   632767173") == ["606420728", "632767173"]
    assert split_phone_cell("889 869 505") == ["889 869 505"]


# ---------------------------------------------------------------------------
# Wyszukiwarka po numerze
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query", ["601092947", "601-092-947", "+48601092947", "601 092 947", "48601092947"]
)
def test_phone_search_variants_are_format_independent(query: str) -> None:
    """Niezależnie od formatu wpisanego przez użytkownika ma wyjść ten sam numer."""
    assert "+48601092947" in phone_search_variants(query)


# ---------------------------------------------------------------------------
# NIP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "digits"),
    [
        ("617-101-01-49", "6171010149"),
        ("5140006040", "5140006040"),
        ("622-00-21-912", "6220021912"),  # nietypowe grupowanie, poprawne 10 cyfr
        ("618-004-45-15", "6180044515"),
        ("767-150-77-41", "7671507741"),
        (" 7891373805 ", "7891373805"),
    ],
)
def test_normalize_nip_valid(raw: str, digits: str) -> None:
    result = normalize_nip(raw)
    assert result.value == digits
    assert result.valid


@pytest.mark.parametrize("raw", ["12988", "3417980RH", "1234567890"])
def test_normalize_nip_invalid(raw: str) -> None:
    result = normalize_nip(raw)
    assert not result.valid
    assert result.warnings


def test_normalize_nip_empty() -> None:
    for raw in (None, "", "   "):
        result = normalize_nip(raw)
        assert result.value is None
        assert result.valid  # brak NIP-u to nie błąd


# ---------------------------------------------------------------------------
# Miasta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("DOBRZYCA", "Dobrzyca"),
        ("SOBÓTKA", "Sobótka"),
        ("Sobótka", "Sobótka"),
        ("JAROCIN", "Jarocin"),
        ("GODZIESZE MAŁE", "Godziesze Małe"),
        ("JASTRZĘBNIKI", "Jastrzębniki"),
        ("WŁADYSŁAWÓW", "Władysławów"),
        ("Kołaczkowo", "Kołaczkowo"),
        ("nowe miasto nad wartą", "Nowe Miasto nad Wartą"),
        ("BIELSKO-BIAŁA", "Bielsko-Biała"),
        ("  ostrów   wielkopolski  ", "Ostrów Wielkopolski"),
    ],
)
def test_normalize_city(raw: str, expected: str) -> None:
    assert normalize_city(raw).value == expected


def test_city_case_variants_collapse_to_one_key() -> None:
    """SOBÓTKA i Sobótka to jedno miasto — inaczej grupowanie da fałszywe duplikaty."""
    assert normalize_city("SOBÓTKA").value == normalize_city("Sobótka").value
    assert city_key("SOBÓTKA") == city_key("sobotka") == "sobotka"


# ---------------------------------------------------------------------------
# Kod pocztowy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("63-330", "63-330"), ("63330", "63-330"), ("62-820", "62-820"), (" 64980 ", "64-980")],
)
def test_normalize_postal_valid(raw: str, expected: str) -> None:
    assert normalize_postal(raw).value == expected


@pytest.mark.parametrize("raw", ["R42XV88", "6333", "abc"])
def test_normalize_postal_invalid(raw: str) -> None:
    result = normalize_postal(raw)
    assert result.value is None
    assert not result.valid


# ---------------------------------------------------------------------------
# Nazwy
# ---------------------------------------------------------------------------


def test_normalize_name_collapses_whitespace() -> None:
    assert (
        normalize_name("Gospodarstwo Rolne  Bartosik Rafał").value
        == "Gospodarstwo Rolne Bartosik Rafał"
    )
    assert normalize_name("  SKR w Stawiszynie  ").value == "SKR w Stawiszynie"


def test_normalize_name_does_not_fix_typos() -> None:
    """Literówek nie poprawiamy — brakujące „o" w „Gospodarstw" zostaje."""
    assert normalize_name("Gospodarstw Rolne Piotr Duras").value == (
        "Gospodarstw Rolne Piotr Duras"
    )
    assert normalize_name("Gospodarstwo Rolno-Hodowlane Bernard Mir").value == (
        "Gospodarstwo Rolno-Hodowlane Bernard Mir"
    )


def test_normalize_name_keeps_quotes() -> None:
    raw = 'F.H.U."STEKRO"SKUP I SPRZEDAŻ SPRZĘTU ROLNICZEGO Stefan Król'
    assert normalize_name(raw).value == raw


def test_normalize_name_missing() -> None:
    result = normalize_name(None)
    assert result.value is None
    assert not result.valid


# ---------------------------------------------------------------------------
# Akronim i e-mail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0156", "0156"), ("10009", "10009"), ("120508", "120508"), ("156.0", "156")],
)
def test_normalize_acronym_keeps_leading_zeros(raw: str, expected: str) -> None:
    """„0156" i „156" to DWA różne rekordy — zera wiodące są znaczące."""
    assert normalize_acronym(raw).value == expected


def test_normalize_email() -> None:
    # 11 adresów w pliku jest zapisanych wersalikami
    assert (
        normalize_email("JK.GOSPODARSTWOROLNE@WP.PL").value
        == "jk.gospodarstworolne@wp.pl"
    )
    assert normalize_email(" skr.stawiszyn@op.pl ").value == "skr.stawiszyn@op.pl"
    assert normalize_email("nie-jest-mailem").value is None
    assert normalize_email(None).value is None
