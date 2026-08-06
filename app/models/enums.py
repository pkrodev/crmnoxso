"""Wyliczenia używane w modelach.

Wszystkie zapisywane w bazie jako VARCHAR z ograniczeniem CHECK
(``native_enum=False``) — dołożenie nowej wartości nie wymaga wtedy ``ALTER TYPE``,
tylko zwykłej migracji ograniczenia.
"""

from __future__ import annotations

import enum


class ClientSource(str, enum.Enum):
    IMPORT = "IMPORT"
    MANUAL = "MANUAL"
    TRANSCRIPT = "TRANSCRIPT"


class ClientStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLACKLIST = "BLACKLIST"


class ActivityType(str, enum.Enum):
    CLIENT_CREATED = "CLIENT_CREATED"
    CLIENT_UPDATED = "CLIENT_UPDATED"
    NOTE_ADDED = "NOTE_ADDED"
    SMS_SENT = "SMS_SENT"
    SMS_DELIVERED = "SMS_DELIVERED"
    SMS_FAILED = "SMS_FAILED"
    CALL_TRANSCRIBED = "CALL_TRANSCRIBED"
    EVENT_SCHEDULED = "EVENT_SCHEDULED"
    TAG_ADDED = "TAG_ADDED"
    TAG_REMOVED = "TAG_REMOVED"
    MANUAL = "MANUAL"


class ActivityActor(str, enum.Enum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    AI = "AI"


class TranscriptStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EventSource(str, enum.Enum):
    MANUAL = "MANUAL"
    AI = "AI"


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    TESTED = "TESTED"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    SENT = "SENT"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class BatchStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RecipientStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ImportStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


# Etykiety po polsku do wyświetlania w interfejsie
CLIENT_STATUS_LABELS = {
    ClientStatus.ACTIVE: "Aktywny",
    ClientStatus.INACTIVE: "Nieaktywny",
    ClientStatus.BLACKLIST: "Czarna lista",
}

CLIENT_SOURCE_LABELS = {
    ClientSource.IMPORT: "Import",
    ClientSource.MANUAL: "Dodany ręcznie",
    ClientSource.TRANSCRIPT: "Z rozmowy",
}

ACTIVITY_TYPE_LABELS = {
    ActivityType.CLIENT_CREATED: "Klient dodany",
    ActivityType.CLIENT_UPDATED: "Dane zaktualizowane",
    ActivityType.NOTE_ADDED: "Notatka",
    ActivityType.SMS_SENT: "SMS wysłany",
    ActivityType.SMS_DELIVERED: "SMS doręczony",
    ActivityType.SMS_FAILED: "SMS nieudany",
    ActivityType.CALL_TRANSCRIBED: "Rozmowa",
    ActivityType.EVENT_SCHEDULED: "Wydarzenie",
    ActivityType.TAG_ADDED: "Tag dodany",
    ActivityType.TAG_REMOVED: "Tag usunięty",
    ActivityType.MANUAL: "Akcja ręczna",
}

TRANSCRIPT_STATUS_LABELS = {
    TranscriptStatus.PENDING: "Oczekuje",
    TranscriptStatus.PROCESSING: "Przetwarzanie",
    TranscriptStatus.DONE: "Gotowe",
    TranscriptStatus.FAILED: "Błąd",
    TranscriptStatus.NEEDS_REVIEW: "Wymaga uwagi",
}

IMPORT_STATUS_LABELS = {
    ImportStatus.PENDING: "Oczekuje",
    ImportStatus.RUNNING: "W toku",
    ImportStatus.DONE: "Zakończony",
    ImportStatus.FAILED: "Błąd",
}
