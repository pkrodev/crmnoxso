"""Analiza transkrypcji modelem językowym (etap 5).

Model siedzi za własnym interfejsem — reszta aplikacji nie wie, że to akurat
DeepSeek, i podmiana dostawcy nie wymaga ruszania niczego poza tym plikiem.

Dwie rzeczy są tu ważniejsze niż wszystko inne:

1. **Prompt musi zawierać dzisiejszą datę.** W rozmowach padają określenia
   względne („w przyszły wtorek", „za dwa tygodnie", „pod koniec miesiąca").
   Bez daty odniesienia model wygeneruje terminy z sufitu, a te wylądują
   w kalendarzu jako propozycje spotkań.
2. **Odpowiedź modelu to dane z zewnątrz, nie prawda objawiona.** Wymuszamy
   JSON i walidujemy go Pydantikiem, z tolerancją na to, co model naprawdę
   zwraca: polskie nazwy wydźwięku, datę z kropkami, ``"null"`` jako napis,
   godzinę bez minut. Nic z tego nie ma prawa wywalić przetwarzania.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Górna granica długości transkrypcji wysyłanej do modelu. Endpoint przyjmuje
# do 1 MB, co przy polskim tekście daje grubo ponad ćwierć miliona tokenów —
# więcej, niż mieści okno kontekstu. Dłuższą rozmowę tniemy i mówimy o tym
# modelowi wprost, zamiast dostać błąd albo cichy śmieć.
MAX_INPUT_CHARS = 40_000

SENTIMENTS = ("positive", "neutral", "negative")

# Model bywa uprzejmy i odpowiada po polsku, mimo że prosimy o wartość z listy.
_SENTIMENT_ALIASES = {
    "pozytywny": "positive",
    "pozytywne": "positive",
    "neutralny": "neutral",
    "neutralne": "neutral",
    "negatywny": "negative",
    "negatywne": "negative",
    "mieszany": "neutral",
}

OUTCOMES = (
    "zainteresowany",
    "brak zainteresowania",
    "do oddzwonienia",
    "umówiono spotkanie",
    "inne",
)

CONFIDENCES = ("high", "medium", "low")

_CONFIDENCE_ALIASES = {
    "wysoka": "high",
    "wysokie": "high",
    "średnia": "medium",
    "srednia": "medium",
    "niska": "low",
    "niskie": "low",
}

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y")

# Etykiety do interfejsu. Wartości trzymamy po angielsku (tak są w bazie i tak
# odpowiada model), ale użytkownik widzi polskie.
SENTIMENT_LABELS = {
    "positive": "Pozytywny",
    "neutral": "Neutralny",
    "negative": "Negatywny",
}

CONFIDENCE_LABELS = {
    "high": "pewny termin",
    "medium": "termin prawdopodobny",
    "low": "termin niepewny",
}

WEEKDAYS_PL = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)


class AiError(RuntimeError):
    """Analiza się nie udała — sieć, limit, nieparsowalna odpowiedź."""


class AiNotConfigured(AiError):
    """Brak klucza API. Nie jest to błąd przetwarzania, tylko braku konfiguracji."""


# ---------------------------------------------------------------------------
# Kształt odpowiedzi
# ---------------------------------------------------------------------------


def _blank_to_none(value: Any) -> Any:
    """``""``, ``"null"``, ``"brak"`` → ``None``. Model lubi każdy z tych zapisów."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {
            "null",
            "none",
            "brak",
            "nie podano",
            "-",
        }:
            return None
        return stripped
    return value


class AiEvent(BaseModel):
    """Jedno ustalenie z rozmowy, które ma trafić do kalendarza."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    # Domyślna wartość, a nie pole wymagane: brak tytułu nie jest powodem, żeby
    # odrzucić całą analizę i ponawiać próbę.
    title: str = Field(default="Ustalenie z rozmowy", max_length=300)
    description: str | None = None
    date: dt.date | None = None
    time: dt.time | None = None
    confidence: Literal["high", "medium", "low"] = "low"

    @field_validator("description", mode="before")
    @classmethod
    def _description(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, value: Any) -> Any:
        text = _blank_to_none(value)
        return "Ustalenie z rozmowy" if text is None else str(text)[:300]

    @field_validator("date", mode="before")
    @classmethod
    def _date(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None or isinstance(value, dt.date):
            return value
        text = str(value).split("T")[0].strip()
        for fmt in _DATE_FORMATS:
            try:
                return dt.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        # Data nie do odczytania znaczy „nieokreślona", a nie „przerwij analizę".
        return None

    @field_validator("time", mode="before")
    @classmethod
    def _time(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None or isinstance(value, dt.time):
            return value
        text = str(value).strip().replace(".", ":")
        match = re.match(r"^(\d{1,2})(?::(\d{2}))?", text)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if hour > 23 or minute > 59:
            return None
        return dt.time(hour, minute)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None:
            return "low"
        text = str(value).strip().lower()
        text = _CONFIDENCE_ALIASES.get(text, text)
        return text if text in CONFIDENCES else "low"


class AiAnalysis(BaseModel):
    """Odpowiedź modelu po walidacji — kształt z sekcji 9 specyfikacji."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    summary: str
    client_name: str | None = None
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    outcome: str = "inne"
    events: list[AiEvent] = Field(default_factory=list)
    follow_up_needed: bool = False
    key_points: list[str] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, value: Any) -> Any:
        text = _blank_to_none(value)
        if text is None:
            raise ValueError("Model nie zwrócił podsumowania.")
        return str(text)

    @field_validator("client_name", mode="before")
    @classmethod
    def _client_name(cls, value: Any) -> Any:
        text = _blank_to_none(value)
        return str(text)[:300] if text is not None else None

    @field_validator("sentiment", mode="before")
    @classmethod
    def _sentiment(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None:
            return "neutral"
        text = str(value).strip().lower()
        text = _SENTIMENT_ALIASES.get(text, text)
        return text if text in SENTIMENTS else "neutral"

    @field_validator("outcome", mode="before")
    @classmethod
    def _outcome(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None:
            return "inne"
        text = str(value).strip().lower()
        return text if text in OUTCOMES else "inne"

    @field_validator("events", "key_points", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> Any:
        # Model potrafi zwrócić `null` zamiast pustej listy.
        return [] if value is None else value

    @field_validator("key_points", mode="after")
    @classmethod
    def _clean_points(cls, value: list[str]) -> list[str]:
        return [point for point in (p.strip() for p in value) if point][:20]


@dataclass(slots=True)
class AiResult:
    analysis: AiAnalysis
    raw: dict[str, Any] = field(default_factory=dict)
    tokens_used: int | None = None
    model: str = ""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
Jesteś asystentem właściciela firmy NOXSO, która sprzedaje i serwisuje maszyny
rolnicze w Wielkopolsce. Dostajesz zapis rozmowy telefonicznej z klientem —
gospodarstwem rolnym, spółdzielnią kółek rolniczych albo firmą rolniczą.

Zapis pochodzi z automatycznej transkrypcji, więc bywa w nim gwara, skróty
branżowe i przekręcone nazwy maszyn. Nie poprawiaj ich — rozumiej.

Odpowiadasz WYŁĄCZNIE obiektem JSON o dokładnie takich kluczach:

{
  "summary": "2-3 zdania po polsku, o czym była rozmowa",
  "client_name": "nazwa firmy albo osoby, jeśli padła w rozmowie; inaczej null",
  "sentiment": "positive | neutral | negative",
  "outcome": "zainteresowany | brak zainteresowania | do oddzwonienia | umówiono spotkanie | inne",
  "events": [
    {
      "title": "krótki tytuł",
      "description": "kontekst z rozmowy",
      "date": "RRRR-MM-DD albo null, gdy termin nie padł",
      "time": "GG:MM albo null, gdy godzina nie padła",
      "confidence": "high | medium | low"
    }
  ],
  "follow_up_needed": true,
  "key_points": ["najważniejsze ustalenia, po polsku"]
}

Zasady:
- Wartości "sentiment", "outcome" i "confidence" bierz DOKŁADNIE z podanych list.
- Do "events" wpisuj wyłącznie rzeczy umówione na konkretny moment: spotkanie,
  dostawa, oddzwonienie, przegląd. Nie wstawiaj tam ogólnych zamiarów.
- Terminy względne przeliczaj na daty względem dzisiejszej daty podanej niżej.
- Jeśli terminu nie da się ustalić, wpisz null. NIE zgaduj daty.
- "confidence" ustaw na "low", gdy termin wynika z domysłu, a nie z wypowiedzi.
- Nie wymyślaj faktów, których w rozmowie nie ma."""


def build_messages(text: str, today: dt.date) -> list[dict[str, str]]:
    """Wiadomości do modelu. Data dzisiejsza jest tu obowiązkowa, nie ozdobna."""
    weekday = WEEKDAYS_PL[today.weekday()]
    body = text.strip()
    truncated = ""
    if len(body) > MAX_INPUT_CHARS:
        body = body[:MAX_INPUT_CHARS]
        truncated = (
            "\n\n[UWAGA: zapis został ucięty na potrzeby analizy — "
            "dalsza część rozmowy nie jest tu widoczna.]"
        )

    user = (
        f"Dzisiaj jest {today.isoformat()} ({weekday}).\n"
        "Wszystkie określenia względne w rozmowie (jutro, w przyszły wtorek,\n"
        "za dwa tygodnie) przelicz na daty właśnie od tego dnia.\n\n"
        f"Zapis rozmowy:\n\n{body}{truncated}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_response(content: str) -> AiAnalysis:
    """Tekst odpowiedzi → zwalidowany obiekt. Rzuca ``AiError`` przy śmieciu."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise AiError(f"Odpowiedź modelu nie jest JSON-em: {exc}") from exc

    if not isinstance(data, dict):
        raise AiError("Odpowiedź modelu nie jest obiektem JSON.")

    try:
        return AiAnalysis.model_validate(data)
    except ValidationError as exc:
        raise AiError(f"Odpowiedź modelu nie przeszła walidacji: {exc}") from exc


# ---------------------------------------------------------------------------
# Dostawca
# ---------------------------------------------------------------------------


class AiProvider(Protocol):
    def analyse(self, text: str, *, today: dt.date) -> AiResult: ...


class DeepSeekProvider:
    """DeepSeek przez SDK ``openai`` — API jest z nim zgodne."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = DEEPSEEK_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise AiNotConfigured("Brak DEEPSEEK_API_KEY.")
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def analyse(self, text: str, *, today: dt.date) -> AiResult:
        try:
            # Typy SDK wymieniają modele OpenAI z nazwy, a my podajemy nazwę
            # modelu DeepSeeka — stąd wyciszenie. W czasie działania to zwykły
            # łańcuch znaków i API jest zgodne.
            response = self._client.chat.completions.create(  # type: ignore[call-overload]
                model=self.model,
                messages=build_messages(text, today),
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except Exception as exc:  # SDK ma własną hierarchię wyjątków
            raise AiError(f"Model nie odpowiedział: {exc}") from exc

        choices = response.choices or []
        content = choices[0].message.content if choices else None
        if not content:
            raise AiError("Model zwrócił pustą odpowiedź.")

        analysis = parse_response(content)
        usage = getattr(response, "usage", None)

        return AiResult(
            analysis=analysis,
            raw=json.loads(content),
            tokens_used=getattr(usage, "total_tokens", None),
            model=self.model,
        )


def get_provider(config: Any = None) -> AiProvider:
    """Dostawca zbudowany z konfiguracji aplikacji.

    Podnosi ``AiNotConfigured``, gdy nie ma klucza — zadanie w tle rozpoznaje ten
    wyjątek i po prostu nie robi nic, zamiast liczyć nieudane próby transkrypcjom.
    """
    if config is None:
        from flask import current_app

        config = current_app.config

    api_key = config.get("DEEPSEEK_API_KEY") or ""
    if not api_key:
        raise AiNotConfigured(
            "Brak DEEPSEEK_API_KEY w konfiguracji — analiza rozmów jest wyłączona."
        )
    return DeepSeekProvider(
        api_key=api_key, model=config.get("AI_MODEL") or "deepseek-chat"
    )


__all__ = [
    "AiAnalysis",
    "AiError",
    "AiEvent",
    "AiNotConfigured",
    "AiProvider",
    "AiResult",
    "DeepSeekProvider",
    "build_messages",
    "get_provider",
    "parse_response",
]
