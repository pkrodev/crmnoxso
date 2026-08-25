"""Ekran importu arkusza."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import ImportJob, ImportStatus
from app.services.importer import ImportError_, build_preview
from app.tasks import enqueue_import

bp = Blueprint("imports", __name__)

ALLOWED = {"ods", "xlsx", "xlsm"}


class UploadForm(FlaskForm):
    file = FileField(
        "Plik z bazą klientów",
        validators=[
            FileRequired("Wybierz plik."),
            FileAllowed(sorted(ALLOWED), "Dozwolone formaty: .ods, .xlsx"),
        ],
    )


@bp.route("/", methods=["GET", "POST"])
def index():
    form = UploadForm()

    if form.validate_on_submit():
        upload = form.file.data
        original = secure_filename(upload.filename or "arkusz")
        suffix = Path(original).suffix.lower()

        upload.stream.seek(0, 2)
        size = upload.stream.tell()
        upload.stream.seek(0)
        limit = current_app.config["IMPORT_MAX_BYTES"]
        if size > limit:
            flash(
                f"Plik ma {size / 1048576:.1f} MB, limit to {limit // 1048576} MB.",
                "error",
            )
            return redirect(url_for("imports.index"))

        stored = Path(current_app.config["UPLOAD_DIR"]) / f"{uuid.uuid4().hex}{suffix}"
        upload.save(stored)

        job = ImportJob(
            filename=original, stored_path=str(stored), status=ImportStatus.PENDING
        )
        db.session.add(job)
        db.session.commit()
        return redirect(url_for("imports.preview", job_id=job.id))

    recent = db.session.scalars(
        sa.select(ImportJob).order_by(ImportJob.created_at.desc()).limit(10)
    ).all()
    return render_template("imports/index.html", form=form, recent=recent)


@bp.route("/<int:job_id>/podglad")
def preview(job_id: int):
    job = db.session.get(ImportJob, job_id)
    if job is None:
        abort(404)

    if job.status != ImportStatus.PENDING:
        return redirect(url_for("imports.progress", job_id=job.id))

    try:
        data = build_preview(job.stored_path)
    except ImportError_ as exc:
        job.status = ImportStatus.FAILED
        job.error = str(exc)
        job.finished_at = datetime.now(UTC)
        db.session.commit()
        flash(str(exc), "error")
        return redirect(url_for("imports.index"))

    return render_template("imports/preview.html", job=job, preview=data)


@bp.route("/<int:job_id>/start", methods=["POST"])
def start(job_id: int):
    job = db.session.get(ImportJob, job_id)
    if job is None:
        abort(404)
    if job.status != ImportStatus.PENDING:
        flash("Ten import został już uruchomiony.", "warning")
        return redirect(url_for("imports.progress", job_id=job.id))

    enqueue_import(current_app._get_current_object(), job.id)  # type: ignore[attr-defined]
    return redirect(url_for("imports.progress", job_id=job.id))


@bp.route("/<int:job_id>")
def progress(job_id: int):
    job = db.session.get(ImportJob, job_id)
    if job is None:
        abort(404)
    return render_template("imports/progress.html", job=job)


@bp.route("/<int:job_id>/status")
def status(job_id: int):
    """Fragment odpytywany przez HTMX co 2 sekundy."""
    job = db.session.get(ImportJob, job_id)
    if job is None:
        abort(404)
    db.session.refresh(job)
    return render_template("imports/_status.html", job=job)
