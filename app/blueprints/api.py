"""Endpointy poza sesją użytkownika: przyjmowanie transkrypcji (etap 4).

Etap 7 dołoży tu webhook doręczeń SMS. Oba endpointy mają własną autoryzację —
token w nagłówku i podpis HMAC — więc blueprint jest wypisany w
``PUBLIC_BLUEPRINTS`` i zwolniony z ochrony CSRF (nie ma tu formularzy ani
ciasteczka sesji, którym można by się posłużyć w ataku).
"""

from __future__ import annotations

import datetime as dt
import hmac
import re
from typing import Any

from charset_normalizer import from_bytes
from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.extensions import db, limiter
from app.models import Transcript, TranscriptStatus
from app.services import matching
from app.services.normalize import normalize_phone

bp = Blueprint("api", __name__)

# Data rozmowy bywa podawana po polsku (14.03.2026) albo po amerykańsku
# przez narzędzie kolegi (2026-03-14). Przyjmujemy oba zapisy.
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y")


class TranscriptIn(BaseModel):
    """Wejście endpointu — jedno i to samo dla JSON-a i dla multipartu."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    text: str = Field(min_length=1)
    phone: str | None = None
    call_date: dt.date | None = Field(default=None, alias="date")
    filename: str | None = Field(default=None, max_length=255)

    @field_validator("phone", "filename", mode="before")
    @classmethod
    def _empty_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("call_date", mode="before")
    @classmethod
    def _parse_date(cls, value: Any) -> Any:
        if value is None or isinstance(value, dt.date):
            return value
        text = str(value).strip()
        if not text:
            return None
        # Znacznik czasu ISO z godziną — bierzemy sam dzień.
        text = text.split("T")[0].split(" ")[0]
        for fmt in _DATE_FORMATS:
            try:
                return dt.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError("Nieznany format daty. Użyj RRRR-MM-DD albo DD.MM.RRRR.")


def _error(message: str, status: int, **extra: Any):
    return jsonify({"error": message, **extra}), status


def _authorized() -> bool:
    """Bearer token porównywany ``compare_digest``, nie ``==``.

    Zwykłe porównanie kończy się na pierwszym różnym znaku, co przy odpowiednio
    wielu próbach zdradza token po czasie odpowiedzi.
    """
    expected = current_app.config.get("INGEST_TOKEN") or ""
    if not expected:
        return False
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(token.strip(), expected)


def _decode(data: bytes) -> str:
    """Bajty pliku ``.txt`` na tekst.

    Pliki przychodzą z Windowsa i bywają w CP1250, a bywają w UTF-8 — bez
    wykrycia kodowania polskie znaki rozsypałyby się na krzaki. Najpierw próba
    UTF-8 (z BOM-em i bez), potem wykrywanie ``charset-normalizer``.
    """
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    best = from_bytes(data).best()
    if best is None:
        raise ValueError("Nie udało się rozpoznać kodowania pliku.")
    return str(best)


def _payload() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """Wyciąga dane z multipartu albo z JSON-a. Zwraca (dane, błąd)."""
    limit = current_app.config["INGEST_MAX_BYTES"]

    if "file" in request.files:
        upload = request.files["file"]
        data = upload.read()
        if not data:
            return None, _error("Wgrany plik jest pusty.", 400)
        if len(data) > limit:
            return None, _error(
                f"Plik ma {len(data) / 1024:.0f} kB, limit to {limit // 1024} kB.", 413
            )
        try:
            text = _decode(data)
        except ValueError as exc:
            return None, _error(str(exc), 400)
        return {
            "text": text,
            "phone": request.form.get("phone"),
            "date": request.form.get("date"),
            "filename": request.form.get("filename") or upload.filename,
        }, None

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, _error(
            "Oczekiwano pliku w polu `file` albo obiektu JSON z polem `text`.", 400
        )
    raw_text = body.get("text")
    if isinstance(raw_text, str) and len(raw_text.encode("utf-8")) > limit:
        return None, _error(f"Treść przekracza limit {limit // 1024} kB.", 413)
    return body, None


@bp.post("/ingest/transcript")
@limiter.limit("120 per minute")
def ingest_transcript():
    """Przyjmuje transkrypcję i **natychmiast** oddaje 202.

    Analiza AI (etap 5) chodzi w tle, więc klient nie czeka na model. Tu dzieje
    się tylko to, co tanie: zapis surowego tekstu i dopasowanie po numerze.
    """
    if not current_app.config.get("INGEST_TOKEN"):
        return _error("Endpoint nie jest skonfigurowany (brak INGEST_TOKEN).", 503)
    if not _authorized():
        return _error("Brak autoryzacji.", 401)

    data, failure = _payload()
    if failure is not None:
        return failure
    assert data is not None

    try:
        payload = TranscriptIn.model_validate(data)
    except ValidationError as exc:
        return _error(
            "Dane nie przeszły walidacji.",
            422,
            details=[
                {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
                for err in exc.errors()
            ],
        )

    text = payload.text.strip()
    if not text:
        return _error("Transkrypcja jest pusta.", 422)

    candidate = normalize_phone(payload.phone) if payload.phone else None

    transcript = Transcript(
        raw_text=text,
        phone_raw=payload.phone,
        phone_e164=candidate.e164 if candidate else None,
        call_date=payload.call_date,
        source_file=_safe_filename(payload.filename),
        status=TranscriptStatus.PENDING,
    )
    db.session.add(transcript)
    db.session.flush()

    outcome = matching.resolve(transcript)
    db.session.commit()

    current_app.logger.info(
        "Transkrypcja %s: %s (%s)", transcript.id, outcome.status.value, outcome.reason
    )

    return (
        jsonify(
            {
                "id": transcript.id,
                "status": transcript.status.value,
                "client_id": transcript.client_id,
                "client_created": outcome.created,
                "phone": transcript.phone_e164,
                "message": outcome.reason,
            }
        ),
        202,
    )


def _safe_filename(name: str | None) -> str | None:
    """Nazwa pliku tylko do pokazania na liście — bez ścieżek i znaków sterujących."""
    if not name:
        return None
    cleaned = re.sub(r"[\x00-\x1f]", "", name.replace("\\", "/").split("/")[-1])
    return cleaned[:255] or None


@bp.errorhandler(413)
def too_large(_error):  # type: ignore[misc]
    """Żądanie ucięte przez MAX_CONTENT_LENGTH — odpowiadamy JSON-em, nie HTML-em."""
    limit = current_app.config["INGEST_MAX_BYTES"]
    return jsonify({"error": f"Żądanie za duże. Limit to {limit // 1024} kB."}), 413
