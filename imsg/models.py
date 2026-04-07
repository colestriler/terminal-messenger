from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Contact:
    handle: str
    label: str
    chat_identifier: str | None = None
    service: str | None = None
    preview: str | None = None
    last_message_at: datetime | None = None


@dataclass(frozen=True)
class Message:
    rowid: int
    guid: str | None
    text: str
    timestamp: datetime
    is_from_me: bool
    handle: str | None = None
    chat_identifier: str | None = None
    service: str | None = None

    @property
    def dedupe_key(self) -> tuple[str | None, int, bool, str]:
        if self.guid:
            return (self.guid, 0, self.is_from_me, self.text)
        return (None, self.rowid, self.is_from_me, self.text)

    @property
    def time_label(self) -> str:
        return self.timestamp.astimezone().strftime("%H:%M")

