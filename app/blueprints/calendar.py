"""Ekran kalendarza (etap 6).

Sam kalendarz to jedyne miejsce w aplikacji, gdzie własnego JavaScriptu nie da
się uniknąć — FullCalendar trzeba zainicjować. Cała reszta jest jak wszędzie:
kliknięcie w wydarzenie prosi serwer o **fragment HTML** i wstawia go w panel
boczny, a przyciski Potwierdź / Edytuj / Usuń to zwykłe żądania HTMX.
"""

from __future__ import annotations

import datetime as dt

from flask import Blueprint, abort, jsonify, render_template, request

from app.extensions import db
from app.models import CalendarEvent, Transcript
from app.services import calendar as service

bp = Blueprint("calendar", __name__)

# Ile znaków rozmowy pokazujemy w panelu wydarzenia. Chodzi o kontekst
# („skąd ten termin?"), nie o czytanie całej transkrypcji — od tego jest
# ekran rozmowy, do którego prowadzi odnośnik.
EXCERPT_CHARS = 600


def _get(event_id: int) -> CalendarEvent:
    event = db.session.get(CalendarEvent, event_id)
    if event is None:
        abort(404)
    return event


def _parse_day(value: str | None) -> dt.date | None:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime((value or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value: str | None) -> dt.time | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H.%M", "%H"):
        try:
            return dt.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _client_id(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Ekran i dane
# ---------------------------------------------------------------------------


@bp.route("/")
def index():
    return render_template(
        "calendar/index.html",
        waiting=service.unconfirmed_count(),
        clients=service.client_options(),
        today=dt.date.today(),
    )


@bp.route("/panel")
def empty():
    """Pusty panel — powrót do stanu wyjściowego po anulowaniu formularza."""
    return render_template("calendar/_empty.html")


@bp.route("/wydarzenia")
def feed():
    """Dane dla FullCalendara. Jedyny endpoint w aplikacji oddający JSON do UI."""
    start, end = service.parse_range(request.args.get("start"), request.args.get("end"))
    return jsonify(
        [service.to_feed(event) for event in service.events_in_range(start, end)]
    )


# ---------------------------------------------------------------------------
# Panel wydarzenia
# ---------------------------------------------------------------------------


@bp.route("/<int:event_id>")
def panel(event_id: int):
    event = _get(event_id)

    excerpt = None
    if event.transcript_id is not None:
        transcript = db.session.get(Transcript, event.transcript_id)
        if transcript is not None:
            excerpt = transcript.ai_summary or transcript.raw_text[:EXCERPT_CHARS]

    return render_template("calendar/_panel.html", event=event, excerpt=excerpt)


@bp.route("/<int:event_id>/potwierdz", methods=["POST"])
def confirm(event_id: int):
    event = _get(event_id)
    service.confirm(event)
    db.session.commit()
    return _panel_with_refresh(event)


@bp.route("/<int:event_id>/edycja")
def edit(event_id: int):
    event = _get(event_id)
    return render_template(
        "calendar/_form.html", event=event, clients=service.client_options()
    )


@bp.route("/<int:event_id>/zapisz", methods=["POST"])
def save(event_id: int):
    event = _get(event_id)

    title = (request.form.get("title") or "").strip()
    day = _parse_day(request.form.get("day"))
    if not title or day is None:
        return render_template(
            "calendar/_form.html",
            event=event,
            clients=service.client_options(),
            error="Podaj tytuł i datę.",
        )

    service.update(
        event,
        title=title,
        day=day,
        moment=_parse_time(request.form.get("time")),
        description=(request.form.get("description") or "").strip() or None,
        client_id=_client_id(request.form.get("client_id")),
    )
    db.session.commit()
    return _panel_with_refresh(event)


@bp.route("/nowe", methods=["GET", "POST"])
def create():
    if request.method == "GET":
        return render_template(
            "calendar/_form.html",
            event=None,
            clients=service.client_options(),
            day=request.args.get("day"),
        )

    title = (request.form.get("title") or "").strip()
    day = _parse_day(request.form.get("day"))
    if not title or day is None:
        return render_template(
            "calendar/_form.html",
            event=None,
            clients=service.client_options(),
            error="Podaj tytuł i datę.",
        )

    event = service.create(
        title=title,
        day=day,
        moment=_parse_time(request.form.get("time")),
        description=(request.form.get("description") or "").strip() or None,
        client_id=_client_id(request.form.get("client_id")),
    )
    db.session.commit()
    return _panel_with_refresh(event)


@bp.route("/<int:event_id>/usun-pytanie")
def delete_confirm(event_id: int):
    """Pytanie przed usunięciem. Osobny fragment, żeby nie sięgać po JS-owy dialog."""
    return render_template("calendar/_delete.html", event=_get(event_id))


@bp.route("/<int:event_id>/usun", methods=["POST"])
def delete(event_id: int):
    event = _get(event_id)
    title = event.title
    service.delete(event)
    db.session.commit()

    response = render_template("calendar/_removed.html", title=title)
    return _with_refresh(response)


# ---------------------------------------------------------------------------
# Odświeżanie siatki kalendarza
# ---------------------------------------------------------------------------


def _with_refresh(html: str):
    """Każe stronie przeładować wydarzenia w kalendarzu.

    HTMX rozgłasza zdarzenie z nagłówka ``HX-Trigger``, a skrypt kalendarza
    nasłuchuje go i woła ``refetchEvents``. Dzięki temu po potwierdzeniu terminu
    kafelek w siatce zmienia wygląd bez przeładowania strony.
    """
    from flask import make_response

    response = make_response(html)
    response.headers["HX-Trigger"] = "kalendarz:odswiez"
    return response


def _panel_with_refresh(event: CalendarEvent):
    excerpt = None
    if event.transcript_id is not None:
        transcript = db.session.get(Transcript, event.transcript_id)
        if transcript is not None:
            excerpt = transcript.ai_summary or transcript.raw_text[:EXCERPT_CHARS]
    return _with_refresh(
        render_template("calendar/_panel.html", event=event, excerpt=excerpt)
    )
