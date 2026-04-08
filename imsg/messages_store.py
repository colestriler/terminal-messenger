from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from imsg.contact_resolver import ContactResolver
from imsg.models import Contact, Message


APPLE_EPOCH = 978307200

MESSAGE_QUERY = """
SELECT
  message.ROWID,
  message.guid,
  message.text,
  message.attributedBody,
  message.date,
  message.is_from_me,
  handle.id AS handle_id,
  handle.service,
  chat.chat_identifier
FROM message
LEFT JOIN handle
  ON handle.ROWID = message.handle_id
LEFT JOIN chat_message_join
  ON chat_message_join.message_id = message.ROWID
LEFT JOIN chat
  ON chat.ROWID = chat_message_join.chat_id
WHERE (
  LOWER(COALESCE(handle.id, '')) = LOWER(?)
  OR LOWER(COALESCE(chat.chat_identifier, '')) = LOWER(?)
)
ORDER BY message.date DESC, message.ROWID DESC
LIMIT ?
"""

CONTACT_QUERY = """
SELECT
  handle.id AS handle_id,
  handle.service,
  chat.guid AS chat_guid,
  chat.chat_identifier,
  chat.display_name,
  MAX(message.date) AS last_message_date
FROM handle
LEFT JOIN chat_handle_join
  ON chat_handle_join.handle_id = handle.ROWID
LEFT JOIN chat
  ON chat.ROWID = chat_handle_join.chat_id
LEFT JOIN chat_message_join
  ON chat_message_join.chat_id = chat.ROWID
LEFT JOIN message
  ON message.ROWID = chat_message_join.message_id
WHERE (
  LOWER(COALESCE(handle.id, '')) LIKE LOWER(?)
  OR LOWER(COALESCE(chat.chat_identifier, '')) LIKE LOWER(?)
  OR LOWER(COALESCE(chat.display_name, '')) LIKE LOWER(?)
)
GROUP BY handle.id, handle.service, chat.guid, chat.chat_identifier, chat.display_name
ORDER BY last_message_date DESC
LIMIT 5
"""

RECENT_CHATS_QUERY = """
SELECT
  chat.ROWID AS chat_rowid,
  chat.guid AS chat_guid,
  chat.chat_identifier,
  chat.display_name,
  chat.last_read_message_timestamp,
  GROUP_CONCAT(DISTINCT handle.id) AS participant_handles,
  COUNT(DISTINCT handle.id) AS participant_count,
  MAX(handle.service) AS service,
  latest_message.ROWID AS latest_message_rowid,
  latest_message.text,
  latest_message.attributedBody,
  latest_message.date,
  (
    SELECT MAX(m2.ROWID)
    FROM chat_message_join AS cmj2
    JOIN message AS m2
      ON m2.ROWID = cmj2.message_id
    WHERE cmj2.chat_id = chat.ROWID
      AND m2.is_from_me = 0
  ) AS latest_incoming_rowid,
  (
    SELECT MAX(m2.date)
    FROM chat_message_join AS cmj2
    JOIN message AS m2
      ON m2.ROWID = cmj2.message_id
    WHERE cmj2.chat_id = chat.ROWID
      AND m2.is_from_me = 0
  ) AS latest_incoming_date,
  (
    SELECT COUNT(*)
    FROM chat_message_join AS cmj3
    JOIN message AS m3
      ON m3.ROWID = cmj3.message_id
    WHERE cmj3.chat_id = chat.ROWID
      AND m3.is_from_me = 0
      AND m3.is_read = 0
  ) AS unread_count
FROM chat
LEFT JOIN chat_handle_join
  ON chat_handle_join.chat_id = chat.ROWID
LEFT JOIN handle
  ON handle.ROWID = chat_handle_join.handle_id
LEFT JOIN chat_message_join AS latest_join
  ON latest_join.chat_id = chat.ROWID
LEFT JOIN message AS latest_message
  ON latest_message.ROWID = latest_join.message_id
WHERE latest_message.ROWID = (
  SELECT cmj.message_id
  FROM chat_message_join AS cmj
  JOIN message AS m
    ON m.ROWID = cmj.message_id
  WHERE cmj.chat_id = chat.ROWID
  ORDER BY m.date DESC, m.ROWID DESC
  LIMIT 1
)
GROUP BY
    chat.ROWID,
    chat.guid,
  chat.chat_identifier,
  chat.display_name,
  latest_message.text,
  latest_message.attributedBody,
  latest_message.date
ORDER BY latest_message.date DESC
LIMIT ?
"""


class MessageStoreError(RuntimeError):
    """Raised when the local Messages store cannot be queried."""


def default_db_path() -> Path:
    return Path.home() / "Library" / "Messages" / "chat.db"


def open_readonly_connection(db_path: Path | None = None) -> sqlite3.Connection:
    target = db_path or default_db_path()
    try:
        return sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        raise MessageStoreError(
            "Could not open the local Messages database.\n"
            "Grant Full Disk Access to your terminal app and Python, then fully restart the terminal.\n"
            "Open: System Settings > Privacy & Security > Full Disk Access"
        ) from exc


def decode_attributed_body(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()

    extracted = extract_nsstring_text(value)
    if extracted:
        return extracted

    try:
        decoded = value.decode("utf-8", errors="ignore")
    except Exception:
        return ""

    matches = re.findall(r"[\x20-\x7E][\x20-\x7E\n\r\t]{0,512}", decoded)
    if not matches:
        return ""

    candidate = max(matches, key=len)
    normalized = " ".join(candidate.split()).strip()
    if _looks_like_binary_preview(normalized):
        return ""
    return normalized


def extract_nsstring_text(value: bytes) -> str:
    marker = b"NSString"
    candidates: list[str] = []
    start = 0

    while True:
        index = value.find(marker, start)
        if index == -1:
            break

        plus_index = value.find(b"+", index, min(len(value), index + 64))
        if plus_index != -1 and plus_index + 1 < len(value):
            length = value[plus_index + 1]
            text_start = plus_index + 2
            text_end = text_start + length
            if 0 < length <= 160 and text_end <= len(value):
                chunk = value[text_start:text_end]
                try:
                    decoded = chunk.decode("utf-8", errors="strict").strip()
                except UnicodeDecodeError:
                    decoded = ""
                if decoded and not _looks_like_binary_preview(decoded):
                    candidates.append(decoded)

        start = index + len(marker)

    if not candidates:
        return ""
    return max(candidates, key=len)


def _looks_like_binary_preview(value: str) -> bool:
    lowered = value.lower()
    markers = (
        "__kimmessagepartattributename",
        "$classname",
        "nsobject",
        "nsvalue",
        "NSNumber".lower(),
    )
    return any(marker in lowered for marker in markers)


def normalize_text(text: str | None, attributed_body: bytes | str | None) -> str:
    direct = (text or "").strip()
    if direct:
        return direct
    return decode_attributed_body(attributed_body)


def apple_timestamp_to_datetime(raw_value: int | float | None) -> datetime:
    if raw_value in (None, 0):
        return datetime.fromtimestamp(APPLE_EPOCH, tz=timezone.utc)

    value = float(raw_value)
    abs_value = abs(value)
    if abs_value > 10_000_000_000:
        value /= 1_000_000_000
    elif abs_value > 10_000_000:
        value /= 1_000_000

    return datetime.fromtimestamp(value + APPLE_EPOCH, tz=timezone.utc)


def row_to_message(row: sqlite3.Row) -> Message | None:
    text = normalize_text(row["text"], row["attributedBody"])
    if not text:
        return None

    return Message(
        rowid=int(row["ROWID"]),
        guid=row["guid"],
        text=text,
        timestamp=apple_timestamp_to_datetime(row["date"]),
        is_from_me=bool(row["is_from_me"]),
        handle=row["handle_id"],
        chat_identifier=row["chat_identifier"],
        service=row["service"],
    )


def _participant_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.split(",") if item]


def _row_value(row: sqlite3.Row | dict[str, object], key: str) -> object:
    if isinstance(row, dict):
        return row.get(key)
    return row[key]


def row_to_contact(row: sqlite3.Row, resolver: ContactResolver | None = None) -> Contact | None:
    participant_handles = _participant_list(_row_value(row, "participant_handles"))
    participant_count = int(_row_value(row, "participant_count") or 0)
    chat_identifier = _row_value(row, "chat_identifier")
    chat_guid = _row_value(row, "chat_guid")

    if not participant_handles and not chat_identifier:
        return None

    preview = normalize_text(_row_value(row, "text"), _row_value(row, "attributedBody")) or None
    last_message_at = apple_timestamp_to_datetime(_row_value(row, "date"))
    latest_incoming_at = (
        apple_timestamp_to_datetime(_row_value(row, "latest_incoming_date"))
        if _row_value(row, "latest_incoming_date") not in (None, 0)
        else None
    )
    last_read_message_timestamp = (
        apple_timestamp_to_datetime(_row_value(row, "last_read_message_timestamp"))
        if _row_value(row, "last_read_message_timestamp") not in (None, 0)
        else None
    )
    participant_labels = [
        resolver.lookup(handle) if resolver else None
        for handle in participant_handles
    ]
    rendered_participants = [
        label or handle for handle, label in zip(participant_handles, participant_labels)
    ]

    if _row_value(row, "display_name"):
        label = _row_value(row, "display_name")
    elif participant_count > 1:
        label = ", ".join(rendered_participants[:3])
        if participant_count > 3:
            label = f"{label} +{participant_count - 3}"
    else:
        label = rendered_participants[0] if rendered_participants else chat_identifier

    handle = participant_handles[0] if participant_handles else chat_identifier or ""
    return Contact(
        handle=handle,
        label=label or "Unknown chat",
        chat_identifier=chat_identifier,
        chat_guid=chat_guid,
        participant_handles=tuple(participant_handles),
        service=_row_value(row, "service"),
        preview=preview,
        last_message_at=last_message_at,
        last_message_rowid=_row_value(row, "latest_message_rowid"),
        latest_incoming_rowid=_row_value(row, "latest_incoming_rowid"),
        latest_incoming_at=latest_incoming_at,
        unread_count=int(_row_value(row, "unread_count") or 0),
        last_read_message_timestamp=last_read_message_timestamp,
    )


class MessageStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self.contact_resolver = ContactResolver()

    def _connect(self) -> sqlite3.Connection:
        connection = open_readonly_connection(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def resolve_contact(self, search_term: str) -> Contact:
        if not search_term:
            raise MessageStoreError("Contact value cannot be empty.")

        with self._connect() as connection:
            rows = connection.execute(
                CONTACT_QUERY,
                tuple(f"%{search_term}%" for _ in range(3)),
            ).fetchall()

        if not rows:
            return Contact(handle=search_term, label=search_term)

        exact_matches = [
            row for row in rows
            if search_term.lower()
            in {
                (row["handle_id"] or "").lower(),
                (row["chat_identifier"] or "").lower(),
                (row["display_name"] or "").lower(),
            }
        ]
        row = exact_matches[0] if exact_matches else rows[0]
        label = row["display_name"] or row["chat_identifier"] or row["handle_id"] or search_term
        return Contact(
            handle=row["handle_id"] or search_term,
            label=label,
            chat_identifier=row["chat_identifier"],
            chat_guid=row["chat_guid"],
            participant_handles=((row["handle_id"],) if row["handle_id"] else ()),
            service=row["service"],
        )

    def recent_messages(self, contact: Contact, limit: int = 25) -> list[Message]:
        with self._connect() as connection:
            rows = connection.execute(
                MESSAGE_QUERY,
                (
                    contact.handle,
                    contact.chat_identifier or contact.handle,
                    limit,
                ),
            ).fetchall()

        messages = [message for row in rows if (message := row_to_message(row))]
        messages.sort(key=lambda message: (message.timestamp, message.rowid))
        return messages

    def recent_conversations(self, limit: int = 10) -> list[Contact]:
        with self._connect() as connection:
            rows = connection.execute(RECENT_CHATS_QUERY, (limit,)).fetchall()

        conversations: list[Contact] = []
        for row in rows:
            if contact := row_to_contact(row, resolver=self.contact_resolver):
                conversations.append(contact)

        return conversations

