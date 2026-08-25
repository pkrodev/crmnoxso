"""Przetwarzanie transkrypcji: analiza modelem, wydarzenia, ponawianie (etap 5).

Podział pracy: ``ai.py`` rozmawia z modelem i pilnuje kształtu odpowiedzi,
ten moduł decyduje, co z tą odpowiedzią zrobić w bazie. Dzięki temu testy
przetwarzania nie wymagają sieci — wystarczy podstawić własnego dostawcę.

Trzy rzeczy, które wynikają wprost ze specyfikacji:

* **Wydarzenia z AI nigdy nie są potwierdzone.** Powstają z ``confirmed=False``
  i taką mają zostać do decyzji użytkownika (etap 6 doda przycisk).
* **Surowy tekst zostaje zawsze.** Nieudana analiza zabiera transkrypcję na
  status ``FAILED``, ale treści rozmowy nie rusza.
* **Trzy próby z rosnącym odstępem**, potem ``FAILED`` i przycisk w interfejsie.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa

from app.extensions import db
from app.filters import WARSAW
from app.models import (
    Activity,
    ActivityActor,
    ActivityType,
    CalendarEvent,
    EventSource,
    Transcript,
    TranscriptStatus,
)
from app.services import matching
from app.services.ai import AiAnalysis, AiError, AiProvider, AiResult
from app.services.clients import log_activity

MAX_ATTEMPTS = 3

# Odstęp przed kolejną próbą, rosnąco. Awarie dostawcy modelu bywają
# kilkuminutowe, więc trzy próby w ciągu minuty nie dałyby nic poza spaleniem
# limitu prób dokładnie wtedy, gdy warto poczekać.
RETRY_DELAYS = (
    dt.timedelta(minutes=1),
    dt.timedelta(minutes=5),
    dt.timedelta(minutes=15),
)

# Po tylu minutach rozmowa w stanie PROCESSING wraca do kolejki. Zabezpieczenie
# na wypadek ubicia procesu w trakcie odpytywania modelu — bez tego rekord
# zostałby w „Przetwarzanie" na zawsze.
STUCK_AFTER = dt.timedelta(minutes=15)

BATCH_SIZE = 5

# Statusy, z których rozmowa może wejść do analizy. NEEDS_REVIEW też, i to jest
# świadome: rozmowa bez przypisanego klienta najbardziej potrzebuje podsumowania,
# bo to po nim użytkownik pozna, do kogo ją przypiąć. Status zostaje wtedy
# NEEDS_REVIEW — zakładka „Wymagają uwagi" ma nadal pokazywać to, co czeka
# na człowieka.
ANALYSABLE = (TranscriptStatus.PENDING, TranscriptStatus.NEEDS_REVIEW)


@dataclass(slots=True)
class Report:
    processed: int = 0
    failed: int = 0
    events: int = 0
    tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "przetworzone": self.processed,
            "nieudane": self.failed,
            "wydarzenia": self.events,
            "tokeny": self.tokens,
        }


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def today_local() -> dt.date:
    """Dzisiejsza data po polsku, nie po UTC.

    O 1:30 w nocy czasu polskiego UTC pokazuje jeszcze dzień poprzedni. Model
    dostałby wtedy złą datę odniesienia i „jutro" wypadłoby o dobę za wcześnie.
    """
    return _now().astimezone(WARSAW).date()


# ---------------------------------------------------------------------------
# Kolejka
# ---------------------------------------------------------------------------


def release_stuck() -> int:
    """Zwraca do kolejki rozmowy, które utknęły w trakcie przetwarzania."""
    stuck = db.session.scalars(
        sa.select(Transcript).where(
            Transcript.status == TranscriptStatus.PROCESSING,
            Transcript.next_attempt_at.is_not(None),
            Transcript.next_attempt_at <= _now(),
        )
    ).all()

    for transcript in stuck:
        transcript.status = _resting_status(transcript)
        transcript.next_attempt_at = None
    if stuck:
        db.session.commit()
    return len(stuck)


def _resting_status(transcript: Transcript) -> TranscriptStatus:
    """Stan, w którym rozmowa czeka: bez klienta zawsze „wymaga uwagi"."""
    if transcript.client_id is None:
        return TranscriptStatus.NEEDS_REVIEW
    return TranscriptStatus.PENDING


def claim(limit: int = BATCH_SIZE) -> list[Transcript]:
    """Bierze porcję rozmów do analizy i od razu oznacza je jako przetwarzane.

    ``FOR UPDATE ... SKIP LOCKED`` jest zabezpieczeniem na wypadek uruchomienia
    kilku workerów. Przy ``--workers 1`` z Procfile problem i tak nie występuje,
    ale koszt tej klauzuli to zero.
    """
    now = _now()
    rows = db.session.scalars(
        sa.select(Transcript)
        .where(
            Transcript.status.in_(ANALYSABLE),
            Transcript.ai_summary.is_(None),
            Transcript.attempts < MAX_ATTEMPTS,
            sa.or_(
                Transcript.next_attempt_at.is_(None),
                Transcript.next_attempt_at <= now,
            ),
        )
        .order_by(Transcript.created_at, Transcript.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()

    for transcript in rows:
        transcript.status = TranscriptStatus.PROCESSING
        transcript.next_attempt_at = now + STUCK_AFTER
    if rows:
        db.session.commit()
    return list(rows)


# ---------------------------------------------------------------------------
# Zapis wyniku
# ---------------------------------------------------------------------------


def _starts_at(day: dt.date, moment: dt.time | None) -> tuple[dt.datetime, bool]:
    """Data i godzina z modelu → moment w UTC. Bez godziny: wydarzenie całodniowe.

    Model podaje czas polski, w bazie trzymamy UTC (sekcja 12 specyfikacji).
    """
    if moment is None:
        local = dt.datetime.combine(day, dt.time(0, 0), tzinfo=WARSAW)
        return local.astimezone(dt.UTC), True
    local = dt.datetime.combine(day, moment, tzinfo=WARSAW)
    return local.astimezone(dt.UTC), False


def _event_description(event, client_name: str | None) -> str | None:
    parts: list[str] = []
    if event.description:
        parts.append(event.description)
    if event.confidence == "low":
        # Wymóg z sekcji 9: niską pewność odnotuj także w opisie, żeby było ją
        # widać w kalendarzu, a nie tylko w kolumnie bazy.
        parts.append("Termin niepewny — model wywnioskował go, zamiast usłyszeć.")
    if client_name:
        parts.append(f"Z rozmowy z: {client_name}")
    return "\n\n".join(parts) if parts else None


def create_events(transcript: Transcript, analysis: AiAnalysis) -> list[CalendarEvent]:
    """Wydarzenia z analizy. Bez daty nie powstaje nic — nie zgadujemy terminu."""
    created: list[CalendarEvent] = []
    client_name = transcript.client.name if transcript.client else None

    for item in analysis.events:
        if item.date is None:
            # Ustalenie bez terminu zostaje w ai_raw i pokazujemy je na ekranie
            # rozmowy. Wstawienie go do kalendarza wymagałoby wymyślenia daty.
            continue

        starts_at, all_day = _starts_at(item.date, item.time)
        event = CalendarEvent(
            client_id=transcript.client_id,
            transcript_id=transcript.id,
            title=item.title,
            description=_event_description(item, client_name),
            starts_at=starts_at,
            all_day=all_day,
            source=EventSource.AI,
            confidence=item.confidence,
            confirmed=False,  # NIGDY potwierdzone z automatu
        )
        db.session.add(event)
        created.append(event)

        if transcript.client is not None:
            log_activity(
                transcript.client,
                ActivityType.EVENT_SCHEDULED,
                f"Z rozmowy: {item.title}",
                description=f"Termin: {item.date.strftime('%d.%m.%Y')}"
                + (f", godz. {item.time.strftime('%H:%M')}" if item.time else "")
                + " — do potwierdzenia.",
                meta={"transcript_id": transcript.id, "confidence": item.confidence},
                actor=ActivityActor.AI,
            )

    return created


def _rename_placeholder_client(transcript: Transcript, analysis: AiAnalysis) -> None:
    """Klientowi założonemu z rozmowy nadaje nazwę, którą model usłyszał.

    Zmieniamy tylko nazwę tymczasową („Nieznany (601 092 947)") — nazwy wpisanej
    przez użytkownika ani zaimportowanej z arkusza model nie ma prawa nadpisać.
    """
    client = transcript.client
    if client is None or not analysis.client_name or not transcript.phone_e164:
        return
    placeholder = matching.phone_placeholder_name(transcript.phone_e164)
    if client.name != placeholder:
        return

    previous, client.name = client.name, analysis.client_name
    log_activity(
        client,
        ActivityType.CLIENT_UPDATED,
        "Nazwa uzupełniona z rozmowy",
        description=f"„{previous}” → „{analysis.client_name}”",
        meta={"field": "name", "from": previous, "to": analysis.client_name},
        actor=ActivityActor.AI,
    )


def _attach_summary_to_timeline(transcript: Transcript, analysis: AiAnalysis) -> None:
    """Dopisuje podsumowanie do wpisu o rozmowie na osi czasu klienta.

    Wpis powstał już przy dopasowaniu (etap 4), tylko bez treści. Zamiast dokładać
    drugi, uzupełniamy istniejący — oś czasu ma pokazywać jedną rozmowę jako
    jedną pozycję. Autor zmienia się na AI, bo widoczna treść jest wygenerowana.
    """
    if transcript.client_id is None:
        return

    activity = db.session.scalar(
        sa.select(Activity).where(
            Activity.client_id == transcript.client_id,
            Activity.type == ActivityType.CALL_TRANSCRIBED,
            Activity.meta["transcript_id"].astext == str(transcript.id),
        )
    )
    if activity is None or activity.description:
        return

    activity.description = analysis.summary
    activity.actor = ActivityActor.AI


def apply_result(transcript: Transcript, result: AiResult) -> list[CalendarEvent]:
    """Zapisuje udaną analizę. Bez ``commit`` — woła go wywołujący."""
    analysis = result.analysis

    transcript.ai_summary = analysis.summary
    transcript.ai_sentiment = analysis.sentiment
    transcript.ai_outcome = analysis.outcome
    transcript.ai_raw = result.raw
    transcript.tokens_used = result.tokens_used
    transcript.error = None
    transcript.processed_at = _now()
    transcript.next_attempt_at = None
    # Rozmowa bez klienta nadal wymaga człowieka, choć analizę już ma.
    transcript.status = (
        TranscriptStatus.DONE
        if transcript.client_id is not None
        else TranscriptStatus.NEEDS_REVIEW
    )

    _rename_placeholder_client(transcript, analysis)
    _attach_summary_to_timeline(transcript, analysis)
    return create_events(transcript, analysis)


def record_failure(transcript: Transcript, error: Exception) -> None:
    """Nieudana próba: licznik, komunikat i termin kolejnego podejścia."""
    transcript.attempts += 1
    transcript.error = str(error)[:2000]

    if transcript.attempts >= MAX_ATTEMPTS:
        transcript.status = TranscriptStatus.FAILED
        transcript.next_attempt_at = None
    else:
        transcript.status = _resting_status(transcript)
        transcript.next_attempt_at = _now() + RETRY_DELAYS[transcript.attempts - 1]

    db.session.commit()


# ---------------------------------------------------------------------------
# Przebieg
# ---------------------------------------------------------------------------


def process(transcript: Transcript, provider: AiProvider) -> Report:
    """Analiza jednej rozmowy. Wyjątki dostawcy zamienia na status, nie na crash."""
    report = Report()
    try:
        result = provider.analyse(transcript.raw_text, today=today_local())
    except AiError as exc:
        record_failure(transcript, exc)
        report.failed = 1
        return report
    except Exception as exc:  # dostawca może rzucić czymkolwiek
        record_failure(transcript, exc)
        report.failed = 1
        return report

    events = apply_result(transcript, result)
    db.session.commit()

    report.processed = 1
    report.events = len(events)
    report.tokens = result.tokens_used or 0
    return report


def run_pending(provider: AiProvider, limit: int = BATCH_SIZE) -> Report:
    """Jeden przebieg zadania w tle."""
    release_stuck()

    total = Report()
    for transcript in claim(limit):
        one = process(transcript, provider)
        total.processed += one.processed
        total.failed += one.failed
        total.events += one.events
        total.tokens += one.tokens
    return total


def reset_for_reprocessing(transcript: Transcript) -> None:
    """Przygotowuje rozmowę do ponownej analizy — bez kasowania surowego tekstu.

    Wydarzenia wygenerowane poprzednio kasujemy tylko te niepotwierdzone;
    potwierdzone przez użytkownika zostają, bo są już jego decyzją, nie modelu.
    """
    for event in list(transcript.events):
        if event.source == EventSource.AI and not event.confirmed:
            db.session.delete(event)

    transcript.ai_summary = None
    transcript.ai_sentiment = None
    transcript.ai_outcome = None
    transcript.ai_raw = None
    transcript.tokens_used = None
    transcript.error = None
    transcript.attempts = 0
    transcript.processed_at = None
    transcript.next_attempt_at = None
    transcript.status = _resting_status(transcript)


def tokens_used_this_month() -> int:
    """Suma tokenów w bieżącym miesiącu — do pokazania w ustawieniach (etap 8)."""
    start = (
        _now()
        .astimezone(WARSAW)
        .replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    )
    total = db.session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(Transcript.tokens_used), 0)).where(
            Transcript.processed_at >= start.astimezone(dt.UTC)
        )
    )
    return int(total or 0)


__all__ = [
    "MAX_ATTEMPTS",
    "Report",
    "apply_result",
    "claim",
    "create_events",
    "process",
    "record_failure",
    "release_stuck",
    "reset_for_reprocessing",
    "run_pending",
    "today_local",
    "tokens_used_this_month",
]
