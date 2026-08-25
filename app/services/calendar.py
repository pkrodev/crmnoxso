"""Kalendarz — wydarzenia ręczne i te wygenerowane z rozmów (etap 6).

Rzecz, która porządkuje cały ten moduł: **w bazie wszystko jest w UTC, a widać
ma być czas polski**. FullCalendar dostaje daty z jawnym przesunięciem strefy
(``2026-09-01T14:00:00+02:00``), więc nie musi niczego zgadywać, a przejście
z czasu letniego na zimowy nie przesuwa terminów o godzinę.

Druga rzecz: wydarzenie z AI jest **propozycją**, nie faktem. Do czasu
potwierdzenia przez użytkownika ma być widoczne inaczej niż wpis zrobiony ręcznie
— stąd osobne klasy CSS w danych podawanych kalendarzowi.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.filters import WARSAW, to_local
from app.models import (
    ActivityActor,
    ActivityType,
    CalendarEvent,
    Client,
    EventSource,
)
from app.services.clients import log_activity

# Ile trwa wydarzenie z godziną, gdy nikt nie podał końca. AI nigdy go nie podaje
# — z rozmowy pada „o czternastej", nie „od czternastej do piętnastej".
DEFAULT_DURATION = dt.timedelta(hours=1)


# ---------------------------------------------------------------------------
# Odczyt
# ---------------------------------------------------------------------------


def events_in_range(start: dt.datetime, end: dt.datetime) -> list[CalendarEvent]:
    return list(
        db.session.scalars(
            sa.select(CalendarEvent)
            .where(CalendarEvent.starts_at >= start, CalendarEvent.starts_at < end)
            .order_by(CalendarEvent.starts_at)
            .options(selectinload(CalendarEvent.client))
        ).all()
    )


def upcoming(days: int = 7, limit: int = 10) -> list[CalendarEvent]:
    now = dt.datetime.now(dt.UTC)
    return list(
        db.session.scalars(
            sa.select(CalendarEvent)
            .where(
                CalendarEvent.starts_at >= now,
                CalendarEvent.starts_at < now + dt.timedelta(days=days),
            )
            .order_by(CalendarEvent.starts_at)
            .limit(limit)
            .options(selectinload(CalendarEvent.client))
        ).all()
    )


def unconfirmed_count() -> int:
    """Ile propozycji z AI czeka na decyzję — licznik w nagłówku ekranu."""
    return int(
        db.session.scalar(
            sa.select(sa.func.count())
            .select_from(CalendarEvent)
            .where(
                CalendarEvent.source == EventSource.AI,
                CalendarEvent.confirmed.is_(False),
            )
        )
        or 0
    )


def css_classes(event: CalendarEvent) -> list[str]:
    """Klasy wyglądu dla FullCalendara.

    Trzy stany, wszystkie w palecie marki (sekcja 3 specyfikacji):
    propozycja z AI, potwierdzony termin z AI, wpis zrobiony ręcznie.
    """
    if event.source != EventSource.AI:
        return ["ev-manual"]
    return ["ev-ai-confirmed"] if event.confirmed else ["ev-ai"]


def to_feed(event: CalendarEvent) -> dict:
    """Wydarzenie w formacie, którego oczekuje FullCalendar."""
    local_start = to_local(event.starts_at)
    assert local_start is not None

    if event.all_day:
        start: str = local_start.date().isoformat()
        end: str | None = None
    else:
        start = local_start.isoformat()
        local_end = to_local(event.ends_at) if event.ends_at else None
        end = (local_end or (local_start + DEFAULT_DURATION)).isoformat()

    return {
        "id": str(event.id),
        "title": event.title,
        "start": start,
        "end": end,
        "allDay": event.all_day,
        "classNames": css_classes(event),
        "extendedProps": {
            "confirmed": event.confirmed,
            "source": event.source.value,
            "confidence": event.confidence,
            "client": event.client.name if event.client else None,
        },
    }


def parse_range(start: str | None, end: str | None) -> tuple[dt.datetime, dt.datetime]:
    """Zakres z parametrów FullCalendara, z rozsądnym zapasem przy braku danych."""
    now = dt.datetime.now(dt.UTC)

    def _parse(value: str | None, fallback: dt.datetime) -> dt.datetime:
        if not value:
            return fallback
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=WARSAW)
        return parsed.astimezone(dt.UTC)

    return (
        _parse(start, now - dt.timedelta(days=90)),
        _parse(end, now + dt.timedelta(days=365)),
    )


# ---------------------------------------------------------------------------
# Zapis
# ---------------------------------------------------------------------------


def to_utc(day: dt.date, moment: dt.time | None) -> dt.datetime:
    """Data i godzina wpisane przez użytkownika (czas polski) → moment w UTC."""
    local = dt.datetime.combine(day, moment or dt.time(0, 0), tzinfo=WARSAW)
    return local.astimezone(dt.UTC)


def confirm(event: CalendarEvent) -> bool:
    """Potwierdzenie propozycji z AI. To jedyny sposób, w jaki termin z modelu
    staje się ustaleniem — sam z siebie nigdy nie jest potwierdzony."""
    if event.confirmed:
        return False

    event.confirmed = True
    if event.client is not None:
        log_activity(
            event.client,
            ActivityType.EVENT_SCHEDULED,
            f"Potwierdzono termin: {event.title}",
            description=_when(event),
            meta={"event_id": event.id, "transcript_id": event.transcript_id},
            actor=ActivityActor.USER,
        )
    return True


def update(
    event: CalendarEvent,
    *,
    title: str,
    day: dt.date,
    moment: dt.time | None,
    description: str | None = None,
    client_id: int | None = None,
) -> None:
    """Ręczna poprawka terminu.

    Poprawiony termin z AI uznajemy za potwierdzony — użytkownik właśnie się nim
    zajął i wpisał własną wartość, więc trzymanie go dalej jako „propozycji"
    byłoby udawaniem, że decyzji nie było.
    """
    event.title = title[:300]
    event.description = description or None
    event.all_day = moment is None
    event.starts_at = to_utc(day, moment)
    event.ends_at = None if moment is None else event.starts_at + DEFAULT_DURATION
    if client_id is not None:
        event.client_id = client_id
    event.confirmed = True

    if event.client is not None:
        log_activity(
            event.client,
            ActivityType.EVENT_SCHEDULED,
            f"Zmieniono termin: {event.title}",
            description=_when(event),
            meta={"event_id": event.id},
            actor=ActivityActor.USER,
        )


def create(
    *,
    title: str,
    day: dt.date,
    moment: dt.time | None,
    description: str | None = None,
    client_id: int | None = None,
) -> CalendarEvent:
    starts_at = to_utc(day, moment)
    event = CalendarEvent(
        client_id=client_id,
        title=title[:300],
        description=description or None,
        starts_at=starts_at,
        ends_at=None if moment is None else starts_at + DEFAULT_DURATION,
        all_day=moment is None,
        source=EventSource.MANUAL,
        confirmed=True,  # wpis użytkownika jest ustaleniem z definicji
    )
    db.session.add(event)
    db.session.flush()

    if event.client is not None:
        log_activity(
            event.client,
            ActivityType.EVENT_SCHEDULED,
            f"Wydarzenie: {event.title}",
            description=_when(event),
            meta={"event_id": event.id},
            actor=ActivityActor.USER,
        )
    return event


def delete(event: CalendarEvent) -> None:
    """Usunięcie terminu. Ślad na osi czasu zostaje — historia ma być prawdziwa."""
    if event.client is not None:
        log_activity(
            event.client,
            ActivityType.MANUAL,
            f"Usunięto termin: {event.title}",
            description=_when(event),
            meta={"transcript_id": event.transcript_id},
            actor=ActivityActor.USER,
        )
    db.session.delete(event)


def _when(event: CalendarEvent) -> str:
    local = to_local(event.starts_at)
    if local is None:
        return ""
    if event.all_day:
        return local.strftime("%d.%m.%Y") + ", cały dzień"
    return local.strftime("%d.%m.%Y, godz. %H:%M")


def client_options(limit: int = 500) -> list[Client]:
    """Klienci do listy wyboru przy wydarzeniu ręcznym."""
    return list(
        db.session.scalars(sa.select(Client).order_by(Client.name).limit(limit)).all()
    )


__all__ = [
    "confirm",
    "create",
    "css_classes",
    "delete",
    "events_in_range",
    "parse_range",
    "to_feed",
    "to_utc",
    "unconfirmed_count",
    "upcoming",
    "update",
]
