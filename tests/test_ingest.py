"""Testy endpointu przyjmującego transkrypcje (etap 4).

Endpoint jest jedynym wejściem do systemu spoza sesji użytkownika — wrzuca tu
pliki osoba z zewnątrz. Sprawdzamy więc nie tylko „czy działa", ale i to, czego
robić NIE wolno: wpuścić żądania bez tokenu, przyjąć plik ponad limit
i rozsypać polskie znaki na pliku z Windowsa.
"""

from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.db

TOKEN = "token-testowy-ingest"
URL = "/api/ingest/transcript"


@pytest.fixture
def token(app):
    """Token endpointu ustawiony tylko na czas testu."""
    previous = app.config.get("INGEST_TOKEN")
    app.config["INGEST_TOKEN"] = TOKEN
    yield TOKEN
    app.config["INGEST_TOKEN"] = previous


def _auth(token_value: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_value}"}


def _post_json(client, token, **payload):
    return client.post(URL, json=payload, headers=_auth(token))


# ---------------------------------------------------------------------------
# Autoryzacja
# ---------------------------------------------------------------------------


def test_without_token_returns_401(client, token, session):
    response = client.post(URL, json={"text": "Rozmowa."})
    assert response.status_code == 401


def test_wrong_token_returns_401(client, token, session):
    response = client.post(URL, json={"text": "Rozmowa."}, headers=_auth("nie-ten"))
    assert response.status_code == 401


def test_token_without_bearer_prefix_returns_401(client, token, session):
    response = client.post(URL, json={"text": "x"}, headers={"Authorization": TOKEN})
    assert response.status_code == 401


def test_unconfigured_endpoint_refuses_everything(app, client, session):
    """Pusty INGEST_TOKEN nie może oznaczać „wpuszczaj wszystkich"."""
    previous = app.config.get("INGEST_TOKEN")
    app.config["INGEST_TOKEN"] = ""
    try:
        response = client.post(URL, json={"text": "Rozmowa."}, headers=_auth(""))
        assert response.status_code == 503
    finally:
        app.config["INGEST_TOKEN"] = previous


# ---------------------------------------------------------------------------
# Wariant JSON
# ---------------------------------------------------------------------------


def test_json_returns_202_immediately(client, token, session):
    from app.models import Transcript, TranscriptStatus

    response = _post_json(client, token, text="Rozmowa o siewniku.", phone="601-092-947")

    assert response.status_code == 202
    body = response.get_json()
    assert body["id"] > 0

    transcript = session.get(Transcript, body["id"])
    assert transcript.raw_text == "Rozmowa o siewniku."
    assert transcript.phone_e164 == "+48601092947"
    assert transcript.status == TranscriptStatus.PENDING


def test_json_without_text_is_rejected(client, token, session):
    response = _post_json(client, token, phone="601092947")
    assert response.status_code == 422
    assert "details" in response.get_json()


def test_empty_text_is_rejected(client, token, session):
    response = _post_json(client, token, text="   ")
    assert response.status_code == 422


def test_body_that_is_not_json_is_rejected(client, token, session):
    response = client.post(URL, data="cokolwiek", headers=_auth())
    assert response.status_code == 400


@pytest.mark.parametrize("value", ["2026-03-14", "14.03.2026", "14-03-2026"])
def test_date_is_accepted_in_polish_and_iso_notation(client, token, session, value):
    from datetime import date

    from app.models import Transcript

    response = _post_json(client, token, text="Rozmowa.", date=value)

    assert response.status_code == 202
    transcript = session.get(Transcript, response.get_json()["id"])
    assert transcript.call_date == date(2026, 3, 14)


def test_nonsense_date_is_rejected(client, token, session):
    response = _post_json(client, token, text="Rozmowa.", date="w przyszły wtorek")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Wariant multipart
# ---------------------------------------------------------------------------


def _upload(client, data: bytes, filename: str = "rozmowa.txt", **form):
    payload = {"file": (io.BytesIO(data), filename), **form}
    return client.post(
        URL, data=payload, content_type="multipart/form-data", headers=_auth()
    )


def test_utf8_file_is_accepted(client, token, session):
    from app.models import Transcript

    text = "Zażółć gęślą jaźń — rozmowa o kosiarce."
    response = _upload(client, text.encode("utf-8"), phone="601092947")

    assert response.status_code == 202
    transcript = session.get(Transcript, response.get_json()["id"])
    assert transcript.raw_text == text
    assert transcript.source_file == "rozmowa.txt"


def test_cp1250_file_keeps_polish_letters(client, token, session):
    """Pliki z Windowsa bywają w CP1250 — bez wykrycia kodowania byłyby krzaki."""
    from app.models import Transcript

    text = "Rozmowa z gospodarstwem Zażółć, ulica Świętego Ducha."
    response = _upload(client, text.encode("cp1250"))

    assert response.status_code == 202
    transcript = session.get(Transcript, response.get_json()["id"])
    assert "Zażółć" in transcript.raw_text
    assert "Świętego" in transcript.raw_text


def test_file_over_the_limit_is_refused(app, client, token, session):
    limit = app.config["INGEST_MAX_BYTES"]
    response = _upload(client, b"a" * (limit + 1))
    assert response.status_code == 413


def test_empty_file_is_refused(client, token, session):
    assert _upload(client, b"").status_code == 400


def test_path_is_stripped_from_the_file_name(client, token, session):
    from app.models import Transcript

    response = _upload(client, b"Rozmowa.", filename="C:\\nagrania\\a.txt")

    transcript = session.get(Transcript, response.get_json()["id"])
    assert transcript.source_file == "a.txt"


# ---------------------------------------------------------------------------
# Dopasowanie do klienta w chwili przyjęcia
# ---------------------------------------------------------------------------


def test_known_number_is_attached_to_its_client(client, token, session):
    from app.models import Client, Phone, Transcript

    existing = Client(name="Gospodarstwo Rolne Kowalski")
    existing.phones.append(Phone(e164="+48601092947", raw="601092947", is_primary=True))
    session.add(existing)
    session.commit()

    response = _post_json(client, token, text="Rozmowa.", phone="+48601092947")
    body = response.get_json()

    assert body["client_id"] == existing.id
    assert body["client_created"] is False
    assert session.get(Transcript, body["id"]).client_id == existing.id


def test_unknown_number_creates_a_client(client, token, session):
    from app.models import TAG_FROM_TRANSCRIPT, Client

    response = _post_json(client, token, text="Rozmowa.", phone="+48601092947")
    body = response.get_json()

    assert body["client_created"] is True
    created = session.get(Client, body["client_id"])
    assert created.has_tag(TAG_FROM_TRANSCRIPT)


def test_number_taken_from_the_text_when_field_is_missing(client, token, session):
    from app.models import Transcript

    response = _post_json(
        client, token, text="Dzień dobry, mój numer to 601 092 947, proszę oddzwonić."
    )

    transcript = session.get(Transcript, response.get_json()["id"])
    assert transcript.phone_e164 == "+48601092947"
    assert transcript.client_id is not None


def test_transcript_without_number_waits_for_a_human(client, token, session):
    from app.models import Transcript, TranscriptStatus

    response = _post_json(client, token, text="Rozmowa bez numeru w treści.")
    body = response.get_json()

    assert body["client_id"] is None
    transcript = session.get(Transcript, body["id"])
    assert transcript.status == TranscriptStatus.NEEDS_REVIEW
    # Surowy tekst zostaje w bazie ZAWSZE — nawet gdy nie ma do kogo go przypiąć.
    assert transcript.raw_text == "Rozmowa bez numeru w treści."
