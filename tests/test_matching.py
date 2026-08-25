"""Testy dopasowania rozmowy do klienta (etap 4).

Dwa miejsca, w których cichy błąd byłby najdroższy:

1. **Wyłuskiwanie numeru z treści.** Za ostry wzorzec zassie NIP albo datę
   i przypisze rozmowę losowemu gospodarstwu. Za luźny — nie znajdzie nic
   i każda rozmowa wyląduje w „Wymagają uwagi".
2. **Numer wspólny dla kilku klientów.** W bazie źródłowej takich numerów jest
   58. System nie ma prawa zgadywać, do kogo należy rozmowa.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Wyłuskiwanie numeru z treści rozmowy — bez bazy
# ---------------------------------------------------------------------------


def _extracted(text: str) -> list[str]:
    from app.services.matching import extract_phones

    return [phone.e164 for phone in extract_phones(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dzwonię z numeru +48 601 092 947 w sprawie kosiarki.", "+48601092947"),
        ("Mój numer to 601-092-947. Proszę oddzwonić.", "+48601092947"),
        ("Kontakt: 889 869 505", "+48889869505"),
        ("proszę dzwonić na 601092947", "+48601092947"),
        ("Stacjonarny 62 733 61 49, odbieram do szesnastej.", "+48627336149"),
        ("Zadzwoń na 0601092947 wieczorem.", "+48601092947"),
        ("numer 48601092947 jest aktualny", "+48601092947"),
    ],
)
def test_extracts_number_in_every_convention(text, expected):
    assert _extracted(text) == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "NIP naszej firmy to 617-101-01-49, proszę zapisać.",
        "Rozmowa z dnia 2026-03-14 o godzinie 14:00.",
        "Kwota to 1 200 000 zł netto.",
        "Numer działki 123/4 w obrębie 05.",
        "Rozmowa bez numeru telefonu w treści.",
        "",
    ],
)
def test_does_not_mistake_other_numbers_for_a_phone(text):
    """NIP, data i kwota nie są poprawnymi numerami polskimi — mają odpaść."""
    assert _extracted(text) == []


def test_number_split_by_newline_does_not_glue_into_one():
    """Koniec jednej linii i początek następnej to NIE jeden numer."""
    text = "Zapisuję 62 733\n61 49 do dokumentów."
    assert _extracted(text) == []


def test_two_numbers_in_one_line_give_two_results():
    text = "Numery kontaktowe: 606420728   632767173 — oba czynne."
    assert _extracted(text) == ["+48606420728", "+48632767173"]


def test_same_number_twice_counts_once():
    text = "Dzwoniłem na 601 092 947, potem jeszcze raz na +48601092947."
    assert _extracted(text) == ["+48601092947"]


def test_order_of_appearance_is_preserved():
    """Pierwszy numer w rozmowie to zwykle numer rozmówcy — kolejność ma znaczenie."""
    text = "Mój to 601 092 947, a do brata dzwoń na 607 137 842."
    assert _extracted(text) == ["+48601092947", "+48607137842"]


def test_number_of_candidates_is_capped():
    from app.services.matching import MAX_PHONES_FROM_TEXT

    numbers = [
        "601092947",
        "607137842",
        "889869505",
        "627528058",
        "691747038",
        "722099015",
        "606420728",
    ]
    text = " oraz ".join(numbers)
    assert len(_extracted(text)) == MAX_PHONES_FROM_TEXT


# ---------------------------------------------------------------------------
# Dopasowanie do klienta — z bazą
# ---------------------------------------------------------------------------


@pytest.fixture
def make_client(session):
    from app.models import Client, Phone
    from app.services.normalize import normalize_phone

    def make(name: str, *phones: str) -> Client:
        client = Client(name=name)
        for index, raw in enumerate(phones):
            candidate = normalize_phone(raw)
            client.phones.append(
                Phone(e164=candidate.e164, raw=raw, is_primary=index == 0)
            )
        session.add(client)
        session.flush()
        return client

    return make


@pytest.fixture
def make_transcript(session):
    from app.models import Transcript, TranscriptStatus

    def make(text: str, *, phone: str | None = None, call_date=None) -> Transcript:
        from app.services.normalize import normalize_phone

        candidate = normalize_phone(phone) if phone else None
        transcript = Transcript(
            raw_text=text,
            phone_raw=phone,
            phone_e164=candidate.e164 if candidate else None,
            call_date=call_date,
            status=TranscriptStatus.PENDING,
        )
        session.add(transcript)
        session.flush()
        return transcript

    return make


@pytest.mark.db
def test_matches_client_by_number_from_request(session, make_client, make_transcript):
    from app.models import TranscriptStatus
    from app.services import matching

    client = make_client("Gospodarstwo Rolne Kowalski", "+48601092947")
    transcript = make_transcript("Rozmowa o kosiarce.", phone="601-092-947")

    outcome = matching.resolve(transcript)
    session.commit()

    assert outcome.client is not None
    assert outcome.client.id == client.id
    assert transcript.client_id == client.id
    assert transcript.status == TranscriptStatus.PENDING


@pytest.mark.db
def test_matches_client_by_number_found_in_text(session, make_client, make_transcript):
    from app.services import matching

    client = make_client("SKR w Stawiszynie", "+48627528058")
    transcript = make_transcript(
        "Dzień dobry, tu Nowak, 62 752 80 58, w sprawie siewnika."
    )

    outcome = matching.resolve(transcript)
    session.commit()

    assert transcript.client_id == client.id
    assert transcript.phone_e164 == "+48627528058"
    assert outcome.created is False


@pytest.mark.db
def test_unknown_number_creates_client(session, make_transcript):
    from app.models import TAG_FROM_TRANSCRIPT, ActivityType, ClientSource
    from app.services import matching

    transcript = make_transcript("Pytanie o ofertę.", phone="+48601092947")

    outcome = matching.resolve(transcript)
    session.commit()

    client = outcome.client
    assert outcome.created is True
    assert client is not None
    assert client.source == ClientSource.TRANSCRIPT
    assert client.has_tag(TAG_FROM_TRANSCRIPT)
    assert client.primary_phone is not None
    assert client.primary_phone.e164 == "+48601092947"

    types = {activity.type for activity in client.activities}
    assert ActivityType.CLIENT_CREATED in types
    assert ActivityType.CALL_TRANSCRIBED in types


@pytest.mark.db
def test_number_shared_by_two_clients_is_not_guessed(
    session, make_client, make_transcript
):
    """58 numerów w bazie źródłowej należy do kilku gospodarstw naraz."""
    from app.models import TranscriptStatus
    from app.services import matching

    make_client("Gospodarstwo Kowalski Jan", "+48601092947")
    make_client("Gospodarstwo Kowalska Anna", "+48601092947")
    transcript = make_transcript("Rozmowa.", phone="+48601092947")

    outcome = matching.resolve(transcript)
    session.commit()

    assert transcript.client_id is None
    assert transcript.status == TranscriptStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 2
    assert "Kowalski" in outcome.reason


@pytest.mark.db
def test_transcript_without_any_number_waits_for_a_human(session, make_transcript):
    from app.models import TranscriptStatus
    from app.services import matching

    transcript = make_transcript("Rozmowa, w której nikt nie podał numeru.")

    outcome = matching.resolve(transcript)
    session.commit()

    assert transcript.client_id is None
    assert transcript.phone_e164 is None
    assert transcript.status == TranscriptStatus.NEEDS_REVIEW
    assert outcome.matched is False


@pytest.mark.db
def test_client_creation_can_be_switched_off(session, make_transcript):
    from app.models import Client, TranscriptStatus
    from app.services import matching

    transcript = make_transcript("Rozmowa.", phone="+48601092947")

    outcome = matching.resolve(transcript, create_missing=False)
    session.commit()

    assert outcome.client is None
    assert transcript.status == TranscriptStatus.NEEDS_REVIEW
    assert session.scalar(sa_count(Client)) == 0


@pytest.mark.db
def test_call_date_lands_on_the_right_day_of_the_timeline(
    session, make_client, make_transcript
):
    """Data rozmowy nie może się przesunąć o dzień przy przeliczeniu na UTC."""
    from datetime import date

    from app.filters import to_local
    from app.services import matching

    make_client("Klient z datą", "+48601092947")
    transcript = make_transcript(
        "Rozmowa sprzed tygodnia.", phone="+48601092947", call_date=date(2026, 3, 14)
    )

    matching.resolve(transcript)
    session.commit()

    activity = next(
        a for a in transcript.client.activities if a.type.value == "CALL_TRANSCRIBED"
    )
    local = to_local(activity.occurred_at)
    assert local is not None
    assert local.date() == date(2026, 3, 14)


@pytest.mark.db
def test_detach_sends_transcript_back_to_review(session, make_client, make_transcript):
    from app.models import TranscriptStatus
    from app.services import matching

    make_client("Klient", "+48601092947")
    transcript = make_transcript("Rozmowa.", phone="+48601092947")
    matching.resolve(transcript)
    session.commit()

    matching.detach(transcript)
    session.commit()

    assert transcript.client_id is None
    assert transcript.status == TranscriptStatus.NEEDS_REVIEW


def sa_count(model):
    import sqlalchemy as sa

    return sa.select(sa.func.count()).select_from(model)
