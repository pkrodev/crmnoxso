"""Wyszukiwanie, filtrowanie i edycja klientów.

Logika zapytań mieszka tutaj, a nie w widoku, z dwóch powodów: da się ją
przetestować bez klienta HTTP, a lista klientów i przyszły kreator kampanii
(etap 7) muszą filtrować odbiorców dokładnie tak samo.

Rzecz najważniejsza w tym module: **wyszukiwanie po numerze telefonu musi
działać niezależnie od tego, jak użytkownik go wpisze**. W bazie numery są
w E.164 (``+48601092947``), a w głowie użytkownika bywają jako ``601092947``,
``601-092-947`` albo ``601 092 947``. Zapytanie normalizujemy przed pójściem
do bazy, a dodatkowo porównujemy same cyfry kolumny ``Phone.raw`` — dzięki temu
znajdują się też numery, których nie dało się sparsować i które mają
``e164 = NULL``.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    Activity,
    ActivityActor,
    ActivityType,
    Client,
    ClientStatus,
    Note,
    Phone,
    Tag,
)
from app.services.normalize import (
    normalize_acronym,
    normalize_city,
    normalize_email,
    normalize_name,
    normalize_nip,
    normalize_phone,
    normalize_postal,
    normalize_street,
    phone_search_variants,
)

PAGE_SIZE = 50

# Minimalna liczba cyfr, od której traktujemy wpisany ciąg jako fragment
# numeru albo NIP-u. Poniżej tego progu zbyt wiele rekordów pasuje do wszystkiego.
MIN_DIGITS = 4


# ---------------------------------------------------------------------------
# Filtry
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ClientFilters:
    """Stan wyszukiwarki i filtrów, wprost z parametrów zapytania."""

    query: str = ""
    city: str = ""
    tag: str = ""
    status: str = ""
    has_email: bool = False
    has_phone: bool = False
    page: int = 1

    @classmethod
    def from_request(cls, args) -> ClientFilters:
        try:
            page = max(1, int(args.get("strona", 1)))
        except (TypeError, ValueError):
            page = 1
        return cls(
            query=(args.get("q") or "").strip(),
            city=(args.get("miasto") or "").strip(),
            tag=(args.get("tag") or "").strip(),
            status=(args.get("status") or "").strip(),
            has_email=args.get("ma_email") in {"1", "true", "on"},
            has_phone=args.get("ma_telefon") in {"1", "true", "on"},
            page=page,
        )

    @property
    def active(self) -> bool:
        """Czy cokolwiek zawęża listę — do pokazania przycisku „wyczyść"."""
        return bool(
            self.query
            or self.city
            or self.tag
            or self.status
            or self.has_email
            or self.has_phone
        )

    def as_params(self) -> dict[str, str]:
        """Filtry jako parametry URL — bez pustych, żeby adres był czytelny."""
        params: dict[str, str] = {}
        if self.query:
            params["q"] = self.query
        if self.city:
            params["miasto"] = self.city
        if self.tag:
            params["tag"] = self.tag
        if self.status:
            params["status"] = self.status
        if self.has_email:
            params["ma_email"] = "1"
        if self.has_phone:
            params["ma_telefon"] = "1"
        return params


@dataclass(slots=True)
class Page:
    rows: list[tuple[Client, datetime | None]] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = PAGE_SIZE

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def first_index(self) -> int:
        return 0 if not self.total else (self.page - 1) * self.page_size + 1

    @property
    def last_index(self) -> int:
        return min(self.page * self.page_size, self.total)


# ---------------------------------------------------------------------------
# Budowanie zapytania
# ---------------------------------------------------------------------------


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _phone_digits_column():
    """Cyfry z ``Phone.raw`` — pozwala trafić także w numery nieparsowalne.

    ``regexp_replace`` jest specyficzne dla PostgreSQL, ale to jedyna baza,
    na której ta aplikacja działa (i w developmencie, i na Railwayu).
    """
    return sa.func.regexp_replace(sa.func.coalesce(Phone.raw, ""), r"\D", "", "g")


def search_clause(term: str):
    """Warunek wyszukiwania po nazwie, akronimie, mieście, NIP-ie i telefonie."""
    term = (term or "").strip()
    if not term:
        return None

    like = f"%{term}%"
    clauses: list[Any] = [
        Client.name.ilike(like),
        Client.city.ilike(like),
        Client.acronym.ilike(like),
        Client.email.ilike(like),
    ]

    digits = _digits(term)
    if len(digits) >= MIN_DIGITS:
        clauses.append(Client.nip.like(f"%{digits}%"))

        # Numer telefonu: najpierw warianty znormalizowane (trafiają w e164),
        # potem porównanie samych cyfr oryginału (trafia w e164 = NULL).
        variants = [v for v in phone_search_variants(term) if v.startswith("+")]
        phone_conditions: list[Any] = [_phone_digits_column().like(f"%{digits}%")]
        if variants:
            phone_conditions.append(Phone.e164.in_(variants))

        clauses.append(
            Client.id.in_(sa.select(Phone.client_id).where(sa.or_(*phone_conditions)))
        )

    return sa.or_(*clauses)


def _last_contact_subquery():
    """Data ostatniego zdarzenia na osi czasu klienta."""
    return (
        sa.select(sa.func.max(Activity.occurred_at))
        .where(Activity.client_id == Client.id)
        .correlate(Client)
        .scalar_subquery()
    )


def build_query(filters: ClientFilters):
    """Zapytanie z nałożonymi filtrami, jeszcze bez sortowania i stronicowania."""
    last_contact = _last_contact_subquery()
    stmt = sa.select(Client, last_contact.label("last_contact"))

    term = search_clause(filters.query)
    if term is not None:
        stmt = stmt.where(term)

    if filters.city:
        stmt = stmt.where(Client.city == filters.city)

    if filters.tag:
        stmt = stmt.where(Client.tags.any(Tag.name == filters.tag))

    if filters.status:
        # Nieznany status w adresie (np. ręcznie podrobiony parametr) pomijamy,
        # zamiast wywracać widok błędem 500.
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Client.status == ClientStatus(filters.status))

    if filters.has_email:
        stmt = stmt.where(Client.email.is_not(None))

    if filters.has_phone:
        stmt = stmt.where(Client.phones.any(Phone.e164.is_not(None)))

    return stmt


def list_clients(filters: ClientFilters) -> Page:
    """Strona wyników — klienci wraz z datą ostatniego kontaktu."""
    stmt = build_query(filters)

    total = db.session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )

    rows = db.session.execute(
        stmt.options(selectinload(Client.phones), selectinload(Client.tags))
        .order_by(Client.name, Client.id)
        .limit(PAGE_SIZE)
        .offset((filters.page - 1) * PAGE_SIZE)
    ).all()

    return Page(
        rows=[(row[0], row[1]) for row in rows],
        total=total or 0,
        page=filters.page,
    )


def city_options() -> list[str]:
    """Miasta występujące w bazie — do listy rozwijanej filtru."""
    rows = db.session.scalars(
        sa.select(Client.city)
        .where(Client.city.is_not(None))
        .distinct()
        .order_by(Client.city)
    ).all()
    # Warunek WHERE odsiewa NULL-e, ale typ kolumny pozostaje `str | None`.
    return [city for city in rows if city is not None]


def tag_options() -> list[Tag]:
    return list(db.session.scalars(sa.select(Tag).order_by(Tag.name)).all())


def selected_clients(ids: list[int]) -> list[Client]:
    if not ids:
        return []
    return list(db.session.scalars(sa.select(Client).where(Client.id.in_(ids))).all())


# ---------------------------------------------------------------------------
# Oś czasu
# ---------------------------------------------------------------------------


def log_activity(
    client: Client,
    type_: ActivityType,
    title: str,
    *,
    description: str | None = None,
    meta: dict[str, Any] | None = None,
    actor: ActivityActor = ActivityActor.USER,
) -> Activity:
    """Dopisuje wpis na oś czasu klienta.

    Oś czasu to wymóg funkcjonalny — użytkownik ma widzieć historię kontaktu
    w jednym miejscu — więc zapisujemy tu też zwykłe zmiany pól.
    """
    activity = Activity(
        client_id=client.id,
        type=type_,
        title=title,
        description=description,
        meta=meta,
        actor=actor,
        occurred_at=datetime.now(UTC),
    )
    db.session.add(activity)
    return activity


def timeline(client_id: int, limit: int = 100) -> list[Activity]:
    return list(
        db.session.scalars(
            sa.select(Activity)
            .where(Activity.client_id == client_id)
            .order_by(Activity.occurred_at.desc(), Activity.id.desc())
            .limit(limit)
        ).all()
    )


def pinned_notes(client_id: int) -> list[Note]:
    return list(
        db.session.scalars(
            sa.select(Note)
            .where(Note.client_id == client_id, Note.pinned.is_(True))
            .order_by(Note.created_at.desc())
        ).all()
    )


# ---------------------------------------------------------------------------
# Edycja pojedynczego pola
# ---------------------------------------------------------------------------

# Pola edytowalne w panelu klienta wraz z etykietą po polsku i normalizatorem.
# Normalizujemy tak samo jak przy imporcie — inaczej ręcznie wpisane „WARSZAWA"
# rozjechałoby się z zaimportowanym „Warszawa" i zrobiło dwa miasta w filtrze.
EDITABLE_FIELDS: dict[str, tuple[str, Any]] = {
    "name": ("Nazwa", normalize_name),
    "acronym": ("Akronim", normalize_acronym),
    "nip": ("NIP", normalize_nip),
    "city": ("Miasto", normalize_city),
    "postal_code": ("Kod pocztowy", normalize_postal),
    "street": ("Ulica", normalize_street),
    "email": ("E-mail", normalize_email),
}


@dataclass(slots=True)
class FieldUpdate:
    ok: bool
    value: str | None = None
    warning: str | None = None
    error: str | None = None


def update_field(client: Client, name: str, raw: str) -> FieldUpdate:
    """Zapisuje jedno pole klienta, z normalizacją i wpisem na oś czasu.

    Zwraca wynik zamiast rzucać wyjątkiem — widok renderuje z niego fragment
    HTML dla HTMX, razem z ewentualnym ostrzeżeniem (np. NIP bez sumy kontrolnej).
    """
    if name not in EDITABLE_FIELDS:
        return FieldUpdate(ok=False, error="Nieznane pole.")

    label, normalizer = EDITABLE_FIELDS[name]
    result = normalizer(raw)
    warning = "; ".join(result.warnings) or None

    if name == "name" and not result.value:
        return FieldUpdate(ok=False, error="Nazwa nie może być pusta.")

    # E-mail i kod pocztowy w złym formacie normalizator zwraca jako `None`.
    # Przy imporcie to właściwe (rekord wchodzi, pole zostaje puste), ale przy
    # ręcznej edycji wyczyściłoby pole zamiast zgłosić błąd — użytkownik
    # zobaczyłby, że jego wpis zniknął bez słowa wyjaśnienia.
    if raw.strip() and result.value is None and not result.valid:
        return FieldUpdate(ok=False, error=warning or f"{label}: niepoprawna wartość.")

    if name == "acronym" and result.value:
        clash = db.session.scalar(
            sa.select(Client).where(
                Client.acronym == result.value, Client.id != client.id
            )
        )
        if clash is not None:
            return FieldUpdate(
                ok=False,
                error=f"Akronim {result.value} należy już do klienta „{clash.name}”.",
            )

    previous = getattr(client, name)
    if previous == result.value:
        return FieldUpdate(ok=True, value=result.value, warning=warning)

    setattr(client, name, result.value)

    # NIP trzymamy razem z wynikiem walidacji sumą kontrolną — czerwona ikona
    # w panelu bierze się właśnie z tej flagi.
    if name == "nip":
        client.nip_valid = bool(result.value) and result.valid

    log_activity(
        client,
        ActivityType.CLIENT_UPDATED,
        f"Zmiana pola: {label}",
        description=f"{previous or '—'} → {result.value or '—'}",
        meta={"field": name, "from": previous, "to": result.value},
    )
    return FieldUpdate(ok=True, value=result.value, warning=warning)


# ---------------------------------------------------------------------------
# Telefony
# ---------------------------------------------------------------------------


def add_phone(client: Client, raw: str, label: str | None = None) -> FieldUpdate:
    """Dokłada numer klientowi. Nieparsowalny też zapisujemy — w ``raw``."""
    raw = (raw or "").strip()
    if not raw:
        return FieldUpdate(ok=False, error="Wpisz numer.")

    candidate = normalize_phone(raw)

    if candidate.e164 and any(p.e164 == candidate.e164 for p in client.phones):
        return FieldUpdate(ok=False, error="Ten numer jest już przypisany.")

    # Dokładamy przez relację, nie przez `client_id` — inaczej kolekcja
    # `client.phones` wczytana wcześniej nie zobaczyłaby nowego numeru
    # i pierwszy numer klienta nie dostałby flagi „główny".
    phone = Phone(
        e164=candidate.e164,
        raw=raw,
        label=label or candidate.label,
        is_primary=not client.phones,
    )
    client.phones.append(phone)

    log_activity(
        client,
        ActivityType.CLIENT_UPDATED,
        "Dodano numer telefonu",
        description=candidate.e164 or raw,
        meta={"field": "phone", "to": candidate.e164 or raw},
    )
    return FieldUpdate(
        ok=True,
        value=candidate.e164 or raw,
        warning=None if candidate.e164 else "Numeru nie udało się rozpoznać.",
    )


def set_primary_phone(client: Client, phone_id: int) -> bool:
    target = next((p for p in client.phones if p.id == phone_id), None)
    if target is None:
        return False
    for phone in client.phones:
        phone.is_primary = phone.id == phone_id
    log_activity(
        client,
        ActivityType.CLIENT_UPDATED,
        "Zmiana numeru głównego",
        description=target.e164 or target.raw,
        meta={"field": "primary_phone", "to": target.e164 or target.raw},
    )
    return True


def remove_phone(client: Client, phone_id: int) -> bool:
    target = next((p for p in client.phones if p.id == phone_id), None)
    if target is None:
        return False
    was_primary = target.is_primary
    label = target.e164 or target.raw or ""
    client.phones.remove(target)
    db.session.flush()

    # Klient bez numeru głównego nie może zostać — pierwszy z listy przejmuje rolę.
    if was_primary and client.phones:
        client.phones[0].is_primary = True

    log_activity(
        client,
        ActivityType.CLIENT_UPDATED,
        "Usunięto numer telefonu",
        description=label,
        meta={"field": "phone", "from": label},
    )
    return True


# ---------------------------------------------------------------------------
# Tagi
# ---------------------------------------------------------------------------


def add_tag(client: Client, name: str) -> FieldUpdate:
    name = (name or "").strip().lower()
    if not name:
        return FieldUpdate(ok=False, error="Wpisz nazwę tagu.")
    if len(name) > 64:
        return FieldUpdate(ok=False, error="Nazwa tagu jest za długa.")

    if client.has_tag(name):
        return FieldUpdate(ok=True, value=name)

    tag = db.session.scalar(sa.select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name)
        db.session.add(tag)
        db.session.flush()

    client.tags.append(tag)
    log_activity(client, ActivityType.TAG_ADDED, f"Dodano tag: {name}")
    return FieldUpdate(ok=True, value=name)


def remove_tag(client: Client, tag_id: int) -> bool:
    tag = next((t for t in client.tags if t.id == tag_id), None)
    if tag is None:
        return False
    client.tags.remove(tag)
    log_activity(client, ActivityType.TAG_REMOVED, f"Usunięto tag: {tag.name}")
    return True


# ---------------------------------------------------------------------------
# Notatki i zdarzenia ręczne
# ---------------------------------------------------------------------------


def add_note(client: Client, body: str, pinned: bool = False) -> FieldUpdate:
    body = (body or "").strip()
    if not body:
        return FieldUpdate(ok=False, error="Notatka jest pusta.")

    note = Note(client_id=client.id, body=body, pinned=pinned)
    db.session.add(note)
    db.session.flush()

    log_activity(
        client,
        ActivityType.NOTE_ADDED,
        "Notatka",
        description=body,
        meta={"note_id": note.id, "pinned": pinned},
    )
    return FieldUpdate(ok=True, value=body)


def add_manual_activity(client: Client, title: str, description: str) -> FieldUpdate:
    title = (title or "").strip()
    if not title:
        return FieldUpdate(ok=False, error="Opisz, co się wydarzyło.")
    log_activity(
        client,
        ActivityType.MANUAL,
        title,
        description=(description or "").strip() or None,
    )
    return FieldUpdate(ok=True, value=title)


# ---------------------------------------------------------------------------
# Status i zgoda SMS
# ---------------------------------------------------------------------------


def set_status(client: Client, status: str) -> bool:
    try:
        new_status = ClientStatus(status)
    except ValueError:
        return False
    if client.status == new_status:
        return True

    previous = client.status
    client.status = new_status
    log_activity(
        client,
        ActivityType.CLIENT_UPDATED,
        "Zmiana statusu",
        description=f"{previous.value} → {new_status.value}",
        meta={"field": "status", "from": previous.value, "to": new_status.value},
    )
    # Etap 7 podepnie tu synchronizację czarnej listy u dostawcy SMS —
    # ustawienie BLACKLIST musi wywołać blacklist/add, zdjęcie blacklist/remove.
    return True


def set_sms_consent(client: Client, consent: bool) -> None:
    if client.sms_consent == consent:
        return
    client.sms_consent = consent
    client.sms_consent_at = datetime.now(UTC) if consent else None
    log_activity(
        client,
        ActivityType.CLIENT_UPDATED,
        "Zgoda na SMS: " + ("udzielona" if consent else "wycofana"),
        meta={"field": "sms_consent", "to": consent},
    )
