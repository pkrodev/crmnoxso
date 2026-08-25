"""Testy promptu i parsowania odpowiedzi modelu (etap 5).

Specyfikacja wymienia parsowanie odpowiedzi AI wśród miejsc, które trzeba
przetestować, i słusznie: to jedyny moment, w którym do bazy wchodzą dane
wygenerowane przez maszynę, nad którą nie mamy kontroli. Model potrafi odpowiedzieć
po polsku, mimo że prosiliśmy o wartość z listy; potrafi wstawić `"null"` jako
napis; potrafi podać datę z kropkami. Żadna z tych rzeczy nie ma prawa wywalić
przetwarzania ani wpisać śmiecia do kalendarza.

Testy nie ruszają sieci — sprawdzają czysty kształt promptu i walidację.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app.services.ai import (
    MAX_INPUT_CHARS,
    AiError,
    build_messages,
    parse_response,
)

TODAY = dt.date(2026, 8, 25)  # wtorek

PELNA_ODPOWIEDZ = {
    "summary": "Klient pyta o siewnik i prosi o ofertę.",
    "client_name": "Gospodarstwo Rolne Kowalski",
    "sentiment": "positive",
    "outcome": "zainteresowany",
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
    "key_points": ["Interesuje go siewnik", "Prosi o ofertę mailem"],
}


def _parse(payload: dict) -> object:
    return parse_response(json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def test_prompt_contains_todays_date():
    """Bez daty odniesienia „w przyszły wtorek" nie znaczy nic."""
    user = build_messages("Rozmowa.", TODAY)[1]["content"]

    assert "2026-08-25" in user
    assert "wtorek" in user


def test_prompt_carries_the_transcript():
    user = build_messages("Rozmowa o kombajnie Claas.", TODAY)[1]["content"]
    assert "Rozmowa o kombajnie Claas." in user


def test_prompt_has_a_system_part_with_the_json_shape():
    system = build_messages("x", TODAY)[0]
    assert system["role"] == "system"
    for key in ("summary", "sentiment", "outcome", "events", "confidence"):
        assert key in system["content"]


def test_overlong_transcript_is_cut_and_the_model_is_told():
    user = build_messages("a" * (MAX_INPUT_CHARS + 5000), TODAY)[1]["content"]

    assert "a" * 100 in user
    assert len(user) < MAX_INPUT_CHARS + 2000
    assert "ucięty" in user


# ---------------------------------------------------------------------------
# Poprawna odpowiedź
# ---------------------------------------------------------------------------


def test_full_response_is_parsed():
    analysis = _parse(PELNA_ODPOWIEDZ)

    assert analysis.summary.startswith("Klient pyta")
    assert analysis.client_name == "Gospodarstwo Rolne Kowalski"
    assert analysis.sentiment == "positive"
    assert analysis.outcome == "zainteresowany"
    assert analysis.follow_up_needed is True
    assert len(analysis.key_points) == 2

    event = analysis.events[0]
    assert event.title == "Pokaz siewnika"
    assert event.date == dt.date(2026, 9, 1)
    assert event.time == dt.time(14, 0)
    assert event.confidence == "high"


# ---------------------------------------------------------------------------
# To, co model naprawdę zwraca
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("pozytywny", "positive"),
        ("NEGATYWNY", "negative"),
        ("neutral", "neutral"),
        ("zdecydowanie entuzjastyczny", "neutral"),
        (None, "neutral"),
        ("", "neutral"),
    ],
)
def test_sentiment_is_brought_back_to_the_allowed_set(given, expected):
    analysis = _parse({**PELNA_ODPOWIEDZ, "sentiment": given})
    assert analysis.sentiment == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("do oddzwonienia", "do oddzwonienia"),
        ("Umówiono spotkanie", "umówiono spotkanie"),
        ("klient się zastanowi", "inne"),
        (None, "inne"),
    ],
)
def test_outcome_outside_the_list_becomes_other(given, expected):
    analysis = _parse({**PELNA_ODPOWIEDZ, "outcome": given})
    assert analysis.outcome == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("2026-09-01", dt.date(2026, 9, 1)),
        ("01.09.2026", dt.date(2026, 9, 1)),
        ("01-09-2026", dt.date(2026, 9, 1)),
        ("2026-09-01T14:00:00", dt.date(2026, 9, 1)),
        ("w przyszłym tygodniu", None),
        ("null", None),
        (None, None),
    ],
)
def test_event_date_notations(given, expected):
    payload = {**PELNA_ODPOWIEDZ, "events": [{"title": "X", "date": given}]}
    assert _parse(payload).events[0].date == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("14:00", dt.time(14, 0)),
        ("14.30", dt.time(14, 30)),
        ("9", dt.time(9, 0)),
        ("25:00", None),
        ("rano", None),
        (None, None),
    ],
)
def test_event_time_notations(given, expected):
    payload = {**PELNA_ODPOWIEDZ, "events": [{"title": "X", "time": given}]}
    assert _parse(payload).events[0].time == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("high", "high"),
        ("wysoka", "high"),
        ("niska", "low"),
        ("dziwna", "low"),
        (None, "low"),
    ],
)
def test_confidence_defaults_to_low_when_unclear(given, expected):
    """Domyślnie NISKA — niepewność ma być widoczna, a nie zamiatana pod dywan."""
    payload = {**PELNA_ODPOWIEDZ, "events": [{"title": "X", "confidence": given}]}
    assert _parse(payload).events[0].confidence == expected


def test_string_null_is_treated_as_no_value():
    analysis = _parse({**PELNA_ODPOWIEDZ, "client_name": "null"})
    assert analysis.client_name is None


def test_lists_given_as_null_become_empty():
    analysis = _parse({**PELNA_ODPOWIEDZ, "events": None, "key_points": None})
    assert analysis.events == []
    assert analysis.key_points == []


def test_missing_optional_fields_have_defaults():
    analysis = _parse({"summary": "Krótka rozmowa."})

    assert analysis.client_name is None
    assert analysis.sentiment == "neutral"
    assert analysis.outcome == "inne"
    assert analysis.events == []
    assert analysis.follow_up_needed is False


def test_unknown_extra_keys_are_ignored():
    analysis = _parse({**PELNA_ODPOWIEDZ, "wymyslone_pole": {"cokolwiek": 1}})
    assert analysis.summary.startswith("Klient pyta")


def test_event_without_a_title_gets_a_neutral_one():
    payload = {**PELNA_ODPOWIEDZ, "events": [{"date": "2026-09-01"}]}
    assert _parse(payload).events[0].title == "Ustalenie z rozmowy"


# ---------------------------------------------------------------------------
# Odpowiedzi nie do przyjęcia
# ---------------------------------------------------------------------------


def test_response_that_is_not_json_is_rejected():
    with pytest.raises(AiError):
        parse_response("Oczywiście! Oto podsumowanie rozmowy:")


def test_json_that_is_not_an_object_is_rejected():
    with pytest.raises(AiError):
        parse_response('["podsumowanie"]')


def test_response_without_a_summary_is_rejected():
    """Bez podsumowania analiza nie ma wartości — lepiej ponowić próbę."""
    with pytest.raises(AiError):
        parse_response('{"sentiment": "positive"}')


def test_empty_summary_is_rejected():
    with pytest.raises(AiError):
        parse_response('{"summary": "   "}')
