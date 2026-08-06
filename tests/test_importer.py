"""Testy importera arkusza.

Najważniejszy przypadek: plik produkcyjny ma NIENAZWANĄ pierwszą kolumnę
z numerem telefonu, PRZESUNIĘTĄ o jeden wiersz względem kolumny „Telefon".
Mapowanie kolumn po pozycji przypisałoby klientom cudze numery — dlatego
mapujemy po tekście nagłówka.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import make_sheet

HEADERS = [
    "Akronim",
    "Miasto",
    "Prefiks",
    "Nip",
    "Kod p.",
    "Ulica",
    "Opiekun",
    "Telefon",
    "Nazwa",
    "E-mail",
]


def _row(acronym, city, nip, postal, street, phone, name, email=None):
    return [acronym, city, None, nip, postal, street, None, phone, name, email]


# ---------------------------------------------------------------------------
# Rozpoznawanie kolumn
# ---------------------------------------------------------------------------


def test_columns_are_mapped_by_header_not_position(tmp_path: Path) -> None:
    """Nienazwana, przesunięta kolumna A nie może trafić do żadnego pola.

    Odwzorowanie pliku produkcyjnego: kolumna 0 bez nagłówka zawiera numer
    należący do NASTĘPNEGO wiersza.
    """
    from app.services.importer import parse_sheet, read_sheet

    path = tmp_path / "przesunieta_kolumna.xlsx"
    make_sheet(
        path,
        [
            [None, *HEADERS],
            ["48601092947", *_row("0156", "DOBRZYCA", "617-101-01-49", "63-330",
                                  "Karmin", "+48627414846", "Przedsiębiorstwo Rolne")],
            ["48698394664", *_row("10009", "Czajków", "5140006040", "63-524",
                                  "Salomony 50", "627311566", "Gabryś Ewa i Jerzy")],
        ],
    )

    sheet = read_sheet(path)
    # Kolumna 0 nie ma nagłówka — nie może zostać zmapowana na żadne pole.
    assert 0 not in sheet.columns.values()
    assert sheet.columns["acronym"] == 1
    assert sheet.columns["phone"] == 8

    rows = parse_sheet(sheet)
    first = rows[0]
    assert first.values["acronym"] == "0156"
    # Numer z kolumny bez nagłówka (należący do innego wiersza) nie może się pojawić.
    assert [p.e164 for p in first.valid_phones] == ["+48627414846"]
    assert "+48601092947" not in [p.e164 for p in first.phones]


def test_ignored_columns_are_not_mapped(tmp_path: Path) -> None:
    """„Prefiks" (kod kraju NIP-u) i „Opiekun" (pusty) są świadomie pomijane."""
    from app.services.importer import read_sheet

    path = tmp_path / "kolumny.xlsx"
    make_sheet(path, [HEADERS, _row("0156", "Kalisz", None, None, None, None, "Test")])

    sheet = read_sheet(path)
    assert set(sheet.columns) == {
        "acronym", "city", "nip", "postal_code", "street", "phone", "name", "email"
    }


def test_missing_required_column_fails_loudly(tmp_path: Path) -> None:
    from app.services.importer import ImportError_, read_sheet

    path = tmp_path / "bez_nazwy.xlsx"
    make_sheet(path, [["Akronim", "Miasto", "Telefon"], ["0156", "Kalisz", "601092947"]])

    with pytest.raises(ImportError_, match="brakuje wymaganych kolumn"):
        read_sheet(path)


def test_header_row_found_without_title_row(tmp_path: Path) -> None:
    """Plik bez wiersza tytułowego też ma się wczytać."""
    from app.services.importer import read_sheet

    path = tmp_path / "bez_tytulu.xlsx"
    make_sheet(
        path,
        [HEADERS, _row("0156", "Kalisz", None, None, None, "601092947", "Test")],
        title_row=False,
    )

    sheet = read_sheet(path)
    assert sheet.header_row == 0
    assert len(sheet.rows) == 1


# ---------------------------------------------------------------------------
# Normalizacja wiersza
# ---------------------------------------------------------------------------


def test_row_with_two_numbers_in_one_cell(tmp_path: Path) -> None:
    from app.services.importer import parse_sheet, read_sheet

    path = tmp_path / "dwa_numery.xlsx"
    make_sheet(
        path,
        [
            HEADERS,
            _row("10017", "Pyzdry", "7891495744", "62-310", "ul. Farna 38a",
                 "606420728   632767173", "FHU Wrzaskowski Karol"),
        ],
    )

    row = parse_sheet(read_sheet(path))[0]
    assert [p.e164 for p in row.valid_phones] == ["+48606420728", "+48632767173"]


def test_leading_zero_in_acronym_survives(tmp_path: Path) -> None:
    """Bez dtype=str pandas zamieniłby „0156" na liczbę 156."""
    from app.services.importer import parse_sheet, read_sheet

    path = tmp_path / "akronim.xlsx"
    make_sheet(path, [HEADERS, _row("0156", "Dobrzyca", None, None, None, None, "Test")])

    assert parse_sheet(read_sheet(path))[0].values["acronym"] == "0156"


def test_empty_row_is_marked_not_dropped(tmp_path: Path) -> None:
    from app.services.importer import parse_sheet, read_sheet

    path = tmp_path / "pusty.xlsx"
    make_sheet(
        path,
        [
            HEADERS,
            _row("0156", "Kalisz", None, None, None, None, "Klient"),
            [None] * len(HEADERS),
        ],
    )

    rows = parse_sheet(read_sheet(path))
    assert rows[0].empty is False
    assert rows[1].empty is True


def test_bad_values_produce_warnings_but_keep_the_row(tmp_path: Path) -> None:
    """Śmieciowy NIP i kod pocztowy nie mogą wyrzucić rekordu."""
    from app.services.importer import parse_sheet, read_sheet

    path = tmp_path / "smieci.xlsx"
    make_sheet(
        path,
        [HEADERS, _row("10099", "SOBÓTKA", "3417980RH", "R42XV88", "Gutów 5",
                       "7649233", "Gospodarstwo Rolne Kołodziej Paweł")],
    )

    row = parse_sheet(read_sheet(path))[0]
    assert row.empty is False
    assert row.values["name"] == "Gospodarstwo Rolne Kołodziej Paweł"
    assert row.values["city"] == "Sobótka"
    assert row.values["postal_code"] is None
    assert row.nip_valid is False
    assert row.valid_phones == []
    assert row.needs_review is True
    # numer nie do sparsowania zostaje w postaci surowej
    assert row.phones[0].raw == "7649233"


# ---------------------------------------------------------------------------
# Zapis do bazy (wymaga PostgreSQL)
# ---------------------------------------------------------------------------


@pytest.fixture
def job_factory(session, tmp_path):
    from app.models import ImportJob

    def make(rows, name="arkusz.xlsx"):
        path = tmp_path / name
        make_sheet(path, [HEADERS, *rows])
        job = ImportJob(filename=name, stored_path=str(path))
        session.add(job)
        session.commit()
        return job

    return make


@pytest.mark.db
def test_import_creates_clients_with_phones(session, job_factory) -> None:
    from app.models import Client
    from app.services.importer import run_import

    job = job_factory(
        [
            _row("0156", "DOBRZYCA", "617-101-01-49", "63-330", "Karmin",
                 "+48627414846", "Przedsiębiorstwo Rolne Taczanów", "hodowla@osw.pl"),
            _row("10017", "Pyzdry", "7891495744", "62-310", "ul. Farna 38a",
                 "606420728   632767173", "FHU Wrzaskowski Karol"),
        ]
    )

    report = run_import(job.id)
    assert report["created"] == 2

    client = session.query(Client).filter_by(acronym="0156").one()
    assert client.name == "Przedsiębiorstwo Rolne Taczanów"
    assert client.city == "Dobrzyca"
    assert client.nip == "6171010149"
    assert client.nip_valid is True
    assert client.email == "hodowla@osw.pl"

    other = session.query(Client).filter_by(acronym="10017").one()
    assert sorted(p.e164 for p in other.phones) == ["+48606420728", "+48632767173"]
    assert other.primary_phone.e164 == "+48606420728"


@pytest.mark.db
def test_reimport_updates_instead_of_duplicating(session, job_factory) -> None:
    """Ten sam plik zaimportowany dwa razy nie może zdublować klientów."""
    from app.models import Client
    from app.services.importer import run_import

    rows = [_row("0156", "Dobrzyca", "617-101-01-49", "63-330", "Karmin",
                 "627414846", "Przedsiębiorstwo Rolne")]

    first = run_import(job_factory(rows, "pierwszy.xlsx").id)
    second = run_import(job_factory(rows, "drugi.xlsx").id)

    assert first["created"] == 1
    assert second["created"] == 0
    assert session.query(Client).count() == 1


@pytest.mark.db
def test_update_records_changed_fields_in_activity(session, job_factory) -> None:
    from app.models import Activity, ActivityType, Client
    from app.services.importer import run_import

    run_import(
        job_factory(
            [_row("0156", "Dobrzyca", None, "63-330", "Karmin", None, "Stara Nazwa")],
            "a.xlsx",
        ).id
    )
    run_import(
        job_factory(
            [_row("0156", "Dobrzyca", None, "63-330", "Karmin", None, "Nowa Nazwa")],
            "b.xlsx",
        ).id
    )

    client = session.query(Client).filter_by(acronym="0156").one()
    assert client.name == "Nowa Nazwa"

    activity = (
        session.query(Activity)
        .filter_by(client_id=client.id, type=ActivityType.CLIENT_UPDATED)
        .one()
    )
    assert activity.meta["changes"]["name"] == {"from": "Stara Nazwa", "to": "Nowa Nazwa"}


@pytest.mark.db
def test_import_never_deletes_existing_phone(session, job_factory) -> None:
    """Pusta komórka w nowym pliku nie kasuje numeru zapisanego wcześniej."""
    from app.models import Client
    from app.services.importer import run_import

    run_import(
        job_factory(
            [_row("0156", "Dobrzyca", None, None, None, "627414846", "Klient")], "a.xlsx"
        ).id
    )
    run_import(
        job_factory(
            [_row("0156", "Dobrzyca", None, None, None, None, "Klient")], "b.xlsx"
        ).id
    )

    client = session.query(Client).filter_by(acronym="0156").one()
    assert [p.e164 for p in client.phones] == ["+48627414846"]


@pytest.mark.db
def test_shared_phone_between_two_clients_is_allowed(session, job_factory) -> None:
    """58 numerów w bazie źródłowej należy do dwóch–trzech klientów naraz.

    Ograniczenie UNIQUE na Phone.e164 odrzuciłoby te rekordy — tu sprawdzamy,
    że oba wchodzą i drugi dostaje tag możliwego duplikatu.
    """
    from app.models import TAG_POSSIBLE_DUPLICATE, Client
    from app.services.importer import run_import

    report = run_import(
        job_factory(
            [
                _row("10009", "Czajków", None, None, None, "601092947", "Ojciec Gabryś"),
                _row("10010", "Czajków", None, None, None, "601092947", "Syn Gabryś"),
            ]
        ).id
    )

    assert report["created"] == 2
    second = session.query(Client).filter_by(acronym="10010").one()
    assert second.has_tag(TAG_POSSIBLE_DUPLICATE)


@pytest.mark.db
def test_duplicate_nip_does_not_merge_clients(session, job_factory) -> None:
    """34 NIP-y powtarzają się u odrębnych gospodarstw — scalać ich nie wolno."""
    from app.models import TAG_POSSIBLE_DUPLICATE, Client
    from app.services.importer import run_import

    run_import(
        job_factory(
            [
                _row("0156", "Kalisz", "617-101-01-49", None, None, None, "Pierwszy"),
                _row("0157", "Kalisz", "617-101-01-49", None, None, None, "Drugi"),
            ]
        ).id
    )

    assert session.query(Client).count() == 2
    assert session.query(Client).filter_by(acronym="0157").one().has_tag(
        TAG_POSSIBLE_DUPLICATE
    )


@pytest.mark.db
def test_row_without_name_is_skipped_and_reported(session, job_factory) -> None:
    from app.models import Client
    from app.services.importer import run_import

    report = run_import(
        job_factory(
            [
                _row("0156", "Kalisz", None, None, None, None, "Poprawny"),
                _row("0157", "Kalisz", None, None, None, "601092947", None),
            ]
        ).id
    )

    assert report["created"] == 1
    assert report["skipped"] == 1
    assert session.query(Client).count() == 1
    assert any("brak nazwy" in problem["reason"] for problem in report["problems"])


@pytest.mark.db
def test_bad_data_gets_review_tag(session, job_factory) -> None:
    from app.models import TAG_NEEDS_REVIEW, Client
    from app.services.importer import run_import

    run_import(
        job_factory(
            [_row("0156", "Kalisz", "3417980RH", "R42XV88", None, "7649233", "Klient")]
        ).id
    )

    client = session.query(Client).filter_by(acronym="0156").one()
    assert client.has_tag(TAG_NEEDS_REVIEW)
    assert client.nip_valid is False
    # numer nieparsowalny zapisany surowo, rekord zachowany
    assert client.phones[0].e164 is None
    assert client.phones[0].raw == "7649233"
