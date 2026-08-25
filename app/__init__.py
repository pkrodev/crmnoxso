"""Fabryka aplikacji NOXSO CRM."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from flask import Flask, render_template, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config, get_config
from app.extensions import csrf, db, limiter, login_manager, migrate, scheduler
from app.filters import register_filters

# Endpointy dostępne bez logowania. Blueprint `api` ma własną autoryzację
# (token po stronie nagłówka, podpis HMAC webhooka), więc też jest tu wymieniony.
PUBLIC_BLUEPRINTS = {"auth", "api"}

# Pliki statyczne aplikacji NIE należą do żadnego blueprintu — `request.blueprint`
# jest dla nich `None`, więc sprawdzenie po nazwie blueprintu ich nie przepuszczało
# i arkusz stylów wracał przekierowaniem na /login. Skutek: ekran logowania
# renderował się bez stylów, jako goły HTML. Dlatego osobny wyjątek po endpoincie.
PUBLIC_ENDPOINTS = {"static"}


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    # Za proxy Railwaya bez tego rate limiting widzi jeden adres IP dla wszystkich.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]

    _init_extensions(app)
    _register_blueprints(app)
    _register_auth_guard(app)
    _register_error_handlers(app)
    _register_context(app)
    register_filters(app)
    _ensure_dirs(app)
    _start_scheduler(app)

    return app


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db, directory="migrations")
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.auth_user import load_user

    login_manager.user_loader(load_user)


def _register_blueprints(app: Flask) -> None:
    from app.blueprints import api, auth, clients, dashboard, imports, transcripts

    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(clients.bp, url_prefix="/clients")
    app.register_blueprint(imports.bp, url_prefix="/import")
    app.register_blueprint(transcripts.bp, url_prefix="/transcripts")
    app.register_blueprint(api.bp, url_prefix="/api")

    # Endpointy maszynowe nie mają formularza ani ciasteczka sesji, którym dałoby
    # się posłużyć w ataku CSRF — autoryzuje je token w nagłówku (a od etapu 7
    # także podpis HMAC webhooka). Bez tego zwolnienia każde żądanie z zewnątrz
    # odbijałoby się od ochrony CSRF.
    csrf.exempt(api.bp)


def _register_auth_guard(app: Flask) -> None:
    """Wymóg logowania na całej aplikacji, zamiast dekoratora na każdym widoku."""

    @app.before_request
    def require_login():  # type: ignore[misc]
        if request.blueprint in PUBLIC_BLUEPRINTS:
            return None
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if request.endpoint is None:
            return None
        if current_user.is_authenticated:
            return None
        return login_manager.unauthorized()


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(_error):  # type: ignore[misc]
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):  # type: ignore[misc]
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_error):  # type: ignore[misc]
        return render_template("errors/413.html"), 413

    @app.errorhandler(429)
    def too_many(error):  # type: ignore[misc]
        return render_template("errors/429.html", error=error), 429

    @app.errorhandler(500)
    def server_error(error):  # type: ignore[misc]
        app.logger.exception("Błąd serwera: %s", error)
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.errorhandler(CSRFError)
    def csrf_error(error):  # type: ignore[misc]
        return render_template("errors/csrf.html", reason=error.description), 400


def _register_context(app: Flask) -> None:
    @app.context_processor
    def inject_globals():  # type: ignore[misc]
        from flask_wtf.csrf import generate_csrf

        from app.models.enums import (
            ACTIVITY_TYPE_LABELS,
            CLIENT_STATUS_LABELS,
            IMPORT_STATUS_LABELS,
            TRANSCRIPT_STATUS_LABELS,
        )

        return {
            "csrf_token_value": generate_csrf(),
            "app_name": "NOXSO CRM",
            "activity_labels": ACTIVITY_TYPE_LABELS,
            "client_status_labels": CLIENT_STATUS_LABELS,
            "transcript_status_labels": TRANSCRIPT_STATUS_LABELS,
            "import_status_labels": IMPORT_STATUS_LABELS,
            # Nawigacja wymienia też ekrany z późniejszych etapów — pokazujemy je
            # wyszarzone, dopóki blueprint nie istnieje, zamiast wywalać się
            # na url_for() nieznanego endpointu.
            "url_map_endpoints": {rule.endpoint for rule in app.url_map.iter_rules()},
        }

    @app.shell_context_processor
    def shell_context():  # type: ignore[misc]
        import app.models as models

        return {"db": db, **{name: getattr(models, name) for name in models.__all__}}


def _ensure_dirs(app: Flask) -> None:
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)


def _start_scheduler(app: Flask) -> None:
    """Uruchomienie APSchedulera w procesie aplikacji.

    Scheduler startuje LENIWIE — przy pierwszym obsłużonym żądaniu, nie przy
    budowie aplikacji. Powód: proces-rodzic reloadera Flaska nie obsługuje
    żądań, więc sam z siebie nigdy nie odpali drugiej kopii zadań, a polecenia
    CLI (``flask db upgrade``) nie wstają z niepotrzebnym schedulerem.

    Wcześniejsza wersja pomijała start, gdy ``DEBUG`` było włączone, a zmienna
    ``WERKZEUG_RUN_MAIN`` nie miała wartości ``"true"``. Tę zmienną ustawia
    wyłącznie reloader, więc serwer deweloperski uruchomiony BEZ przeładowywania
    nie startował schedulera w ogóle. ``enqueue_import`` dokładał wtedy zadanie
    do maszyny, która nie chodzi — import wisiał na statusie „Oczekuje" bez
    jednego wpisu w logu.

    Przy jednym workerze Gunicorna (``--workers 1``, tak jak w Procfile) nie ma
    ryzyka, że zadanie wykona się kilka razy równolegle.
    """
    if not app.config.get("SCHEDULER_ENABLED", True):
        return

    from app.tasks import register_jobs

    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    lock = threading.Lock()

    @app.before_request
    def boot_scheduler():  # type: ignore[misc]
        if scheduler.running:
            return None
        with lock:
            if not scheduler.running:
                register_jobs(app, scheduler)
                scheduler.start()
                app.logger.info("APScheduler wystartował.")
        return None


__all__ = ["Config", "create_app"]
