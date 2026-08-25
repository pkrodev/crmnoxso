"""Dopasowanie transkrypcji rozmowy do klienta (etap 4).

Numer telefonu jest jedynym pewnym kluczem, jaki mamy — nazwa firmy w rozmowie
pada rzadko i w formie, której nie da się porównać z bazą („u Kowalskich",
„ta spółdzielnia spod Jarocina"). Dlatego dopasowanie idzie wyłącznie po numerze,
w kolejności z sekcji 9 specyfikacji:

1. numer podany wprost w żądaniu (pole ``phone``),
2. numer wyłuskany z treści transkrypcji,
3. brak numeru → ``NEEDS_REVIEW`` i ręczne przypisanie z ekranu ``/transcripts``.

Osobny przypadek, który wynika wprost z danych: **jeden numer bywa wspólny dla
kilku klientów**. W bazie źródłowej 58 numerów należy do dwóch lub trzech
gospodarstw (rodzina pod jednym telefonem). Tabela ``phones`` celowo nie ma
ograniczenia UNIQUE na ``e164``, więc dopasowanie musi liczyć się z kilkoma
trafieniami — wtedy nie zgadujemy, tylko oddajemy decyzję użytkownikowi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, time

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.filters import WARSAW, phone_pl
from app.models import (
    TAG_FROM_TRANSCRIPT,
    ActivityActor,
    ActivityType,
    Client,
    ClientSource,
    Phone,
    Transcript,
    TranscriptStatus,
)
from app.services.clients import get_or_create_tag, log_activity
from app.services.normalize import normalize_phone, normalize_phone_cell

# Kandydat na numer w swobodnym tekście: ciąg cyfr rozdzielony spacjami,
# myślnikami albo nawiasami, zaczynający i kończący się cyfrą.
#
# Czego tu NIE ma i dlaczego:
#   * kropki — w zdaniu kończą wypowiedź („…pod 601 092 947. Do usłyszenia"),
#     więc doklejałyby do numeru początek następnego zdania;
#   * znaku nowej linii — numer nie łamie się między wierszami, a ``\s`` zlepiłby
#     koniec jednej linii z początkiem następnej w jeden fałszywy numer.
_PHONE_IN_TEXT = re.compile(
    r"""
    (?<![0-9A-Za-z])
    ( \+? \d [\d\ \t()\-]{7,20} \d )
    (?![0-9A-Za-z])
    """,
    re.VERBOSE,
)

# Ile numerów z jednej transkrypcji w ogóle bierzemy pod uwagę. Rozmowa potrafi
# zawierać numer działki, NIP i datę — po kilku pierwszych trafieniach szansa,
# że kolejne są numerem rozmówcy, spada do zera.
MAX_PHONES_FROM_TEXT = 5


@dataclass(slots=True)
class ExtractedPhone:
    raw: str
    e164: str


def extract_phones(text: str | None) -> list[ExtractedPhone]:
    """Numery telefonów wyłuskane z treści rozmowy, w kolejności wystąpienia.

    Każdy kandydat przechodzi przez ten sam normalizator, co import, więc daty
    (``2026-03-14``), NIP-y (``617-101-01-49``) i kwoty (``1 200 000``) odpadają
    same — nie są poprawnymi numerami polskimi.
    """
    if not text:
        return []

    found: list[ExtractedPhone] = []
    seen: set[str] = set()

    for match in _PHONE_IN_TEXT.finditer(text):
        fragment = match.group(1).strip()
        # Ten sam podział, co w komórce arkusza: dwie spacje albo przecinek
        # rozdzielają dwa numery, pojedyncza spacja jest częścią jednego.
        for candidate in normalize_phone_cell(fragment):
            if candidate.e164 and candidate.e164 not in seen:
                seen.add(candidate.e164)
                found.append(ExtractedPhone(raw=candidate.raw, e164=candidate.e164))
        if len(found) >= MAX_PHONES_FROM_TEXT:
            break

    return found[:MAX_PHONES_FROM_TEXT]


def clients_by_phone(e164: str) -> list[Client]:
    """Wszyscy klienci mający ten numer — zwykle zero albo jeden, bywa kilku."""
    return list(
        db.session.scalars(
            sa.select(Client)
            .join(Phone, Phone.client_id == Client.id)
            .where(Phone.e164 == e164)
            .distinct()
            .order_by(Client.name, Client.id)
            .options(selectinload(Client.phones), selectinload(Client.tags))
        ).all()
    )


# ---------------------------------------------------------------------------
# Wynik dopasowania
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MatchOutcome:
    """Co się stało z transkrypcją — do komunikatu w UI i do testów."""

    status: TranscriptStatus
    client: Client | None = None
    created: bool = False
    candidates: list[Client] = field(default_factory=list)
    phone_e164: str | None = None
    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.client is not None


def _occurred_at(transcript: Transcript) -> datetime:
    """Kiedy wpis ma stanąć na osi czasu klienta.

    Gdy znamy datę rozmowy, ustawiamy południe czasu polskiego — nie północ,
    bo ta po przeliczeniu na UTC wypada dnia poprzedniego i rozmowa lądowałaby
    na osi czasu o dzień za wcześnie. Bez daty zostaje chwila wgrania.
    """
    if transcript.call_date is None:
        return datetime.now(UTC)
    local = datetime.combine(transcript.call_date, time(12, 0), tzinfo=WARSAW)
    return local.astimezone(UTC)


def phone_placeholder_name(e164: str) -> str:
    """Nazwa klienta założonego z rozmowy, dopóki nie znamy prawdziwej.

    Etap 5 podmieni ją na nazwę wyciągniętą przez model, o ile w rozmowie padła.
    """
    return f"Nieznany ({phone_pl(e164)})"


def create_client_from_phone(e164: str, raw: str | None = None) -> Client:
    """Zakłada klienta dla numeru, którego nie ma w bazie.

    Specyfikacja jest tu jednoznaczna: rozmowy z nieznanego numeru nie wolno
    zgubić. Klient dostaje źródło ``TRANSCRIPT`` i tag ``nowy-z-rozmowy``,
    żeby dało się takie rekordy odfiltrować i przejrzeć.
    """
    client = Client(name=phone_placeholder_name(e164), source=ClientSource.TRANSCRIPT)
    client.phones.append(Phone(e164=e164, raw=raw or e164, is_primary=True))
    client.tags.append(get_or_create_tag(TAG_FROM_TRANSCRIPT))
    db.session.add(client)
    db.session.flush()

    log_activity(
        client,
        ActivityType.CLIENT_CREATED,
        "Klient założony z rozmowy telefonicznej",
        description=f"Numer {phone_pl(e164)} nie występował w bazie.",
        actor=ActivityActor.SYSTEM,
    )
    return client


def attach(
    transcript: Transcript,
    client: Client,
    *,
    actor: ActivityActor = ActivityActor.SYSTEM,
    note: str | None = None,
) -> None:
    """Przypina rozmowę do klienta i dopisuje wpis na jego oś czasu."""
    transcript.client_id = client.id
    if transcript.status == TranscriptStatus.NEEDS_REVIEW:
        # Rozmowa czekała na człowieka; teraz ma klienta i może iść do analizy.
        transcript.status = TranscriptStatus.PENDING

    activity = log_activity(
        client,
        ActivityType.CALL_TRANSCRIBED,
        "Rozmowa telefoniczna",
        description=note,
        meta={"transcript_id": transcript.id, "phone": transcript.phone_e164},
        actor=actor,
    )
    activity.occurred_at = _occurred_at(transcript)


def resolve(transcript: Transcript, *, create_missing: bool = True) -> MatchOutcome:
    """Dopasowuje transkrypcję do klienta i ustawia jej status.

    Nie robi ``commit`` — decyzję o zatwierdzeniu podejmuje wywołujący
    (endpoint ingest albo widok „przetwórz ponownie"), bo zapis musi objąć
    także sam rekord transkrypcji.
    """
    e164 = transcript.phone_e164
    if not e164:
        # Numer podany w żądaniu bywa w dowolnym zapisie — normalizujemy tak samo
        # jak przy imporcie.
        candidate = normalize_phone(transcript.phone_raw)
        if candidate.e164:
            e164 = candidate.e164

    if not e164:
        for extracted in extract_phones(transcript.raw_text):
            e164 = extracted.e164
            if not transcript.phone_raw:
                transcript.phone_raw = extracted.raw
            break

    transcript.phone_e164 = e164

    if not e164:
        transcript.status = TranscriptStatus.NEEDS_REVIEW
        return MatchOutcome(
            status=transcript.status,
            reason="W żądaniu ani w treści rozmowy nie ma numeru telefonu.",
        )

    candidates = clients_by_phone(e164)

    if len(candidates) == 1:
        client = candidates[0]
        attach(transcript, client)
        transcript.status = TranscriptStatus.PENDING
        return MatchOutcome(
            status=transcript.status,
            client=client,
            phone_e164=e164,
            reason=f"Numer {phone_pl(e164)} należy do klienta „{client.name}”.",
        )

    if len(candidates) > 1:
        # Świadomie NIE zgadujemy. Przypisanie rozmowy nie temu gospodarstwu
        # jest gorsze niż jedna pozycja więcej w zakładce „Wymagają uwagi".
        transcript.status = TranscriptStatus.NEEDS_REVIEW
        names = ", ".join(f"„{c.name}”" for c in candidates)
        return MatchOutcome(
            status=transcript.status,
            candidates=candidates,
            phone_e164=e164,
            reason=f"Numer {phone_pl(e164)} mają: {names}. Wskaż właściwego.",
        )

    if not create_missing:
        transcript.status = TranscriptStatus.NEEDS_REVIEW
        return MatchOutcome(
            status=transcript.status,
            phone_e164=e164,
            reason=f"Numeru {phone_pl(e164)} nie ma w bazie.",
        )

    client = create_client_from_phone(e164, transcript.phone_raw)
    attach(transcript, client)
    transcript.status = TranscriptStatus.PENDING
    return MatchOutcome(
        status=transcript.status,
        client=client,
        created=True,
        phone_e164=e164,
        reason=f"Numeru {phone_pl(e164)} nie było w bazie — założono nowego klienta.",
    )


def detach(transcript: Transcript) -> None:
    """Odpina rozmowę od klienta — do poprawiania błędnych przypisań."""
    transcript.client_id = None
    transcript.status = TranscriptStatus.NEEDS_REVIEW


__all__ = [
    "ExtractedPhone",
    "MatchOutcome",
    "attach",
    "clients_by_phone",
    "create_client_from_phone",
    "detach",
    "extract_phones",
    "resolve",
]
