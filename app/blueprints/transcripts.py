"""Ekran rozmów — lista, zakładka „Wymagają uwagi" i ręczne przypisanie klienta.

Rozmowa trafia do systemu endpointem ``/api/ingest/transcript`` i dopasowuje się
sama po numerze telefonu. Ten ekran obsługuje resztę: przypadki, w których numeru
nie było, był wieloznaczny albo dopasował się do złego klienta.
"""

from __future__ import annotations

import sqlalchemy as sa
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import ActivityActor, ActivityType, Client, Transcript, TranscriptStatus
from app.services import matching
from app.services import transcripts as service
from app.services.clients import ClientFilters, build_query, log_activity

bp = Blueprint("transcripts", __name__)

# Ilu klientów pokazujemy w podpowiedziach przy ręcznym przypisaniu.
PICKER_LIMIT = 10


def _get(transcript_id: int) -> Transcript:
    transcript = db.session.scalar(
        sa.select(Transcript)
        .where(Transcript.id == transcript_id)
        .options(selectinload(Transcript.client))
    )
    if transcript is None:
        abort(404)
    return transcript


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------


@bp.route("/")
def index():
    filters = service.TranscriptFilters.from_request(request.args)
    page = service.list_transcripts(filters)

    if _is_htmx():
        return render_template("transcripts/_table.html", page=page, filters=filters)

    return render_template(
        "transcripts/index.html",
        page=page,
        filters=filters,
        counts=service.status_counts(),
        statuses=list(TranscriptStatus),
        attention=service.ATTENTION,
    )


# ---------------------------------------------------------------------------
# Pojedyncza rozmowa
# ---------------------------------------------------------------------------


@bp.route("/<int:transcript_id>")
def detail(transcript_id: int):
    transcript = _get(transcript_id)

    # Numer bywa wspólny dla kilku gospodarstw — pokazujemy wszystkich, żeby
    # użytkownik wybrał właściwego jednym kliknięciem.
    candidates: list[Client] = []
    if transcript.client_id is None and transcript.phone_e164:
        candidates = matching.clients_by_phone(transcript.phone_e164)

    return render_template(
        "transcripts/detail.html",
        transcript=transcript,
        candidates=candidates,
        found_in_text=matching.extract_phones(transcript.raw_text),
    )


@bp.route("/<int:transcript_id>/tresc")
def body(transcript_id: int):
    """Pełna treść rozmowy jako fragment — dociągana z osi czasu klienta."""
    transcript = _get(transcript_id)
    return render_template("transcripts/_body.html", transcript=transcript)


@bp.route("/<int:transcript_id>/klienci")
def picker(transcript_id: int):
    """Podpowiedzi klientów do ręcznego przypisania (HTMX, wpisywanie na żywo)."""
    transcript = _get(transcript_id)
    query = (request.args.get("q") or "").strip()

    results: list[Client] = []
    if query:
        stmt = build_query(ClientFilters(query=query))
        results = list(
            db.session.scalars(
                stmt.options(selectinload(Client.phones))
                .order_by(Client.name)
                .limit(PICKER_LIMIT)
            ).all()
        )

    return render_template(
        "transcripts/_picker.html",
        transcript=transcript,
        results=results,
        query=query,
    )


@bp.route("/<int:transcript_id>/przypisz", methods=["POST"])
def assign(transcript_id: int):
    transcript = _get(transcript_id)

    try:
        client_id = int(request.form.get("client_id", ""))
    except (TypeError, ValueError):
        flash("Nie wskazano klienta.", "error")
        return redirect(url_for("transcripts.detail", transcript_id=transcript.id))

    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)

    if transcript.client_id == client.id:
        flash("Ta rozmowa jest już przypisana do tego klienta.", "warning")
        return redirect(url_for("transcripts.detail", transcript_id=transcript.id))

    previous = transcript.client

    matching.attach(
        transcript,
        client,
        actor=ActivityActor.USER,
        note="Rozmowa przypisana ręcznie.",
    )

    # Zmiana przypisania: wpis u poprzedniego klienta zostaje (historia kontaktu
    # ma być prawdziwa), ale dopisujemy do niej informację, dokąd rozmowa poszła.
    if previous is not None and previous.id != client.id:
        log_activity(
            previous,
            ActivityType.CLIENT_UPDATED,
            "Rozmowa przeniesiona do innego klienta",
            description=f"Rozmowa #{transcript.id} trafiła do „{client.name}”.",
            meta={"transcript_id": transcript.id, "moved_to": client.id},
            actor=ActivityActor.USER,
        )

    db.session.commit()

    flash(f"Rozmowa przypisana do klienta „{client.name}”.", "success")
    return redirect(url_for("transcripts.detail", transcript_id=transcript.id))


@bp.route("/<int:transcript_id>/odepnij", methods=["POST"])
def unassign(transcript_id: int):
    transcript = _get(transcript_id)
    if transcript.client_id is None:
        flash("Ta rozmowa nie ma przypisanego klienta.", "warning")
    else:
        matching.detach(transcript)
        db.session.commit()
        flash("Rozmowa odpięta od klienta.", "success")
    return redirect(url_for("transcripts.detail", transcript_id=transcript.id))


@bp.route("/<int:transcript_id>/przetworz", methods=["POST"])
def reprocess(transcript_id: int):
    """Ponowne dopasowanie po numerze.

    Typowy scenariusz: rozmowa przyszła z numeru, którego nie było w bazie,
    użytkownik dopisał numer istniejącemu klientowi i chce, żeby rozmowa
    trafiła tam, gdzie trzeba. Etap 5 dołoży do tego przycisku ponowną analizę AI.
    """
    transcript = _get(transcript_id)

    if transcript.client_id is not None:
        matching.detach(transcript)

    transcript.error = None
    transcript.attempts = 0
    outcome = matching.resolve(transcript)
    db.session.commit()

    flash(outcome.reason or "Rozmowa przetworzona ponownie.", "info")
    return redirect(url_for("transcripts.detail", transcript_id=transcript.id))
