"""Testy kalendarza (etap 6).

Nacisk na dwie rzeczy, w których cichy błąd byłby najbardziej kosztowny:

1. **Strefa czasowa.** W bazie wszystko jest w UTC, a użytkownik ma widzieć czas
   polski. Pomyłka o godzinę oznacza przyjazd do gospodarstwa nie wtedy, co
   trzeba — i to dwa razy do roku, przy zmianie czasu.
2. **Wydarzenie z AI to propozycja, nie fakt.** Nie ma prawa wyglądać ani
   zachowywać się jak potwierdzone, dopóki użytkownik go nie potwierdzi.
"""

from __future__ import annotations

import datetime as dt

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def logged_in(client):
    client.post("/login", data={"login": "Milosz", "password": "testowe-haslo-123"})
    return client


@pytest.fixture
def make_client(session):
    from app.models import Client

    def make(name: str = "Gospodarstwo Testowe") -> Client:
        row = Client(name=name)
        session.add(row)
        session.flush()
        return row

    return make


@pytest.fixture
def make_event(session):
    from app.models import CalendarEvent, EventSource

    def make(
        title: str = "Pokaz siewnika",
        *,
        starts_at: dt.datetime | None = None,
        source=EventSource.AI,
        confirmed: bool = False,
        all_day: bool = False,
        client=None,
        transcript=None,
        confidence: str | None = "high",
    ) -> CalendarEvent:
        event = CalendarEvent(
            title=title,
            starts_at=starts_at or dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC),
            all_day=all_day,
            source=source,
            confirmed=confirmed,
            confidence=confidence,
            client_id=client.id if client else None,
            transcript_id=transcript.id if transcript else None,
        )
        session.add(event)
        session.flush()
        return event

    return make


@pytest.fixture
def make_transcript(session):
    from app.models import Transcript, TranscriptStatus

    def make(text: str = "Zapis rozmowy o siewniku.", summary: str | None = None):
        transcript = Transcript(
            raw_text=text, ai_summary=summary, status=TranscriptStatus.DONE
        )
        session.add(transcript)
        session.flush()
        return transcript

    return make


# ---------------------------------------------------------------------------
# Dane dla FullCalendara
# ---------------------------------------------------------------------------


def test_feed_gives_polish_local_time(session, make_event):
    """12:00 UTC to 14:00 w Polsce — kalendarz dostaje czas z przesunięciem."""
    from app.services import calendar as service

    event = make_event(starts_at=dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC))

    payload = service.to_feed(event)

    assert payload["start"].startswith("2026-09-01T14:00:00")
    assert payload["start"].endswith("+02:00")


def test_feed_handles_winter_offset(session, make_event):
    """Zimą przesunięcie to godzina, nie dwie — termin nie ma prawa uciec."""
    from app.services import calendar as service

    event = make_event(starts_at=dt.datetime(2027, 1, 15, 13, 0, tzinfo=dt.UTC))

    payload = service.to_feed(event)

    assert payload["start"].startswith("2027-01-15T14:00:00")
    assert payload["start"].endswith("+01:00")


def test_all_day_event_has_no_time(session, make_event):
    from app.services import calendar as service

    event = make_event(all_day=True)

    payload = service.to_feed(event)

    assert payload["allDay"] is True
    assert payload["start"] == "2026-09-01"
    assert payload["end"] is None


def test_timed_event_gets_a_default_end(session, make_event):
    """AI nigdy nie podaje końca — bez domyślnej godziny kafelek byłby punktem."""
    from app.services import calendar as service

    payload = service.to_feed(make_event())

    assert payload["end"].startswith("2026-09-01T15:00:00")


@pytest.mark.parametrize(
    ("source_name", "confirmed", "expected"),
    [
        ("AI", False, "ev-ai"),
        ("AI", True, "ev-ai-confirmed"),
        ("MANUAL", True, "ev-manual"),
    ],
)
def test_each_kind_of_event_gets_its_own_look(
    session, make_event, source_name, confirmed, expected
):
    from app.models import EventSource
    from app.services import calendar as service

    event = make_event(source=EventSource[source_name], confirmed=confirmed)

    assert service.to_feed(event)["classNames"] == [expected]


def test_feed_endpoint_returns_json(logged_in, session, make_event):
    make_event()
    session.commit()

    response = logged_in.get("/calendar/wydarzenia?start=2026-08-01&end=2026-10-01")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload) == 1
    assert payload[0]["title"] == "Pokaz siewnika"


def test_feed_respects_the_range(logged_in, session, make_event):
    make_event("W zakresie", starts_at=dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC))
    make_event("Poza zakresem", starts_at=dt.datetime(2027, 9, 1, 12, 0, tzinfo=dt.UTC))
    session.commit()

    payload = logged_in.get(
        "/calendar/wydarzenia?start=2026-08-01&end=2026-10-01"
    ).get_json()

    assert [e["title"] for e in payload] == ["W zakresie"]


# ---------------------------------------------------------------------------
# Ekran
# ---------------------------------------------------------------------------


def test_screen_requires_login(client, session):
    assert client.get("/calendar/").status_code == 302


def test_screen_counts_proposals_waiting(logged_in, session, make_event):
    make_event("Do potwierdzenia", confirmed=False)
    make_event("Już potwierdzone", confirmed=True)
    session.commit()

    body = logged_in.get("/calendar/").get_data(as_text=True)

    assert "1 termin z rozmowy czeka" in body


def test_panel_shows_the_call_it_came_from(
    logged_in, session, make_event, make_transcript
):
    """Kontekst „skąd ten termin" ma być pod ręką, bez szukania po ekranach."""
    transcript = make_transcript(summary="Klient prosi o pokaz siewnika.")
    event = make_event(transcript=transcript)
    session.commit()

    body = logged_in.get(f"/calendar/{event.id}").get_data(as_text=True)

    assert "<html" not in body
    assert "Klient prosi o pokaz siewnika." in body
    assert f"/transcripts/{transcript.id}" in body


def test_panel_of_a_proposal_offers_confirmation(logged_in, session, make_event):
    event = make_event(confirmed=False)
    session.commit()

    body = logged_in.get(f"/calendar/{event.id}").get_data(as_text=True)

    assert "propozycja z rozmowy" in body
    assert f"/calendar/{event.id}/potwierdz" in body


def test_confirmed_event_has_no_confirm_button(logged_in, session, make_event):
    event = make_event(confirmed=True)
    session.commit()

    body = logged_in.get(f"/calendar/{event.id}").get_data(as_text=True)

    assert "/potwierdz" not in body


# ---------------------------------------------------------------------------
# Potwierdzanie, edycja, usuwanie
# ---------------------------------------------------------------------------


def test_confirming_marks_the_event_and_the_timeline(
    logged_in, session, make_client, make_event
):
    from app.models import ActivityActor, ActivityType, CalendarEvent

    owner = make_client()
    event = make_event(client=owner, confirmed=False)
    session.commit()
    event_id, owner_id = event.id, owner.id

    response = logged_in.post(f"/calendar/{event_id}/potwierdz")

    assert response.status_code == 200
    assert session.get(CalendarEvent, event_id).confirmed is True

    entry = next(
        a
        for a in session.get(type(owner), owner_id).activities
        if a.type == ActivityType.EVENT_SCHEDULED
    )
    assert entry.actor == ActivityActor.USER
    assert "Potwierdzono" in entry.title


def test_confirming_asks_the_grid_to_refresh(logged_in, session, make_event):
    """Bez tego kafelek w siatce nadal wyglądałby na niepotwierdzony."""
    event = make_event(confirmed=False)
    session.commit()

    response = logged_in.post(f"/calendar/{event.id}/potwierdz")

    assert response.headers.get("HX-Trigger") == "kalendarz:odswiez"


def test_editing_saves_polish_local_time(logged_in, session, make_event):
    from app.models import CalendarEvent

    event = make_event()
    session.commit()
    event_id = event.id

    logged_in.post(
        f"/calendar/{event_id}/zapisz",
        data={"title": "Przegląd kombajnu", "day": "2026-09-10", "time": "09:30"},
    )

    saved = session.get(CalendarEvent, event_id)
    assert saved.title == "Przegląd kombajnu"
    assert saved.starts_at.astimezone(dt.UTC) == dt.datetime(
        2026, 9, 10, 7, 30, tzinfo=dt.UTC
    )
    assert saved.all_day is False


def test_editing_a_proposal_confirms_it(logged_in, session, make_event):
    """Poprawiony termin przestaje być propozycją — decyzja już zapadła."""
    from app.models import CalendarEvent

    event = make_event(confirmed=False)
    session.commit()
    event_id = event.id

    logged_in.post(
        f"/calendar/{event_id}/zapisz", data={"title": "Poprawione", "day": "2026-09-10"}
    )

    assert session.get(CalendarEvent, event_id).confirmed is True


def test_editing_without_a_time_makes_it_all_day(logged_in, session, make_event):
    from app.models import CalendarEvent

    event = make_event()
    session.commit()
    event_id = event.id

    logged_in.post(
        f"/calendar/{event_id}/zapisz",
        data={"title": "Dostawa", "day": "2026-09-10", "time": ""},
    )

    assert session.get(CalendarEvent, event_id).all_day is True


def test_editing_without_a_title_shows_an_error_and_changes_nothing(
    logged_in, session, make_event
):
    from app.models import CalendarEvent

    event = make_event()
    session.commit()
    event_id = event.id

    body = logged_in.post(
        f"/calendar/{event_id}/zapisz", data={"title": "", "day": "2026-09-10"}
    ).get_data(as_text=True)

    assert "Podaj tytuł i datę." in body
    assert session.get(CalendarEvent, event_id).title == "Pokaz siewnika"


def test_manual_event_is_created_confirmed(logged_in, session, make_client):
    import sqlalchemy as sa

    from app.models import CalendarEvent, EventSource

    owner = make_client()
    session.commit()

    logged_in.post(
        "/calendar/nowe",
        data={
            "title": "Wizyta u klienta",
            "day": "2026-09-10",
            "time": "11:00",
            "client_id": owner.id,
        },
    )

    event = session.scalar(
        sa.select(CalendarEvent).where(CalendarEvent.title == "Wizyta u klienta")
    )
    assert event.source == EventSource.MANUAL
    assert event.confirmed is True
    assert event.client_id == owner.id


def test_deleting_asks_first(logged_in, session, make_event):
    from app.models import CalendarEvent

    event = make_event()
    session.commit()
    event_id = event.id

    body = logged_in.get(f"/calendar/{event_id}/usun-pytanie").get_data(as_text=True)

    assert "Usunąć wydarzenie?" in body
    assert session.get(CalendarEvent, event_id) is not None


def test_deleting_removes_it_and_leaves_a_trace(
    logged_in, session, make_client, make_event
):
    from app.models import ActivityType, CalendarEvent

    owner = make_client()
    event = make_event(client=owner)
    session.commit()
    event_id, owner_id = event.id, owner.id

    logged_in.post(f"/calendar/{event_id}/usun")

    assert session.get(CalendarEvent, event_id) is None
    titles = [
        a.title
        for a in session.get(type(owner), owner_id).activities
        if a.type == ActivityType.MANUAL
    ]
    assert any("Usunięto termin" in title for title in titles)


def test_missing_event_gives_404(logged_in, session):
    assert logged_in.get("/calendar/999999").status_code == 404
