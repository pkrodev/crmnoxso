"""Modele SQLAlchemy.

Import wszystkich modeli w jednym miejscu — Alembic wykrywa tabele dopiero wtedy,
gdy odpowiadające im klasy zostały zaimportowane.
"""

from app.models.activity import Activity
from app.models.calendar_event import CalendarEvent
from app.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.models.client import (
    SYSTEM_TAGS,
    TAG_FROM_TRANSCRIPT,
    TAG_NEEDS_REVIEW,
    TAG_POSSIBLE_DUPLICATE,
    Client,
    Phone,
    Tag,
    client_tags,
)
from app.models.enums import (
    ActivityActor,
    ActivityType,
    BatchStatus,
    CampaignStatus,
    ClientSource,
    ClientStatus,
    EventSource,
    ImportStatus,
    RecipientStatus,
    TranscriptStatus,
)
from app.models.import_job import ImportJob
from app.models.note import Note
from app.models.transcript import Transcript

__all__ = [
    "SYSTEM_TAGS",
    "TAG_FROM_TRANSCRIPT",
    "TAG_NEEDS_REVIEW",
    "TAG_POSSIBLE_DUPLICATE",
    "Activity",
    "ActivityActor",
    "ActivityType",
    "BatchStatus",
    "CalendarEvent",
    "Campaign",
    "CampaignBatch",
    "CampaignRecipient",
    "CampaignStatus",
    "Client",
    "ClientSource",
    "ClientStatus",
    "EventSource",
    "ImportJob",
    "ImportStatus",
    "Note",
    "Phone",
    "RecipientStatus",
    "Tag",
    "Transcript",
    "TranscriptStatus",
    "client_tags",
]
