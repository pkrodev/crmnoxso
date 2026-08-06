"""Logowanie i wylogowanie."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired

from app.auth_user import verify_credentials
from app.extensions import limiter

bp = Blueprint("auth", __name__)


class LoginForm(FlaskForm):
    login = StringField("Login", validators=[DataRequired("Podaj login.")])
    password = PasswordField("Hasło", validators=[DataRequired("Podaj hasło.")])
    remember = BooleanField("Zapamiętaj mnie")


def _safe_next(target: str | None) -> str:
    """Ochrona przed przekierowaniem na obcy adres po zalogowaniu."""
    if not target:
        return url_for("dashboard.index")
    parsed = urlparse(target)
    if parsed.netloc or parsed.scheme:
        return url_for("dashboard.index")
    return target


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    "5 per 15 minutes",
    methods=["POST"],
    error_message="Za dużo prób logowania. Spróbuj ponownie za kwadrans.",
)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = verify_credentials(form.login.data or "", form.password.data or "")
        if user is not None:
            login_user(user, remember=bool(form.remember.data))
            return redirect(_safe_next(request.args.get("next")))
        # Celowo nie zdradzamy, czy błędny był login czy hasło.
        flash("Nieprawidłowy login lub hasło.", "error")

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Wylogowano.", "success")
    return redirect(url_for("auth.login"))
