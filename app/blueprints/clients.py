"""Lista klientów i panel pojedynczego klienta.

Cała interaktywność idzie przez HTMX: serwer oddaje **fragment HTML**, nie JSON.
Wyszukiwarka podmienia samo ``<tbody>``, edycja pola podmienia jeden ``<span>``.
Alpine.js pilnuje wyłącznie tego, co musi żyć w przeglądarce — zaznaczenia wierszy.

Każde żądanie zmieniające dane kończy się wpisem na osi czasu klienta
(``Activity``) — to wymóg funkcjonalny z sekcji 4 specyfikacji, nie log techniczny.
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
from app.models import ActivityType, Client, ClientSource, ClientStatus
from app.services import clients as service

bp = Blueprint("clients", __name__)


def _get_client(client_id: int) -> Client:
    client = db.session.scalar(
        sa.select(Client)
        .where(Client.id == client_id)
        .options(selectinload(Client.phones), selectinload(Client.tags))
    )
    if client is None:
        abort(404)
    return client


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------


@bp.route("/")
def index():
    filters = service.ClientFilters.from_request(request.args)
    page = service.list_clients(filters)

    # Żądanie z wyszukiwarki albo z paginacji — oddajemy sam fragment tabeli.
    if _is_htmx():
        return render_template("clients/_table.html", page=page, filters=filters)

    return render_template(
        "clients/index.html",
        page=page,
        filters=filters,
        cities=service.city_options(),
        tags=service.tag_options(),
        statuses=list(ClientStatus),
    )


# ---------------------------------------------------------------------------
# Panel klienta
# ---------------------------------------------------------------------------


@bp.route("/<int:client_id>")
def detail(client_id: int):
    client = _get_client(client_id)
    return render_template(
        "clients/detail.html",
        client=client,
        timeline=service.timeline(client.id),
        pinned=service.pinned_notes(client.id),
        fields=service.EDITABLE_FIELDS,
        statuses=list(ClientStatus),
    )


@bp.route("/nowy", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Nazwa jest wymagana.", "error")
            return render_template("clients/new.html", form=request.form)

        client = Client(name=name, source=ClientSource.MANUAL)
        db.session.add(client)
        db.session.flush()

        for field_name in ("acronym", "nip", "city", "postal_code", "street", "email"):
            value = (request.form.get(field_name) or "").strip()
            if value:
                result = service.update_field(client, field_name, value)
                if not result.ok:
                    db.session.rollback()
                    flash(result.error or "Błąd zapisu.", "error")
                    return render_template("clients/new.html", form=request.form)

        phone = (request.form.get("phone") or "").strip()
        if phone:
            service.add_phone(client, phone)

        service.log_activity(client, ActivityType.CLIENT_CREATED, "Klient dodany ręcznie")
        db.session.commit()
        flash(f"Dodano klienta „{client.name}”.", "success")
        return redirect(url_for("clients.detail", client_id=client.id))

    return render_template("clients/new.html", form={})


# ---------------------------------------------------------------------------
# Edycja pól — wymiana <span> na <input> i z powrotem
# ---------------------------------------------------------------------------


@bp.route("/<int:client_id>/pole/<field_name>/edycja")
def field_edit(client_id: int, field_name: str):
    """Zwraca formularz jednego pola. Wywoływane przez `hx-get` z kliknięcia."""
    client = _get_client(client_id)
    if field_name not in service.EDITABLE_FIELDS:
        abort(404)
    label, _ = service.EDITABLE_FIELDS[field_name]
    return render_template(
        "clients/_field_form.html",
        client=client,
        field_name=field_name,
        label=label,
        value=getattr(client, field_name) or "",
    )


@bp.route("/<int:client_id>/pole/<field_name>", methods=["GET", "PUT"])
def field(client_id: int, field_name: str):
    """GET — anulowanie edycji, PUT — zapis. W obu wypadkach wraca ``<span>``."""
    client = _get_client(client_id)
    if field_name not in service.EDITABLE_FIELDS:
        abort(404)

    error = None
    warning = None

    if request.method == "PUT":
        result = service.update_field(client, field_name, request.form.get("value") or "")
        if result.ok:
            db.session.commit()
            warning = result.warning
        else:
            db.session.rollback()
            error = result.error

    label, _ = service.EDITABLE_FIELDS[field_name]
    return render_template(
        "clients/_field.html",
        client=client,
        field_name=field_name,
        label=label,
        error=error,
        warning=warning,
    )


# ---------------------------------------------------------------------------
# Telefony
# ---------------------------------------------------------------------------


@bp.route("/<int:client_id>/telefony", methods=["POST"])
def phone_add(client_id: int):
    client = _get_client(client_id)
    result = service.add_phone(
        client, request.form.get("phone") or "", request.form.get("label") or None
    )
    if result.ok:
        db.session.commit()
    else:
        db.session.rollback()
    db.session.refresh(client)
    return render_template(
        "clients/_phones.html", client=client, error=result.error, warning=result.warning
    )


@bp.route("/<int:client_id>/telefony/<int:phone_id>", methods=["DELETE"])
def phone_delete(client_id: int, phone_id: int):
    client = _get_client(client_id)
    if service.remove_phone(client, phone_id):
        db.session.commit()
    else:
        db.session.rollback()
    db.session.refresh(client)
    return render_template("clients/_phones.html", client=client)


@bp.route("/<int:client_id>/telefony/<int:phone_id>/glowny", methods=["POST"])
def phone_primary(client_id: int, phone_id: int):
    client = _get_client(client_id)
    if service.set_primary_phone(client, phone_id):
        db.session.commit()
    else:
        db.session.rollback()
    db.session.refresh(client)
    return render_template("clients/_phones.html", client=client)


# ---------------------------------------------------------------------------
# Tagi
# ---------------------------------------------------------------------------


@bp.route("/<int:client_id>/tagi", methods=["POST"])
def tag_add(client_id: int):
    client = _get_client(client_id)
    result = service.add_tag(client, request.form.get("tag") or "")
    if result.ok:
        db.session.commit()
    else:
        db.session.rollback()
    db.session.refresh(client)
    return render_template("clients/_tags.html", client=client, error=result.error)


@bp.route("/<int:client_id>/tagi/<int:tag_id>", methods=["DELETE"])
def tag_delete(client_id: int, tag_id: int):
    client = _get_client(client_id)
    if service.remove_tag(client, tag_id):
        db.session.commit()
    else:
        db.session.rollback()
    db.session.refresh(client)
    return render_template("clients/_tags.html", client=client)


# ---------------------------------------------------------------------------
# Oś czasu: notatki i zdarzenia ręczne
# ---------------------------------------------------------------------------


@bp.route("/<int:client_id>/notatki", methods=["POST"])
def note_add(client_id: int):
    client = _get_client(client_id)
    result = service.add_note(
        client,
        request.form.get("body") or "",
        pinned=request.form.get("pinned") in {"1", "on", "true"},
    )
    if result.ok:
        db.session.commit()
    else:
        db.session.rollback()
    return render_template(
        "clients/_timeline.html",
        client=client,
        timeline=service.timeline(client.id),
        pinned=service.pinned_notes(client.id),
        error=result.error,
    )


@bp.route("/<int:client_id>/zdarzenia", methods=["POST"])
def activity_add(client_id: int):
    client = _get_client(client_id)
    result = service.add_manual_activity(
        client,
        request.form.get("title") or "",
        request.form.get("description") or "",
    )
    if result.ok:
        db.session.commit()
    else:
        db.session.rollback()
    return render_template(
        "clients/_timeline.html",
        client=client,
        timeline=service.timeline(client.id),
        pinned=service.pinned_notes(client.id),
        error=result.error,
    )


# ---------------------------------------------------------------------------
# Status i zgoda SMS
# ---------------------------------------------------------------------------


@bp.route("/<int:client_id>/status", methods=["POST"])
def status_set(client_id: int):
    client = _get_client(client_id)
    if service.set_status(client, request.form.get("status") or ""):
        db.session.commit()
    else:
        db.session.rollback()
    return render_template(
        "clients/_status.html", client=client, statuses=list(ClientStatus)
    )


@bp.route("/<int:client_id>/zgoda-sms", methods=["POST"])
def sms_consent_set(client_id: int):
    client = _get_client(client_id)
    service.set_sms_consent(client, request.form.get("consent") in {"1", "on", "true"})
    db.session.commit()
    return render_template("clients/_consent.html", client=client)


# ---------------------------------------------------------------------------
# Usunięcie
# ---------------------------------------------------------------------------


@bp.route("/<int:client_id>/usun", methods=["POST"])
def delete(client_id: int):
    """Usunięcie klienta wymaga przepisania jego nazwy — sekcja 12 specyfikacji."""
    client = _get_client(client_id)
    confirmation = (request.form.get("confirm") or "").strip()

    if confirmation != client.name:
        flash("Nazwa nie zgadza się z nazwą klienta — nic nie zostało usunięte.", "error")
        return redirect(url_for("clients.detail", client_id=client.id))

    name = client.name
    db.session.delete(client)
    db.session.commit()
    flash(f"Klient „{name}” został usunięty.", "success")
    return redirect(url_for("clients.index"))
