"""Pulpit — liczniki i ostatnie zdarzenia."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from flask import Blueprint, render_template

from app.extensions import db
from app.models import (
    Activity,
    CalendarEvent,
    Campaign,
    Client,
    ClientStatus,
    Transcript,
    TranscriptStatus,
)

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_clients = db.session.scalar(sa.select(sa.func.count()).select_from(Client))
    new_this_month = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(Client)
        .where(Client.created_at >= month_start)
    )
    blacklisted = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(Client)
        .where(Client.status == ClientStatus.BLACKLIST)
    )
    to_review = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(Transcript)
        .where(
            Transcript.status.in_(
                [TranscriptStatus.NEEDS_REVIEW, TranscriptStatus.FAILED]
            )
        )
    )
    upcoming = db.session.scalars(
        sa.select(CalendarEvent)
        .where(
            CalendarEvent.starts_at >= now,
            CalendarEvent.starts_at < now + timedelta(days=7),
        )
        .order_by(CalendarEvent.starts_at)
        .limit(10)
    ).all()
    last_campaign = db.session.scalar(
        sa.select(Campaign).order_by(Campaign.created_at.desc()).limit(1)
    )
    recent = db.session.scalars(
        sa.select(Activity).order_by(Activity.occurred_at.desc()).limit(20)
    ).all()

    return render_template(
        "dashboard/index.html",
        total_clients=total_clients or 0,
        new_this_month=new_this_month or 0,
        blacklisted=blacklisted or 0,
        to_review=to_review or 0,
        upcoming=upcoming,
        upcoming_count=len(upcoming),
        last_campaign=last_campaign,
        recent=recent,
    )
