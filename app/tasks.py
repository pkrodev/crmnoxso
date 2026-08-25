"""Zadania w tle (APScheduler).

Scheduler chodzi w procesie aplikacji — przy jednym workerze Gunicorna
(``--workers 1``) nie ma ryzyka zdublowanego wykonania.
"""

from __future__ import annotations

from flask import Flask

_app: Flask | None = None


def register_jobs(app: Flask, scheduler) -> None:
    """Podpina zadania cykliczne. Import jest zadaniem jednorazowym, dokładanym w locie."""
    global _app
    _app = app
    # Etap 5 dołoży tu cykliczne przetwarzanie transkrypcji (co 30 sekund).


def enqueue_import(app: Flask, job_id: int) -> None:
    """Uruchamia import w tle.

    2000 wierszy nie zmieści się w limicie czasu żądania HTTP, więc widok tylko
    zakłada zadanie, a postęp pokazuje odpytywaniem przez HTMX.
    """
    from app.extensions import scheduler

    scheduler.add_job(
        _run_import_job,
        args=[app, job_id],
        id=f"import-{job_id}",
        replace_existing=True,
        misfire_grace_time=None,
    )


def _run_import_job(app: Flask, job_id: int) -> None:
    from app.extensions import db
    from app.services.importer import run_import

    with app.app_context():
        try:
            run_import(job_id)
        except Exception:
            app.logger.exception("Import %s zakończył się błędem", job_id)
        finally:
            db.session.remove()
