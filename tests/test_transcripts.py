"""Testy ekranu rozmów (etap 4).

Ekran istnieje po to, żeby posprzątać po automacie: przypisać rozmowę, której
nie dało się dopasować, i poprawić tę dopasowaną do niewłaściwego gospodarstwa.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def logged_in(client):
    client.post("/login", data={"login": "Milosz", "password": "testowe-haslo-123"})
    return client


@pytest.fixture
def make_client(session):
    from app.models import Client, Phone

    def make(name: str, *phones: str, city: str | None = None) -> Client:
        row = Client(name=name, city=city)
        for index, e164 in enumerate(phones):
            row.phones.append(Phone(e164=e164, raw=e164, is_primary=index == 0))
        session.add(row)
        session.flush()
        return row

    return make


@pytest.fixture
def make_transcript(session):
    from app.models import Transcript, TranscriptStatus

    def make(
        text: str = "Rozmowa testowa.",
        *,
        phone: str | None = None,
        status: TranscriptStatus = TranscriptStatus.PENDING,
        client_id: int | None = None,
    ) -> Transcript:
        transcript = Transcript(
            raw_text=text,
            phone_raw=phone,
            phone_e164=phone,
            status=status,
            client_id=client_id,
        )
        session.add(transcript)
        session.flush()
        return transcript

    return make


# ---------------------------------------------------------------------------
# Dostęp
# ---------------------------------------------------------------------------


def test_screen_requires_login(client, session):
    response = client.get("/transcripts/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------


def test_list_renders(logged_in, session, make_transcript):
    make_transcript("Rozmowa o siewniku Kongskilde.")
    session.commit()

    response = logged_in.get("/transcripts/")

    assert response.status_code == 200
    assert "Kongskilde" in response.get_data(as_text=True)


def test_htmx_request_returns_only_the_table(logged_in, session, make_transcript):
    make_transcript("Rozmowa o pługu.")
    session.commit()

    response = logged_in.get("/transcripts/?q=pługu", headers={"HX-Request": "true"})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<html" not in body
    assert 'id="tabela-rozmow"' in body


def test_attention_tab_shows_only_unfinished_calls(logged_in, session, make_transcript):
    from app.models import TranscriptStatus

    make_transcript("Bez numeru.", status=TranscriptStatus.NEEDS_REVIEW)
    make_transcript("Wywalona analiza.", status=TranscriptStatus.FAILED)
    make_transcript("Wszystko gra.", status=TranscriptStatus.DONE)
    session.commit()

    body = logged_in.get("/transcripts/?status=uwaga").get_data(as_text=True)

    assert "Bez numeru." in body
    assert "Wywalona analiza." in body
    assert "Wszystko gra." not in body


def test_search_by_phone_ignores_formatting(logged_in, session, make_transcript):
    make_transcript("Rozmowa z numerem.", phone="+48601092947")
    session.commit()

    for query in ("601092947", "601-092-947", "+48601092947"):
        body = logged_in.get(f"/transcripts/?q={query}").get_data(as_text=True)
        assert "Rozmowa z numerem." in body, f"zapis {query} nic nie znalazł"


def test_status_counts_add_up(session, make_transcript):
    from app.models import TranscriptStatus
    from app.services.transcripts import ATTENTION, status_counts

    make_transcript(status=TranscriptStatus.NEEDS_REVIEW)
    make_transcript(status=TranscriptStatus.FAILED)
    make_transcript(status=TranscriptStatus.DONE)
    session.commit()

    counts = status_counts()

    assert counts["total"] == 3
    assert counts[ATTENTION] == 2
    assert counts["DONE"] == 1


# ---------------------------------------------------------------------------
# Panel rozmowy i ręczne przypisanie
# ---------------------------------------------------------------------------


def test_detail_shows_candidates_for_a_shared_number(
    logged_in, session, make_client, make_transcript
):
    make_client("Gospodarstwo Kowalski Jan", "+48601092947")
    make_client("Gospodarstwo Kowalska Anna", "+48601092947")
    transcript = make_transcript("Rozmowa.", phone="+48601092947")
    session.commit()

    body = logged_in.get(f"/transcripts/{transcript.id}").get_data(as_text=True)

    assert "Kowalski Jan" in body
    assert "Kowalska Anna" in body


def test_manual_assignment_writes_to_the_client_timeline(
    logged_in, session, make_client, make_transcript
):
    from app.models import ActivityType, Transcript

    target = make_client("Gospodarstwo Docelowe")
    transcript = make_transcript("Rozmowa bez numeru.")
    session.commit()
    transcript_id, target_id = transcript.id, target.id

    response = logged_in.post(
        f"/transcripts/{transcript_id}/przypisz",
        data={"client_id": target_id},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert session.get(Transcript, transcript_id).client_id == target_id

    types = [a.type for a in session.get(type(target), target_id).activities]
    assert ActivityType.CALL_TRANSCRIBED in types


def test_reassignment_leaves_a_trace_at_the_previous_client(
    logged_in, session, make_client, make_transcript
):
    from app.models import Client, Transcript

    wrong = make_client("Nie ten klient")
    right = make_client("Ten właściwy")
    transcript = make_transcript("Rozmowa.", client_id=wrong.id)
    session.commit()
    transcript_id, wrong_id, right_id = transcript.id, wrong.id, right.id

    logged_in.post(
        f"/transcripts/{transcript_id}/przypisz",
        data={"client_id": right_id},
        follow_redirects=True,
    )

    assert session.get(Transcript, transcript_id).client_id == right_id
    titles = [a.title for a in session.get(Client, wrong_id).activities]
    assert any("przeniesiona" in title for title in titles)


def test_unassign_sends_the_call_back_to_review(
    logged_in, session, make_client, make_transcript
):
    from app.models import Transcript, TranscriptStatus

    owner = make_client("Klient")
    transcript = make_transcript("Rozmowa.", client_id=owner.id)
    session.commit()
    transcript_id = transcript.id

    logged_in.post(f"/transcripts/{transcript_id}/odepnij", follow_redirects=True)

    refreshed = session.get(Transcript, transcript_id)
    assert refreshed.client_id is None
    assert refreshed.status == TranscriptStatus.NEEDS_REVIEW


def test_reprocess_finds_a_client_added_after_the_call(
    logged_in, session, make_client, make_transcript
):
    """Typowy scenariusz: numer dopisano klientowi już po wpłynięciu rozmowy."""
    from app.models import Transcript, TranscriptStatus

    transcript = make_transcript(
        "Rozmowa.", phone="+48601092947", status=TranscriptStatus.NEEDS_REVIEW
    )
    owner = make_client("Dopisany później", "+48601092947")
    session.commit()
    transcript_id, owner_id = transcript.id, owner.id

    logged_in.post(f"/transcripts/{transcript_id}/przetworz", follow_redirects=True)

    refreshed = session.get(Transcript, transcript_id)
    assert refreshed.client_id == owner_id
    assert refreshed.status == TranscriptStatus.PENDING


def test_client_picker_returns_a_fragment(
    logged_in, session, make_client, make_transcript
):
    make_client("Gospodarstwo Rolne Bartosik", city="Dobrzyca")
    transcript = make_transcript("Rozmowa.")
    session.commit()

    response = logged_in.get(f"/transcripts/{transcript.id}/klienci?q=Bartosik")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<html" not in body
    assert "Bartosik" in body


def test_full_text_is_served_as_a_fragment(logged_in, session, make_transcript):
    transcript = make_transcript("Pełny zapis rozmowy o kombajnie.")
    session.commit()

    response = logged_in.get(f"/transcripts/{transcript.id}/tresc")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<html" not in body
    assert "kombajnie" in body


def test_missing_transcript_gives_404(logged_in, session):
    assert logged_in.get("/transcripts/999999").status_code == 404


def test_timeline_offers_to_expand_the_call(
    logged_in, session, make_client, make_transcript
):
    """Na osi czasu klienta stoi wpis o rozmowie z odnośnikiem do pełnego zapisu."""
    from app.models import ActivityActor
    from app.services import matching

    owner = make_client("Klient z rozmową", "+48601092947")
    transcript = make_transcript("Zapis rozmowy.", phone="+48601092947")
    matching.attach(transcript, owner, actor=ActivityActor.SYSTEM)
    session.commit()

    body = logged_in.get(f"/clients/{owner.id}").get_data(as_text=True)

    assert "Rozmowa telefoniczna" in body
    assert "pokaż zapis rozmowy" in body
    assert f"/transcripts/{transcript.id}/tresc" in body


def test_dashboard_links_to_calls_needing_attention(logged_in, session, make_transcript):
    from app.models import TranscriptStatus

    make_transcript("Bez numeru.", status=TranscriptStatus.NEEDS_REVIEW)
    session.commit()

    body = logged_in.get("/").get_data(as_text=True)

    assert "Rozmowy do przejrzenia" in body
    assert "/transcripts/?status=uwaga" in body


def test_stylesheet_is_served_without_login(client, session):
    """Ekran logowania musi mieć style.

    Pliki statyczne nie należą do żadnego blueprintu, więc wartownik logowania
    sprawdzający wyłącznie `request.blueprint` odsyłał je na /login i logowanie
    renderowało się jako goły HTML.
    """
    response = client.get("/static/css/tailwind.css")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Karta analizy (etap 5)
# ---------------------------------------------------------------------------


def test_waiting_call_polls_for_its_analysis(logged_in, session, make_transcript):
    """Dopóki rozmowa czeka w kolejce, panel sam dopytuje o wynik."""
    transcript = make_transcript("Rozmowa w kolejce.")
    session.commit()

    body = logged_in.get(f"/transcripts/{transcript.id}").get_data(as_text=True)

    assert 'hx-trigger="every 3s"' in body
    assert f"/transcripts/{transcript.id}/analiza" in body


def test_finished_analysis_stops_the_polling(logged_in, session, make_transcript):
    """Gotowy wynik wraca bez wyzwalacza — odpytywanie samo się kończy."""
    from app.models import TranscriptStatus

    transcript = make_transcript("Rozmowa przeanalizowana.")
    transcript.ai_summary = "Klient prosi o ofertę na siewnik."
    transcript.ai_sentiment = "positive"
    transcript.ai_outcome = "zainteresowany"
    transcript.ai_raw = {"key_points": ["Prosi o ofertę"], "events": []}
    transcript.status = TranscriptStatus.DONE
    session.commit()

    body = logged_in.get(f"/transcripts/{transcript.id}/analiza").get_data(as_text=True)

    assert "<html" not in body
    assert "Klient prosi o ofertę na siewnik." in body
    assert "Pozytywny" in body
    assert 'hx-trigger="every 3s"' not in body


def test_undated_arrangement_is_shown_but_not_in_the_calendar(
    logged_in, session, make_transcript
):
    from app.models import TranscriptStatus

    transcript = make_transcript("Rozmowa.")
    transcript.ai_summary = "Ustalenia bez terminu."
    transcript.ai_raw = {
        "events": [{"title": "Przegląd kiedyś na jesieni", "date": None}],
        "key_points": [],
    }
    transcript.status = TranscriptStatus.DONE
    session.commit()

    body = logged_in.get(f"/transcripts/{transcript.id}/analiza").get_data(as_text=True)

    assert "Bez ustalonego terminu" in body
    assert "Przegląd kiedyś na jesieni" in body


def test_failed_analysis_says_the_text_is_safe(logged_in, session, make_transcript):
    from app.models import TranscriptStatus

    transcript = make_transcript("Rozmowa, której nie udało się przeanalizować.")
    transcript.status = TranscriptStatus.FAILED
    transcript.attempts = 3
    transcript.error = "Model nie odpowiedział: timeout"
    session.commit()

    body = logged_in.get(f"/transcripts/{transcript.id}").get_data(as_text=True)

    assert "nie powiodła się" in body
    assert "timeout" in body
    assert "Rozmowa, której nie udało się przeanalizować." in body
