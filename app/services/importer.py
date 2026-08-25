"""Import arkusza z bazą kontrahentów.

Wejście to eksport z systemu księgowego — plik ``.ods`` albo ``.xlsx``, ok. 2000
wierszy, dane od trzeciego wiersza (pierwszy to tytuł, drugi to nagłówki).

Trzy rzeczy, które ten moduł traktuje poważniej, niż wyglądają:

1. **Kolumny mapujemy po tekście nagłówka, nigdy po pozycji.** W pliku
   produkcyjnym pierwsza kolumna nie ma nagłówka i jest przesunięta o jeden
   wiersz względem kolumny ``Telefon`` — mapowanie pozycyjne przypisałoby
   klientom cudze numery.
2. **Nic nie jest kasowane.** Import aktualizuje albo dodaje, nigdy nie usuwa.
3. **Automatycznie scalamy wyłącznie po akronimie.** NIP i telefon w tym pliku
   potrafią się powtarzać u odrębnych gospodarstw (34 wspólne NIP-y, 58 wspólnych
   numerów), więc trafienie po nich tylko oznacza rekord do przejrzenia.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import sqlalchemy as sa
from rapidfuzz import fuzz

from app.extensions import db
from app.models import (
    SYSTEM_TAGS,
    TAG_NEEDS_REVIEW,
    TAG_POSSIBLE_DUPLICATE,
    Activity,
    ActivityActor,
    ActivityType,
    Client,
    ClientSource,
    ImportJob,
    ImportStatus,
    Phone,
    Tag,
)
from app.services.normalize import (
    PhoneCandidate,
    normalize_acronym,
    normalize_city,
    normalize_email,
    normalize_name,
    normalize_nip,
    normalize_phone_cell,
    normalize_postal,
    normalize_street,
)

# Nagłówki, których szukamy. Klucz to postać po uproszczeniu (małe litery,
# bez ogonków, bez kropek i spacji), wartość to nazwa pola w modelu.
HEADER_MAP = {
    "akronim": "acronym",
    "miasto": "city",
    "nip": "nip",
    "kodp": "postal_code",
    "kodpocztowy": "postal_code",
    "ulica": "street",
    "telefon": "phone",
    "nazwa": "name",
    "email": "email",
    "emaii": "email",
}

# Kolumny obecne w pliku, ale bezużyteczne: „Prefiks" to kod kraju NIP-u,
# „Opiekun" jest pusty we wszystkich 1924 wierszach.
IGNORED_HEADERS = {"prefiks", "opiekun"}

REQUIRED_FIELDS = {"acronym", "name"}

PREVIEW_ROWS = 20


def _simplify(text: Any) -> str:
    """Nagłówek → postać porównywalna: 'Kod p.' → 'kodp'."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    normalized = unicodedata.normalize("NFKD", str(text).strip().lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return "".join(ch for ch in normalized if ch.isalnum())


# ---------------------------------------------------------------------------
# Odczyt arkusza
# ---------------------------------------------------------------------------


@dataclass
class Sheet:
    """Arkusz po rozpoznaniu nagłówków."""

    columns: dict[str, int]  # nazwa pola → indeks kolumny
    rows: list[list[str | None]]
    header_row: int
    unmapped: list[str]


class ImportError_(Exception):
    """Błąd, który uniemożliwia import — pokazywany użytkownikowi po polsku."""


def read_sheet(path: str | Path) -> Sheet:
    """Wczytuje plik i mapuje kolumny po nagłówkach."""
    path = Path(path)
    suffix = path.suffix.lower()

    # Adnotacja Literal jest konieczna: read_excel ma przeciążenia, a zwykły str
    # nie pasuje do żadnego z nich.
    engine: Literal["odf", "openpyxl"]
    if suffix == ".ods":
        engine = "odf"
    elif suffix in {".xlsx", ".xlsm"}:
        engine = "openpyxl"
    else:
        raise ImportError_(
            f"Nieobsługiwany format pliku: {suffix or 'brak rozszerzenia'}. "
            "Wgraj plik .ods albo .xlsx."
        )

    try:
        # dtype=str jest obowiązkowe: bez tego akronim "0156" zamieni się w liczbę 156,
        # a numer telefonu w liczbę zmiennoprzecinkową.
        frame = pd.read_excel(path, sheet_name=0, header=None, dtype=str, engine=engine)
    except Exception as exc:
        raise ImportError_(f"Nie udało się otworzyć pliku: {exc}") from exc

    if frame.empty:
        raise ImportError_("Arkusz jest pusty.")

    header_row, columns, unmapped = _find_headers(frame)

    missing = REQUIRED_FIELDS - set(columns)
    if missing:
        names = ", ".join(sorted(missing))
        raise ImportError_(
            f"W arkuszu brakuje wymaganych kolumn: {names}. "
            f"Nagłówki znalezione w wierszu {header_row + 1}: "
            f"{', '.join(unmapped) or 'brak'}."
        )

    rows: list[list[str | None]] = []
    for _, series in frame.iloc[header_row + 1 :].iterrows():
        rows.append([_cell(v) for v in series.tolist()])

    return Sheet(columns=columns, rows=rows, header_row=header_row, unmapped=unmapped)


def _find_headers(frame: pd.DataFrame) -> tuple[int, dict[str, int], list[str]]:
    """Szuka wiersza nagłówków.

    Specyfikacja mówi, że to wiersz drugi, ale zamiast wierzyć na słowo
    sprawdzamy kilka pierwszych — plik potrafi przyjść z dodatkowym wierszem
    tytułowym albo bez niego.
    """
    best_row = -1
    best: dict[str, int] = {}
    best_labels: list[str] = []

    for row_index in range(min(6, len(frame))):
        found: dict[str, int] = {}
        labels: list[str] = []
        for col_index, value in enumerate(frame.iloc[row_index].tolist()):
            key = _simplify(value)
            if not key:
                continue  # kolumna bez nagłówka — pomijamy świadomie
            labels.append(str(value).strip())
            if key in IGNORED_HEADERS:
                continue
            field_name = HEADER_MAP.get(key)
            if field_name and field_name not in found:
                found[field_name] = col_index
        if len(found) > len(best):
            best_row, best, best_labels = row_index, found, labels

    if best_row < 0:
        raise ImportError_(
            "Nie znaleziono wiersza z nagłówkami. Oczekiwane kolumny: "
            "Akronim, Miasto, Nip, Kod p., Ulica, Telefon, Nazwa, E-mail."
        )
    return best_row, best, best_labels


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


# ---------------------------------------------------------------------------
# Normalizacja wiersza
# ---------------------------------------------------------------------------


@dataclass
class ParsedRow:
    """Jeden wiersz arkusza po normalizacji."""

    number: int  # numer wiersza w pliku, liczony od 1 — do komunikatów
    raw: dict[str, str | None] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    phones: list[PhoneCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    nip_valid: bool = False
    empty: bool = False

    @property
    def valid_phones(self) -> list[PhoneCandidate]:
        return [p for p in self.phones if p.is_valid]

    @property
    def needs_review(self) -> bool:
        return bool(self.warnings)


def parse_row(row: list[str | None], columns: dict[str, int], number: int) -> ParsedRow:
    """Surowy wiersz → wartości gotowe do zapisu."""

    def raw_of(field_name: str) -> str | None:
        index = columns.get(field_name)
        if index is None or index >= len(row):
            return None
        return row[index]

    parsed = ParsedRow(number=number)
    parsed.raw = {name: raw_of(name) for name in columns}

    if not any(v for v in parsed.raw.values()):
        parsed.empty = True
        return parsed

    acronym = normalize_acronym(raw_of("acronym"))
    name = normalize_name(raw_of("name"))
    city = normalize_city(raw_of("city"))
    postal = normalize_postal(raw_of("postal_code"))
    street = normalize_street(raw_of("street"))
    email = normalize_email(raw_of("email"))
    nip = normalize_nip(raw_of("nip"))

    parsed.values = {
        "acronym": acronym.value,
        "name": name.value,
        "city": city.value,
        "postal_code": postal.value,
        "street": street.value,
        "email": email.value,
        "nip": nip.value,
    }
    parsed.nip_valid = nip.valid and nip.value is not None

    parsed.phones = normalize_phone_cell(raw_of("phone"))

    for result in (acronym, name, city, postal, street, email, nip):
        parsed.warnings.extend(result.warnings)
    for phone in parsed.phones:
        if phone.warning:
            parsed.warnings.append(f"telefon {phone.raw!r}: {phone.warning}")

    if not parsed.values["acronym"] and not parsed.values["name"]:
        parsed.empty = True

    return parsed


def parse_sheet(sheet: Sheet) -> list[ParsedRow]:
    start = sheet.header_row + 2  # numer wiersza w pliku, licząc od 1
    return [
        parse_row(row, sheet.columns, start + offset)
        for offset, row in enumerate(sheet.rows)
    ]


# ---------------------------------------------------------------------------
# Podgląd przed zapisem
# ---------------------------------------------------------------------------


@dataclass
class Preview:
    """To, co widzi użytkownik przed potwierdzeniem importu."""

    rows: list[ParsedRow]
    total: int
    empty_rows: int
    bad_phones: int
    rows_without_phone: int
    bad_nips: int
    bad_postals: int
    bad_emails: int
    needs_review: int
    duplicate_acronyms: list[str]
    possible_duplicates: int
    existing_acronyms: int
    columns: list[str]
    unmapped: list[str]


def build_preview(path: str | Path) -> Preview:
    """Analizuje CAŁY plik, ale do podglądu zwraca pierwsze 20 wierszy."""
    sheet = read_sheet(path)
    parsed = parse_sheet(sheet)

    non_empty = [row for row in parsed if not row.empty]

    bad_phones = sum(1 for row in non_empty for phone in row.phones if not phone.is_valid)
    rows_without_phone = sum(1 for row in non_empty if not row.valid_phones)
    bad_nips = sum(1 for row in non_empty if row.raw.get("nip") and not row.nip_valid)
    bad_postals = sum(
        1
        for row in non_empty
        if row.raw.get("postal_code") and not row.values.get("postal_code")
    )
    bad_emails = sum(
        1 for row in non_empty if row.raw.get("email") and not row.values.get("email")
    )

    seen: dict[str, int] = {}
    for row in non_empty:
        acronym = row.values.get("acronym")
        if acronym:
            seen[acronym] = seen.get(acronym, 0) + 1
    duplicate_acronyms = sorted(a for a, count in seen.items() if count > 1)

    acronyms = [a for a in seen if a]
    existing = 0
    if acronyms:
        existing = (
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(Client)
                .where(Client.acronym.in_(acronyms))
            )
            or 0
        )

    possible = _count_possible_duplicates(non_empty)

    return Preview(
        rows=parsed[:PREVIEW_ROWS],
        total=len(non_empty),
        empty_rows=sum(1 for row in parsed if row.empty),
        bad_phones=bad_phones,
        rows_without_phone=rows_without_phone,
        bad_nips=bad_nips,
        bad_postals=bad_postals,
        bad_emails=bad_emails,
        needs_review=sum(1 for row in non_empty if row.needs_review),
        duplicate_acronyms=duplicate_acronyms,
        possible_duplicates=possible,
        existing_acronyms=existing,
        columns=sorted(sheet.columns),
        unmapped=sheet.unmapped,
    )


def _count_possible_duplicates(rows: list[ParsedRow]) -> int:
    """Ilu klientów trafi do ręcznego przejrzenia jako możliwe duplikaty.

    Liczy zarówno kolizje wewnątrz pliku, jak i trafienia w istniejącą bazę —
    po NIP-ie i po numerze telefonu.
    """
    # Walrus zawęża typ: bez niego element listy pozostaje `Any | None`,
    # mimo że warunek odsiewa puste wartości.
    nips: list[str] = [nip for r in rows if r.nip_valid and (nip := r.values.get("nip"))]
    phones = [p.e164 for r in rows for p in r.valid_phones if p.e164]

    counted = 0
    seen_nips: dict[str, int] = {}
    for nip in nips:
        seen_nips[nip] = seen_nips.get(nip, 0) + 1
    counted += sum(count for count in seen_nips.values() if count > 1)

    seen_phones: dict[str, int] = {}
    for phone in phones:
        seen_phones[phone] = seen_phones.get(phone, 0) + 1
    counted += sum(count for count in seen_phones.values() if count > 1)

    return counted


# ---------------------------------------------------------------------------
# Zapis
# ---------------------------------------------------------------------------

FIELDS_TO_COMPARE = ("name", "city", "postal_code", "street", "email", "nip")

# Próg podobieństwa nazw. Wysoki celowo — wynik służy tylko do OZNACZENIA
# rekordu, nigdy do automatycznego scalenia.
NAME_SIMILARITY_THRESHOLD = 92


def _get_or_create_tag(name: str) -> Tag:
    tag = db.session.scalar(sa.select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name, color=SYSTEM_TAGS.get(name))
        db.session.add(tag)
        db.session.flush()
    return tag


def run_import(job_id: int, progress_every: int = 25) -> dict[str, Any]:
    """Wykonuje import. Uruchamiane z APSchedulera, nie z żądania HTTP."""
    job = db.session.get(ImportJob, job_id)
    if job is None:
        raise ImportError_(f"Nie znaleziono zadania importu {job_id}.")

    job.status = ImportStatus.RUNNING
    db.session.commit()

    try:
        sheet = read_sheet(job.stored_path)
        parsed = [row for row in parse_sheet(sheet) if not row.empty]
        job.total = len(parsed)
        db.session.commit()

        stats = _apply_rows(job, parsed, progress_every)

        job.status = ImportStatus.DONE
        job.finished_at = datetime.now(UTC)
        job.report = stats
        db.session.commit()
        return stats

    except Exception as exc:
        db.session.rollback()
        job = db.session.get(ImportJob, job_id)
        if job is not None:
            job.status = ImportStatus.FAILED
            job.error = str(exc)
            job.finished_at = datetime.now(UTC)
            db.session.commit()
        raise


def _apply_rows(
    job: ImportJob, rows: list[ParsedRow], progress_every: int
) -> dict[str, Any]:
    created = updated = skipped = flagged = 0
    problems: list[dict[str, Any]] = []

    tag_review = _get_or_create_tag(TAG_NEEDS_REVIEW)
    tag_duplicate = _get_or_create_tag(TAG_POSSIBLE_DUPLICATE)

    for index, row in enumerate(rows, start=1):
        if not row.values.get("name"):
            skipped += 1
            problems.append(
                {"row": row.number, "reason": "brak nazwy klienta", "action": "pominięty"}
            )
            continue

        client = None
        acronym = row.values.get("acronym")
        if acronym:
            client = db.session.scalar(sa.select(Client).where(Client.acronym == acronym))

        if client is not None:
            if _update_client(client, row):
                updated += 1
            else:
                skipped += 1
        else:
            client = _create_client(row)
            created += 1
            duplicate_of = _find_possible_duplicate(client, row)
            if duplicate_of is not None:
                if tag_duplicate not in client.tags:
                    client.tags.append(tag_duplicate)
                problems.append(
                    {
                        "row": row.number,
                        "reason": f"możliwy duplikat klienta #{duplicate_of.id} "
                        f"({duplicate_of.name})",
                        "action": "dodany z tagiem do przejrzenia",
                    }
                )

        if row.needs_review:
            flagged += 1
            if tag_review not in client.tags:
                client.tags.append(tag_review)
            for warning in row.warnings[:3]:
                problems.append(
                    {"row": row.number, "reason": warning, "action": "oznaczony"}
                )

        if index % progress_every == 0:
            job.processed = index
            job.created = created
            job.updated = updated
            job.skipped = skipped
            job.flagged = flagged
            db.session.commit()

    job.processed = len(rows)
    job.created = created
    job.updated = updated
    job.skipped = skipped
    job.flagged = flagged
    db.session.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "flagged": flagged,
        "total": len(rows),
        # Lista bywa długa przy brudnym pliku — do raportu bierzemy początek.
        "problems": problems[:200],
        "problems_total": len(problems),
    }


def _create_client(row: ParsedRow) -> Client:
    client = Client(
        acronym=row.values.get("acronym"),
        name=row.values["name"],
        nip=row.values.get("nip"),
        nip_valid=row.nip_valid,
        city=row.values.get("city"),
        postal_code=row.values.get("postal_code"),
        street=row.values.get("street"),
        email=row.values.get("email"),
        source=ClientSource.IMPORT,
    )
    db.session.add(client)
    db.session.flush()

    for position, candidate in enumerate(row.phones):
        db.session.add(
            Phone(
                client_id=client.id,
                e164=candidate.e164,
                raw=candidate.raw,
                label=candidate.label,
                is_primary=(position == 0),
            )
        )

    db.session.add(
        Activity(
            client_id=client.id,
            type=ActivityType.CLIENT_CREATED,
            title="Klient dodany z importu",
            description=f"Wiersz {row.number} arkusza.",
            actor=ActivityActor.SYSTEM,
            meta={"row": row.number, "source": "import"},
        )
    )
    return client


def _update_client(client: Client, row: ParsedRow) -> bool:
    """Aktualizuje istniejącego klienta. Zwraca True, jeśli coś się zmieniło.

    Pustych wartości z arkusza nie wpisujemy — brak danych w eksporcie nie jest
    informacją, że dane zniknęły.
    """
    changes: dict[str, dict[str, Any]] = {}

    for field_name in FIELDS_TO_COMPARE:
        new_value = row.values.get(field_name)
        if new_value in (None, ""):
            continue
        old_value = getattr(client, field_name)
        if old_value != new_value:
            changes[field_name] = {"from": old_value, "to": new_value}
            setattr(client, field_name, new_value)

    if "nip" in changes:
        client.nip_valid = row.nip_valid

    added_phones = _merge_phones(client, row.phones)
    if added_phones:
        changes["phones"] = {"added": added_phones}

    if not changes:
        return False

    client.updated_at = datetime.now(UTC)
    db.session.add(
        Activity(
            client_id=client.id,
            type=ActivityType.CLIENT_UPDATED,
            title="Dane zaktualizowane importem",
            description=", ".join(sorted(changes)),
            actor=ActivityActor.SYSTEM,
            meta={"row": row.number, "changes": changes},
        )
    )
    return True


def _merge_phones(client: Client, candidates: list[PhoneCandidate]) -> list[str]:
    """Dokłada numery, których klient jeszcze nie ma. Żadnego nie usuwa."""
    existing_e164 = {p.e164 for p in client.phones if p.e164}
    existing_raw = {p.raw for p in client.phones if p.raw}
    added: list[str] = []

    for candidate in candidates:
        if candidate.e164 and candidate.e164 in existing_e164:
            continue
        if not candidate.e164 and candidate.raw in existing_raw:
            continue
        db.session.add(
            Phone(
                client_id=client.id,
                e164=candidate.e164,
                raw=candidate.raw,
                label=candidate.label,
                is_primary=not client.phones and not added,
            )
        )
        added.append(candidate.e164 or candidate.raw)
        if candidate.e164:
            existing_e164.add(candidate.e164)

    return added


def _find_possible_duplicate(client: Client, row: ParsedRow) -> Client | None:
    """Szuka podejrzanie podobnego klienta — do OZNACZENIA, nie do scalenia.

    Kolejność: NIP → numer telefonu → podobieństwo nazwy w tym samym mieście.
    """
    if row.nip_valid and client.nip:
        match = db.session.scalar(
            sa.select(Client)
            .where(Client.nip == client.nip, Client.id != client.id)
            .limit(1)
        )
        if match is not None:
            return match

    e164_list = [p.e164 for p in row.valid_phones if p.e164]
    if e164_list:
        match = db.session.scalar(
            sa.select(Client)
            .join(Phone, Phone.client_id == Client.id)
            .where(Phone.e164.in_(e164_list), Client.id != client.id)
            .limit(1)
        )
        if match is not None:
            return match

    if client.city:
        candidates = db.session.scalars(
            sa.select(Client)
            .where(Client.city == client.city, Client.id != client.id)
            .limit(200)
        ).all()
        for other in candidates:
            if fuzz.ratio(client.name.lower(), other.name.lower()) >= (
                NAME_SIMILARITY_THRESHOLD
            ):
                return other

    return None
