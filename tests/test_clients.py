"""Testy listy klientów i panelu klienta.

Nacisk położony na dwa miejsca, w których cichy błąd byłby najdroższy:

1. **Wyszukiwanie po numerze telefonu.** Wymóg z sekcji 6 mówi wprost, że
   ``601092947``, ``601-092-947`` i ``+48601092947`` mają dawać ten sam wynik.
   Gdyby przestało działać, użytkownik uznałby, że klienta nie ma w bazie —
   i założyłby go drugi raz.
2. **Edycja pola.** Każda zmiana musi zostawić ślad na osi czasu, a błędna
   wartość nie może po cichu wyczyścić pola.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.db


@pytest.fixture
def make_client(session):
    """Fabryka klientów z numerami telefonu."""
    from app.models import Client, Phone

    def make(
        name,
        *,
        city=None,
        nip=None,
        nip_valid=False,
        acronym=None,
        email=None,
        phones=(),
        status=None,
        tags=(),
    ):
        from app.models import ClientStatus, Tag

        client = Client(
            name=name,
            city=city,
            nip=nip,
            nip_valid=nip_valid,
            acronym=acronym,
            email=email,
            status=status or ClientStatus.ACTIVE,
        )
        session.add(client)
        session.flush()

        for index, raw in enumerate(phones):
            from app.services.normalize import normalize_phone

            candidate = normalize_phone(raw)
            session.add(
                Phone(
                    client_id=client.id,
                    e164=candidate.e164,
                    raw=raw,
                    is_primary=index == 0,
                )
            )

        for tag_name in tags:
            tag = session.scalar(sa.select(Tag).where(Tag.name == tag_name))
            if tag is None:
                tag = Tag(name=tag_name)
                session.add(tag)
                session.flush()
            client.tags.append(tag)

        session.flush()
        return client

    return make


def _search(query: str):
    from app.services.clients import ClientFilters, list_clients

    return list_clients(ClientFilters(query=query))


# ---------------------------------------------------------------------------
# Wyszukiwanie po telefonie — wymóg twardy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "601092947",
        "601-092-947",
        "601 092 947",
        "+48601092947",
        "48601092947",
    ],
)
def test_phone_search_ignores_formatting(app, make_client, query):
    """Pięć zapisów tego samego numeru musi dać ten sam, jeden wynik."""
    make_client("Gospodarstwo Rolne Kowalski", phones=["+48601092947"])
    make_client("Ktoś zupełnie inny", phones=["+48627528058"])

    page = _search(query)

    assert page.total == 1, f"zapis {query!r} nie znalazł klienta"
    assert page.rows[0][0].name == "Gospodarstwo Rolne Kowalski"


def test_phone_search_finds_number_stored_in_odd_format(app, make_client):
    """Numer zapisany w bazie z myślnikami też musi się znaleźć.

    Import normalizuje numery do E.164, ale numery nieparsowalne zostają
    w kolumnie `raw` z `e164 = NULL` — i te też trzeba umieć odszukać.
    """
    make_client("Gospodarstwo z dziwnym numerem", phones=["606-420-728 wew. 12"])

    page = _search("606420728")

    assert page.total == 1
    assert page.rows[0][0].name == "Gospodarstwo z dziwnym numerem"


def test_phone_search_does_not_match_everyone(app, make_client):
    make_client("Pierwszy", phones=["+48601092947"])
    make_client("Drugi", phones=["+48607137842"])

    assert _search("601092947").total == 1


# ---------------------------------------------------------------------------
# Pozostałe pola wyszukiwarki
# ---------------------------------------------------------------------------


def test_search_by_name_is_case_insensitive(app, make_client):
    make_client("Gospodarstwo Rolne Bartosik Rafał")
    assert _search("bartosik").total == 1
    assert _search("BARTOSIK").total == 1


def test_search_by_city(app, make_client):
    make_client("Pierwszy", city="Dobrzyca")
    make_client("Drugi", city="Jarocin")
    assert _search("Dobrzyca").total == 1


def test_search_by_nip_ignores_separators(app, make_client):
    make_client("Z NIP-em", nip="6171010149", nip_valid=True)
    assert _search("617-101-01-49").total == 1
    assert _search("6171010149").total == 1


def test_search_by_acronym_keeps_leading_zero(app, make_client):
    make_client("Stara seria", acronym="0156")
    make_client("Nowa seria", acronym="10156")

    page = _search("0156")
    names = sorted(row[0].name for row in page.rows)
    # "0156" jest fragmentem "10156", więc oba trafienia są poprawne —
    # ważne, że rekord z wiodącym zerem w ogóle się znajduje.
    assert "Stara seria" in names


# ---------------------------------------------------------------------------
# Filtry
# ---------------------------------------------------------------------------


def test_filter_by_city_is_exact(app, make_client):
    from app.services.clients import ClientFilters, list_clients

    make_client("Pierwszy", city="Sobótka")
    make_client("Drugi", city="Sobótka Wielka")

    page = list_clients(ClientFilters(city="Sobótka"))
    assert page.total == 1


def test_filter_by_tag(app, make_client):
    from app.services.clients import ClientFilters, list_clients

    make_client("Oznaczony", tags=["do-weryfikacji"])
    make_client("Czysty")

    page = list_clients(ClientFilters(tag="do-weryfikacji"))
    assert page.total == 1
    assert page.rows[0][0].name == "Oznaczony"


def test_filter_by_status(app, make_client):
    from app.models import ClientStatus
    from app.services.clients import ClientFilters, list_clients

    make_client("Aktywny")
    make_client("Na czarnej liście", status=ClientStatus.BLACKLIST)

    page = list_clients(ClientFilters(status="BLACKLIST"))
    assert page.total == 1


def test_unknown_status_in_url_does_not_crash(app, make_client):
    """Ręcznie podrobiony parametr w adresie nie może wywalić widoku."""
    from app.services.clients import ClientFilters, list_clients

    make_client("Ktoś")
    page = list_clients(ClientFilters(status="NIE_MA_TAKIEGO"))
    assert page.total == 1


def test_filter_has_email_and_has_phone(app, make_client):
    from app.services.clients import ClientFilters, list_clients

    make_client("Z mailem", email="a@b.pl")
    make_client("Z telefonem", phones=["+48601092947"])
    make_client("Bez niczego")

    assert list_clients(ClientFilters(has_email=True)).total == 1
    assert list_clients(ClientFilters(has_phone=True)).total == 1


def test_filters_combine(app, make_client):
    from app.services.clients import ClientFilters, list_clients

    make_client("Trafiony", city="Dobrzyca", email="a@b.pl")
    make_client("Zły mail", city="Dobrzyca")
    make_client("Złe miasto", city="Jarocin", email="c@d.pl")

    page = list_clients(ClientFilters(city="Dobrzyca", has_email=True))
    assert page.total == 1
    assert page.rows[0][0].name == "Trafiony"


# ---------------------------------------------------------------------------
# Stronicowanie
# ---------------------------------------------------------------------------


def test_pagination_splits_by_page_size(app, make_client):
    from app.services.clients import PAGE_SIZE, ClientFilters, list_clients

    for index in range(PAGE_SIZE + 5):
        make_client(f"Klient {index:03d}")

    first = list_clients(ClientFilters(page=1))
    second = list_clients(ClientFilters(page=2))

    assert first.total == PAGE_SIZE + 5
    assert len(first.rows) == PAGE_SIZE
    assert len(second.rows) == 5
    assert first.has_next is True
    assert second.has_next is False
    assert second.has_prev is True

    # Żaden klient nie może wpaść na obie strony ani wypaść z obu.
    ids = {row[0].id for row in first.rows} | {row[0].id for row in second.rows}
    assert len(ids) == PAGE_SIZE + 5


# ---------------------------------------------------------------------------
# Edycja pól
# ---------------------------------------------------------------------------


def test_field_edit_normalizes_and_logs_activity(app, session, make_client):
    from app.models import ActivityType
    from app.services.clients import timeline, update_field

    client = make_client("Testowy", city="JAROCIN")
    result = update_field(client, "city", "SOBÓTKA")
    session.flush()

    assert result.ok is True
    assert client.city == "Sobótka", "miasto ma wejść w Title Case"

    entries = timeline(client.id)
    assert entries[0].type == ActivityType.CLIENT_UPDATED
    assert entries[0].meta["field"] == "city"
    assert entries[0].meta["from"] == "JAROCIN"
    assert entries[0].meta["to"] == "Sobótka"


def test_invalid_email_is_rejected_not_silently_cleared(app, session, make_client):
    """Zły adres nie może wyczyścić poprawnego, który już był zapisany."""
    from app.services.clients import update_field

    client = make_client("Testowy", email="dobry@example.pl")
    result = update_field(client, "email", "to-nie-jest-mail")

    assert result.ok is False
    assert result.error
    assert client.email == "dobry@example.pl"


def test_invalid_postal_code_is_rejected(app, session, make_client):
    from app.services.clients import update_field

    client = make_client("Testowy")
    result = update_field(client, "postal_code", "R42XV88")

    assert result.ok is False
    assert client.postal_code is None


def test_bad_nip_is_saved_but_flagged(app, session, make_client):
    """NIP bez sumy kontrolnej zapisujemy — ale z czerwoną flagą.

    Inaczej niż e-mail: cyfry są, więc wartość ma sens do przejrzenia,
    tylko nie przechodzi walidacji.
    """
    from app.services.clients import update_field

    client = make_client("Testowy")
    result = update_field(client, "nip", "618-001-85-18")

    assert result.ok is True
    assert client.nip == "6180018518"
    assert client.nip_valid is False
    assert result.warning


def test_empty_name_is_rejected(app, session, make_client):
    from app.services.clients import update_field

    client = make_client("Ma nazwę")
    assert update_field(client, "name", "   ").ok is False
    assert client.name == "Ma nazwę"


def test_duplicate_acronym_is_rejected(app, session, make_client):
    """Akronim to klucz deduplikacji importu — nie może się powtórzyć."""
    from app.services.clients import update_field

    make_client("Pierwszy", acronym="10009")
    second = make_client("Drugi", acronym="10010")

    result = update_field(second, "acronym", "10009")
    assert result.ok is False
    assert second.acronym == "10010"


def test_unchanged_value_does_not_create_activity(app, session, make_client):
    """Zapis tej samej wartości nie ma zaśmiecać osi czasu."""
    from app.services.clients import timeline, update_field

    client = make_client("Testowy", city="Dobrzyca")
    before = len(timeline(client.id))

    update_field(client, "city", "Dobrzyca")
    session.flush()

    assert len(timeline(client.id)) == before


# ---------------------------------------------------------------------------
# Telefony
# ---------------------------------------------------------------------------


def test_first_phone_becomes_primary(app, session, make_client):
    from app.services.clients import add_phone

    client = make_client("Bez telefonu")
    add_phone(client, "601 092 947")
    session.flush()

    assert client.phones[0].is_primary is True
    assert client.phones[0].e164 == "+48601092947"


def test_unparseable_phone_is_kept_with_warning(app, session, make_client):
    """Numeru nie do sparsowania nie wyrzucamy — zostaje w `raw`."""
    from app.services.clients import add_phone

    client = make_client("Testowy")
    result = add_phone(client, "7649233")
    session.flush()

    assert result.ok is True
    assert result.warning
    assert client.phones[0].e164 is None
    assert client.phones[0].raw == "7649233"


def test_duplicate_phone_is_rejected(app, session, make_client):
    from app.services.clients import add_phone

    client = make_client("Testowy", phones=["+48601092947"])
    result = add_phone(client, "601-092-947")

    assert result.ok is False
    assert len(client.phones) == 1


def test_removing_primary_phone_promotes_another(app, session, make_client):
    """Klient z numerami nie może zostać bez numeru głównego."""
    from app.services.clients import remove_phone

    client = make_client("Testowy", phones=["+48601092947", "+48607137842"])
    session.flush()
    primary_id = client.primary_phone.id

    remove_phone(client, primary_id)
    session.flush()

    assert len(client.phones) == 1
    assert client.phones[0].is_primary is True


# ---------------------------------------------------------------------------
# Tagi, notatki, status
# ---------------------------------------------------------------------------


def test_tag_is_reused_not_duplicated(app, session, make_client):
    from app.models import Tag
    from app.services.clients import add_tag

    first = make_client("Pierwszy")
    second = make_client("Drugi")

    add_tag(first, "wazny")
    add_tag(second, "WAZNY")  # ta sama nazwa, inna wielkość liter
    session.flush()

    count = session.scalar(
        sa.select(sa.func.count()).select_from(Tag).where(Tag.name == "wazny")
    )
    assert count == 1
    assert second.has_tag("wazny")


def test_note_lands_on_timeline(app, session, make_client):
    from app.models import ActivityType
    from app.services.clients import add_note, timeline

    client = make_client("Testowy")
    add_note(client, "Zamawia nawóz na wiosnę.", pinned=True)
    session.flush()

    entry = timeline(client.id)[0]
    assert entry.type == ActivityType.NOTE_ADDED
    assert entry.description == "Zamawia nawóz na wiosnę."


def test_sms_consent_records_timestamp(app, session, make_client):
    from app.services.clients import set_sms_consent

    client = make_client("Testowy")
    set_sms_consent(client, True)
    session.flush()

    assert client.sms_consent is True
    assert client.sms_consent_at is not None

    set_sms_consent(client, False)
    session.flush()
    assert client.sms_consent_at is None


# ---------------------------------------------------------------------------
# Widoki HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def logged_in(client):
    """Klient testowy po zalogowaniu. Hasło z conftestu."""
    client.post("/login", data={"login": "Milosz", "password": "testowe-haslo-123"})
    return client


def test_list_renders(app, session, make_client, logged_in):
    make_client("Gospodarstwo Rolne Kowalski", city="Dobrzyca")
    session.commit()

    response = logged_in.get("/clients/")
    assert response.status_code == 200
    assert "Gospodarstwo Rolne Kowalski" in response.get_data(as_text=True)


def test_htmx_request_returns_fragment_not_full_page(
    app, session, make_client, logged_in
):
    """Żądanie HTMX ma wrócić samą tabelą, bez sidebara i <html>."""
    make_client("Widoczny")
    session.commit()

    response = logged_in.get("/clients/?q=Widoczny", headers={"HX-Request": "true"})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Widoczny" in body
    assert "<html" not in body
    assert 'id="tabela-klientow"' in body


def test_detail_renders(app, session, make_client, logged_in):
    client_row = make_client("Panel testowy", city="Jarocin", phones=["+48601092947"])
    session.commit()

    response = logged_in.get(f"/clients/{client_row.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Panel testowy" in body
    assert "601 092 947" in body


def test_delete_requires_exact_name(app, session, make_client, logged_in):
    from app.models import Client

    client_row = make_client("Do usunięcia")
    session.commit()
    client_id = client_row.id

    logged_in.post(f"/clients/{client_id}/usun", data={"confirm": "cokolwiek"})
    assert session.get(Client, client_id) is not None

    logged_in.post(f"/clients/{client_id}/usun", data={"confirm": "Do usunięcia"})
    assert session.get(Client, client_id) is None
