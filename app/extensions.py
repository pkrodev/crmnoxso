"""Rozszerzenia Flaska — tworzone raz, inicjowane w app factory."""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Wspólna klasa bazowa modeli (styl deklaratywny SQLAlchemy 2.0)."""


db = SQLAlchemy(model_class=Base)
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
scheduler = BackgroundScheduler(timezone="UTC")

login_manager.login_view = "auth.login"
login_manager.login_message = "Zaloguj się, żeby przejść dalej."
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"
