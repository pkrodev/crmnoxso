"""Filtry Jinja2 — formatowanie danych do wyświetlenia."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")

MONTHS_GENITIVE = [
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
]


def to_local(value: datetime | None) -> datetime | None:
    """Z UTC na czas polski. W bazie wszystko jest w UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(WARSAW)


def datetime_pl(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    local = to_local(value)
    return local.strftime(fmt) if local else "—"


def date_pl(value: datetime | date | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        local = to_local(value)
        return local.strftime("%d.%m.%Y") if local else "—"
    return value.strftime("%d.%m.%Y")


def date_long_pl(value: datetime | date | None) -> str:
    """Np. „14 marca 2026”."""
    if value is None:
        return "—"
    d = to_local(value) if isinstance(value, datetime) else value
    if d is None:
        return "—"
    return f"{d.day} {MONTHS_GENITIVE[d.month - 1]} {d.year}"


def relative_pl(value: datetime | None) -> str:
    """Odstęp od teraz, po polsku — do osi czasu."""
    local = to_local(value)
    if local is None:
        return "—"
    now = datetime.now(WARSAW)
    delta = now - local
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return datetime_pl(value)
    if seconds < 60:
        return "przed chwilą"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min temu"
    if seconds < 86400:
        hours = seconds // 3600
        if hours == 1:
            return "godzinę temu"
        return f"{hours} godz. temu"
    days = seconds // 86400
    if days == 1:
        return "wczoraj"
    if days < 7:
        return f"{days} dni temu"
    return datetime_pl(value, "%d.%m.%Y")


def phone_pl(e164: str | None) -> str:
    """+48601092947 → 601 092 947 (polskie numery), reszta bez zmian."""
    if not e164:
        return "—"
    if e164.startswith("+48") and len(e164) == 12:
        rest = e164[3:]
        return f"{rest[0:3]} {rest[3:6]} {rest[6:9]}"
    return e164


def nip_pl(nip: str | None) -> str:
    """6171010149 → 617-101-01-49."""
    if not nip:
        return "—"
    if len(nip) == 10 and nip.isdigit():
        return f"{nip[0:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:10]}"
    return nip


def plural_pl(count: int, one: str, few: str, many: str) -> str:
    """Polska odmiana liczebnika: 1 klient, 2 klientów… 22 klientów."""
    if count == 1:
        return one
    last_two = count % 100
    last = count % 10
    if 12 <= last_two <= 14:
        return many
    if 2 <= last <= 4:
        return few
    return many


def register_filters(app) -> None:
    app.jinja_env.filters["datetime_pl"] = datetime_pl
    app.jinja_env.filters["date_pl"] = date_pl
    app.jinja_env.filters["date_long_pl"] = date_long_pl
    app.jinja_env.filters["relative_pl"] = relative_pl
    app.jinja_env.filters["phone_pl"] = phone_pl
    app.jinja_env.filters["nip_pl"] = nip_pl
    app.jinja_env.globals["plural_pl"] = plural_pl
