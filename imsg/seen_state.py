from __future__ import annotations

import json
from pathlib import Path

from imsg.models import Contact, Message


def default_seen_state_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "terminal-messenger" / "seen-state.json"


class SeenState:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_seen_state_path()
        self._seen_by_chat = self._load()

    def _load(self) -> dict[str, int]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, int):
                result[key] = value
        return result

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._seen_by_chat, indent=2, sort_keys=True))
        except OSError:
            return

    def chat_key(self, contact: Contact) -> str | None:
        return contact.chat_identifier or contact.handle or None

    def seen_incoming_rowid(self, contact: Contact) -> int:
        key = self.chat_key(contact)
        if key is None:
            return 0
        return self._seen_by_chat.get(key, 0)

    def mark_contact_seen(self, contact: Contact) -> None:
        key = self.chat_key(contact)
        if key is None:
            return
        latest = contact.latest_incoming_rowid or 0
        if latest <= 0:
            return
        if latest > self._seen_by_chat.get(key, 0):
            self._seen_by_chat[key] = latest
            self.save()

    def mark_message_seen(self, contact: Contact, message: Message) -> None:
        if message.is_from_me:
            return
        key = self.chat_key(contact)
        if key is None:
            return
        if message.rowid > self._seen_by_chat.get(key, 0):
            self._seen_by_chat[key] = message.rowid
            self.save()

