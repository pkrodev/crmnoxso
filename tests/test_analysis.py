"""Testy przetwarzania rozmów: zapis analizy, wydarzenia, ponawianie (etap 5).

Dostawca modelu jest podstawiony — testy nie ruszają sieci i nie kosztują.
Sprawdzamy to, co dzieje się z odpowiedzią PO jej otrzymaniu, bo tam błąd
byłby najdroższy: termin wpisany do kalendarza o złej godzinie albo nadpisana
nazwa klienta zaimportowana z arkusza.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app.services.ai import AiError, AiResult, parse_response

pytestmark = pytest.mark.db

ODPOWIEDZ = {
    "summary": "Klient pyta o siewnik, umówiony pokaz.",
    "client_name": "Gospodarstwo Rolne Kowalski",
    "sentiment": "positive",
    "outcome": "umówiono spotkanie",
    "events": [
        {
            "title": "Pokaz siewnika",
            "description": "U klienta na polu",
            "date": "2026-09-01",
            "time": "14:00",
            "confidence": "high",
        }
    ],
    "follow_up_needed": True,
    "key_points": ["Interesuje go siewnik"],
}


class FakeProvider:
    """Dostawca, który oddaje z góry ustaloną odpowiedź albo rzuca błędem."""

    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.payload = payload if payload is not None else ODPOWIEDZ
        self.error = error
        self.calls: list[tuple[str, dt.date]] = []

    def analyse(self, text: str, *, today: dt.date) -> AiResult:
        self.calls.append((text, today))
        if self.error is not None:
            raise self.error
        content = json.dumps(self.payload, ensure_ascii=False)
        return AiResult(
            analysis=parse_response(content),
            raw=json.loads(content),
            tokens_used=1234,
            model="fake",
        )


@pytest.fixture
def make_client(session):
    from app.models import Client, Phone

    def make(name: str, *phones: str, source=None) -> Client:
        from app.models import ClientSource

        client = Client(name=name, source=source or ClientSource.IMPORT)
        for index, e164 in enumerate(phones):
            client.phones.append(Phone(e164=e164, raw=e164, is_primary=index == 0))
        session.add(client)
        session.flush()
        return client

    return make


@pytest.fixture
def make_transcript(session):
    from app.models import Transcript, TranscriptStatus

    def make(text: str = "Rozmowa o siewniku.", *, client=None, phone=None, status=None):
        transcript = Transcript(
            raw_text=text,
            phone_raw=phone,
            phone_e164=phone,
            client_id=client.id if client else None,
            status=status
            or (TranscriptStatus.PENDING if client else TranscriptStatus.NEEDS_REVIEW),
        )
        session.add(transcript)
        session.flush()
        return transcript

    return make


# ---------------------------------------------------------------------------
# Udana analiza
# ---------------------------------------------------------------------------


def test_successful_analysis_fills_the_transcript(session, make_client, make_transcript):
    from app.models import TranscriptStatus
    from app.services import analysis

    client = make_client("Gospodarstwo Rolne Kowalski", "+48601092947")
    transcript = make_transcript(client=client)
    session.commit()

    report = analysis.process(transcript, FakeProvider())

    assert report.processed == 1
    assert transcript.status == TranscriptStatus.DONE
    assert transcript.ai_summary.startswith("Klient pyta")
    assert transcript.ai_sentiment == "positive"
    assert transcript.ai_outcome == "umówiono spotkanie"
    assert transcript.tokens_used == 1234
    assert transcript.processed_at is not None
    assert transcript.error is None
    assert transcript.ai_raw["key_points"] == ["Interesuje go siewnik"]


def test_model_gets_the_polish_date_of_today(session, make_client, make_transcript):
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()
    provider = FakeProvider()

    analysis.process(transcript, provider)

    assert provider.calls[0][1] == analysis.today_local()


def test_transcript_without_a_client_stays_in_review(session, make_transcript):
    """Podsumowanie pomaga wskazać klienta, ale wskazać musi go człowiek."""
    from app.models import TranscriptStatus
    from app.services import analysis

    transcript = make_transcript()
    session.commit()

    analysis.process(transcript, FakeProvider())

    assert transcript.ai_summary is not None
    assert transcript.status == TranscriptStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# Wydarzenia
# ---------------------------------------------------------------------------


def test_event_is_created_unconfirmed(session, make_client, make_transcript):
    from app.models import EventSource
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    analysis.process(transcript, FakeProvider())

    event = transcript.events[0]
    assert event.source == EventSource.AI
    assert event.confirmed is False, "wydarzenie z AI nigdy nie jest potwierdzone"
    assert event.confidence == "high"
    assert event.title == "Pokaz siewnika"


def test_summer_time_is_converted_correctly(session, make_client, make_transcript):
    """14:00 czasu polskiego 1 września to 12:00 UTC — inaczej termin ucieka."""
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    analysis.process(transcript, FakeProvider())

    starts_at = transcript.events[0].starts_at.astimezone(dt.UTC)
    assert starts_at == dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)


def test_winter_time_is_converted_correctly(session, make_client, make_transcript):
    """Ta sama godzina w styczniu to już 13:00 UTC — przesunięcie zmienia się."""
    from app.services import analysis

    payload = {
        **ODPOWIEDZ,
        "events": [{"title": "Przegląd", "date": "2027-01-15", "time": "14:00"}],
    }
    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    analysis.process(transcript, FakeProvider(payload))

    starts_at = transcript.events[0].starts_at.astimezone(dt.UTC)
    assert starts_at == dt.datetime(2027, 1, 15, 13, 0, tzinfo=dt.UTC)


def test_event_without_a_time_is_all_day(session, make_client, make_transcript):
    from app.services import analysis

    payload = {**ODPOWIEDZ, "events": [{"title": "Dostawa", "date": "2026-09-01"}]}
    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    analysis.process(transcript, FakeProvider(payload))

    assert transcript.events[0].all_day is True


def test_event_without_a_date_does_not_reach_the_calendar(
    session, make_client, make_transcript
):
    """Termin nieustalony zostaje w ai_raw — wymyślanie daty byłoby gorsze."""
    from app.services import analysis

    payload = {
        **ODPOWIEDZ,
        "events": [{"title": "Kiedyś przegląd", "date": None, "confidence": "low"}],
    }
    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    analysis.process(transcript, FakeProvider(payload))

    assert transcript.events == []
    assert transcript.ai_raw["events"][0]["title"] == "Kiedyś przegląd"


def test_low_confidence_is_written_into_the_description(
    session, make_client, make_transcript
):
    from app.services import analysis

    payload = {
        **ODPOWIEDZ,
        "events": [{"title": "Spotkanie", "date": "2026-09-01", "confidence": "low"}],
    }
    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    analysis.process(transcript, FakeProvider(payload))

    assert "niepewny" in transcript.events[0].description


def test_event_lands_on_the_client_timeline(session, make_client, make_transcript):
    from app.models import ActivityActor, ActivityType
    from app.services import analysis

    client = make_client("Klient")
    transcript = make_transcript(client=client)
    session.commit()

    analysis.process(transcript, FakeProvider())

    entry = next(a for a in client.activities if a.type == ActivityType.EVENT_SCHEDULED)
    assert entry.actor == ActivityActor.AI
    assert "Pokaz siewnika" in entry.title


# ---------------------------------------------------------------------------
# Klient i oś czasu
# ---------------------------------------------------------------------------


def test_placeholder_client_gets_the_name_from_the_call(session, make_transcript):
    from app.services import analysis, matching

    transcript = make_transcript(phone="+48601092947")
    outcome = matching.resolve(transcript)
    session.commit()
    assert outcome.created is True
    assert outcome.client.name.startswith("Nieznany")

    analysis.process(transcript, FakeProvider())

    assert transcript.client.name == "Gospodarstwo Rolne Kowalski"


def test_imported_client_name_is_never_overwritten(session, make_client, make_transcript):
    """Model nie ma prawa nadpisać nazwy z arkusza ani wpisanej ręcznie."""
    from app.services import analysis

    client = make_client("SKR w Stawiszynie", "+48601092947")
    transcript = make_transcript(client=client, phone="+48601092947")
    session.commit()

    analysis.process(transcript, FakeProvider())

    assert client.name == "SKR w Stawiszynie"


def test_summary_is_attached_to_the_existing_call_entry(session, make_transcript):
    """Jedna rozmowa to jedna pozycja na osi czasu, nie dwie."""
    from app.models import ActivityActor, ActivityType
    from app.services import analysis, matching

    transcript = make_transcript(phone="+48601092947")
    matching.resolve(transcript)
    session.commit()

    analysis.process(transcript, FakeProvider())

    calls = [
        a for a in transcript.client.activities if a.type == ActivityType.CALL_TRANSCRIBED
    ]
    assert len(calls) == 1
    assert calls[0].description.startswith("Klient pyta")
    assert calls[0].actor == ActivityActor.AI


# ---------------------------------------------------------------------------
# Błędy i ponawianie
# ---------------------------------------------------------------------------


def test_failure_counts_an_attempt_and_waits(session, make_client, make_transcript):
    from app.models import TranscriptStatus
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    report = analysis.process(transcript, FakeProvider(error=AiError("brak sieci")))

    assert report.failed == 1
    assert transcript.attempts == 1
    assert transcript.status == TranscriptStatus.PENDING
    assert transcript.next_attempt_at is not None
    assert "brak sieci" in transcript.error


def test_third_failure_gives_up(session, make_client, make_transcript):
    from app.models import TranscriptStatus
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()
    provider = FakeProvider(error=AiError("dostawca leży"))

    for _ in range(analysis.MAX_ATTEMPTS):
        transcript.next_attempt_at = None
        analysis.process(transcript, provider)

    assert transcript.attempts == analysis.MAX_ATTEMPTS
    assert transcript.status == TranscriptStatus.FAILED
    # Treść rozmowy zostaje ZAWSZE, także po nieudanej analizie.
    assert transcript.raw_text == "Rozmowa o siewniku."


def test_any_exception_is_caught_not_just_ours(session, make_client, make_transcript):
    from app.models import TranscriptStatus
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()

    analysis.process(transcript, FakeProvider(error=RuntimeError("cokolwiek")))

    assert transcript.attempts == 1
    assert transcript.status == TranscriptStatus.PENDING


# ---------------------------------------------------------------------------
# Kolejka
# ---------------------------------------------------------------------------


def test_queue_takes_waiting_calls_only(session, make_client, make_transcript):
    from app.models import TranscriptStatus
    from app.services import analysis

    client = make_client("Klient")
    waiting = make_transcript("Czeka.", client=client)
    make_transcript("Gotowa.", client=client, status=TranscriptStatus.DONE)
    make_transcript("Poległa.", client=client, status=TranscriptStatus.FAILED)
    session.commit()

    claimed = analysis.claim()

    assert [t.id for t in claimed] == [waiting.id]
    assert waiting.status == TranscriptStatus.PROCESSING


def test_queue_respects_the_waiting_period(session, make_client, make_transcript):
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()
    analysis.process(transcript, FakeProvider(error=AiError("chwilowa awaria")))

    assert analysis.claim() == []


def test_call_stuck_in_processing_returns_to_the_queue(
    session, make_client, make_transcript
):
    from app.models import TranscriptStatus
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    transcript.status = TranscriptStatus.PROCESSING
    transcript.next_attempt_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    session.commit()

    assert analysis.release_stuck() == 1
    assert transcript.status == TranscriptStatus.PENDING


def test_full_run_processes_the_queue(session, make_client, make_transcript):
    from app.services import analysis

    client = make_client("Klient")
    make_transcript("Pierwsza.", client=client)
    make_transcript("Druga.", client=client)
    session.commit()

    report = analysis.run_pending(FakeProvider())

    assert report.processed == 2
    assert report.events == 2
    assert report.tokens == 2468


# ---------------------------------------------------------------------------
# Ponowna analiza
# ---------------------------------------------------------------------------


def test_reprocessing_clears_the_result_but_keeps_confirmed_events(
    session, make_client, make_transcript
):
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()
    analysis.process(transcript, FakeProvider())

    confirmed = transcript.events[0]
    confirmed.confirmed = True
    session.commit()

    analysis.reset_for_reprocessing(transcript)
    session.commit()

    assert transcript.ai_summary is None
    assert transcript.attempts == 0
    assert transcript.raw_text == "Rozmowa o siewniku."
    # Potwierdzenie to decyzja użytkownika — nie kasujemy jej ponowną analizą.
    assert [e.id for e in transcript.events] == [confirmed.id]


def test_reprocessing_drops_unconfirmed_events(session, make_client, make_transcript):
    from app.services import analysis

    transcript = make_transcript(client=make_client("Klient"))
    session.commit()
    analysis.process(transcript, FakeProvider())
    assert len(transcript.events) == 1

    analysis.reset_for_reprocessing(transcript)
    session.commit()

    assert transcript.events == []


def test_monthly_token_count(session, make_client, make_transcript):
    from app.services import analysis

    client = make_client("Klient")
    for _ in range(3):
        transcript = make_transcript(client=client)
        session.commit()
        analysis.process(transcript, FakeProvider())

    assert analysis.tokens_used_this_month() == 3 * 1234
