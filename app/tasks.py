"""Zadania w tle (APScheduler).

Scheduler chodzi w procesie aplikacji — przy jednym workerze Gunicorna
(``--workers 1``) nie ma ryzyka zdublowanego wykonania.
"""

from __future__ import annotations

from flask import Flask

_app: Flask | None = None


ANALYSIS_INTERVAL_SECONDS = 30

# Brak klucza do modelu nie jest błędem, tylko stanem konfiguracji — ale wpis
# w logu co trzydzieści sekund zasypałby wszystko inne. Mówimy o tym raz.
_warned_about_ai = False


def register_jobs(app: Flask, scheduler) -> None:
    """Podpina zadania cykliczne. Import jest zadaniem jednorazowym, dokładanym w locie."""
    global _app
    _app = app

    scheduler.add_job(
        _analyse_transcripts,
        trigger="interval",
        seconds=ANALYSIS_INTERVAL_SECONDS,
        args=[app],
        id="analyse-transcripts",
        replace_existing=True,
        # Jedna instancja naraz: analiza porcji rozmów bywa dłuższa niż odstęp
        # między uruchomieniami, a drugi przebieg nie miałby czego wziąć.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=ANALYSIS_INTERVAL_SECONDS,
    )


def _analyse_transcripts(app: Flask) -> None:
    """Cykliczna analiza rozmów oczekujących (etap 5)."""
    global _warned_about_ai
    from app.extensions import db
    from app.services import analysis
    from app.services.ai import AiNotConfigured, get_provider

    with app.app_context():
        try:
            provider = get_provider()
        except AiNotConfigured as exc:
            if not _warned_about_ai:
                app.logger.warning("%s", exc)
                _warned_about_ai = True
            return
        except Exception:
            app.logger.exception("Nie udało się zbudować dostawcy AI")
            return

        _warned_about_ai = False
        try:
            report = analysis.run_pending(provider)
            if report.processed or report.failed:
                app.logger.info("Analiza rozmów: %s", report.as_dict())
        except Exception:
            app.logger.exception("Przebieg analizy rozmów zakończył się błędem")
            db.session.rollback()
        finally:
            db.session.remove()


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
