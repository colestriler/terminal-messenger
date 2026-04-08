from __future__ import annotations

import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List
from unittest.mock import patch

from imsg.contact_resolver import normalize_phone
from imsg.cli import (
    ANSI_BLUE,
    ANSI_CYAN,
    contact_is_unread,
    filter_conversations,
    format_contact_option,
    flush_new_messages,
    handle_input,
    pending_message_key,
    prompt_for_conversation,
    render_message_line,
    transcript_label,
)
from imsg.messages_store import (
    MESSAGE_QUERY_BY_CHAT,
    MESSAGE_QUERY_BY_HANDLE,
    apple_timestamp_to_datetime,
    extract_nsstring_text,
    MessageStore,
    normalize_text,
    row_to_message,
    row_to_contact,
)
from imsg.models import Contact, Message
from imsg.seen_state import SeenState


class FakeStore:
    def __init__(self) -> None:
        self.contacts = [
            Contact(
                handle="+15551234567",
                label="Frida",
                preview="see you soon",
                last_message_at=datetime(2026, 4, 7, 14, 30, tzinfo=timezone.utc),
            ),
            Contact(
                handle="+15557654321",
                label="Mom",
                preview="call me",
                last_message_at=datetime(2026, 4, 7, 14, 25, tzinfo=timezone.utc),
            ),
        ]

    def recent_conversations(self, limit: int = 10) -> List[Contact]:
        return self.contacts[:limit]

    def resolve_contact(self, search_term: str) -> Contact:
        return Contact(handle=search_term, label=search_term)


class FakeMessageStore:
    def __init__(self, messages: List[Message]) -> None:
        self.messages = messages

    def recent_messages(self, contact: Contact, limit: int = 25) -> List[Message]:
        return self.messages[:limit]


class FakeResolver:
    def __init__(self, names: Dict[str, str]) -> None:
        self.names = names

    def lookup(self, handle: str | None) -> str | None:
        if handle is None:
            return None
        return self.names.get(handle)


class RecordingConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.row_factory = None

    def execute(self, query: str, params: tuple[object, ...]):
        self.executed.append((query, params))
        return self

    def fetchall(self) -> list[dict[str, object]]:
        return []

    def __enter__(self) -> "RecordingConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class StoreParsingTests(unittest.TestCase):
    def test_normalize_phone_strips_country_code(self) -> None:
        self.assertEqual(normalize_phone("+1 (555) 123-4567"), "5551234567")

    def test_normalize_text_prefers_plain_text(self) -> None:
        self.assertEqual(normalize_text("hello", b"ignored"), "hello")

    def test_normalize_text_falls_back_to_attributed_body(self) -> None:
        payload = b"\x00\x01Hello from attributed body\x00\x02"
        self.assertEqual(normalize_text("", payload), "Hello from attributed body")

    def test_normalize_text_filters_binary_preview_garbage(self) -> None:
        payload = b"__kIMMessagePartAttributeName $classname NSObject"
        self.assertEqual(normalize_text("", payload), "")

    def test_extract_nsstring_text_reads_archived_message(self) -> None:
        payload = (
            b"\x04\x0bstreamtyped"
            b"NSMutableAttributedString\x00"
            b"NSString\x01\x94\x84\x01+\x1eYeah, that\xe2\x80\x99s always possible"
            b"\x86\x84\x02iI\x01\x1cNSDictionary\x00"
        )
        self.assertEqual(extract_nsstring_text(payload), "Yeah, that’s always possible")

    def test_apple_timestamp_handles_nanoseconds(self) -> None:
        result = apple_timestamp_to_datetime(784_000_000_000_000_000)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertGreaterEqual(result.year, 2024)

    def test_message_dedupe_key_prefers_guid(self) -> None:
        message = Message(
            rowid=42,
            guid="abc",
            text="hey",
            timestamp=apple_timestamp_to_datetime(0),
            is_from_me=True,
        )
        self.assertEqual(message.dedupe_key, ("abc", 0, True, "hey"))

    def test_format_contact_option_includes_preview(self) -> None:
        contact = Contact(
            handle="+15551234567",
            label="Frida",
            preview="see you soon",
            last_message_at=datetime(2026, 4, 7, 14, 30, tzinfo=timezone.utc),
        )
        rendered = format_contact_option(1, contact)
        self.assertIn("1. Frida", rendered)
        self.assertIn("+15551234567", rendered)
        self.assertIn("see you soon", rendered)

    def test_format_contact_option_skips_duplicate_group_handle(self) -> None:
        contact = Contact(
            handle="+15550000001",
            label="+15550000001, +15550000002, +15550000003 +1",
            preview="group hello",
            last_message_at=datetime(2026, 4, 7, 14, 30, tzinfo=timezone.utc),
        )
        rendered = format_contact_option(1, contact)
        self.assertNotIn("(+15550000001)", rendered)

    def test_format_contact_option_marks_unread(self) -> None:
        contact = Contact(handle="+15551234567", label="Frida")
        rendered = format_contact_option(1, contact, unread=True)
        self.assertIn("* Frida", rendered)

    def test_transcript_label_shortens_long_name(self) -> None:
        self.assertEqual(
            transcript_label("Frida Marie Ranghild Schaefer Bastian"),
            "Frida",
        )

    def test_prompt_for_conversation_accepts_number(self) -> None:
        store = FakeStore()
        with patch("builtins.input", return_value="2"):
            selected = prompt_for_conversation(
                store,
                SeenState(path=Path("/tmp/nonexistent-seen-state.json")),
                limit=10,
                interactive_picker=False,
            )
        self.assertEqual(selected.label, "Mom")

    def test_filter_conversations_matches_name_and_preview(self) -> None:
        contacts = [
            Contact(handle="+15551234567", label="Frida", preview="see you soon"),
            Contact(handle="+15557654321", label="Mom", preview="call me"),
        ]
        by_name = filter_conversations(contacts, "frida")
        by_preview = filter_conversations(contacts, "call")
        self.assertEqual([contact.label for contact in by_name], ["Frida"])
        self.assertEqual([contact.label for contact in by_preview], ["Mom"])

    def test_handle_input_list_returns_selected_contact(self) -> None:
        store = FakeStore()
        current = store.contacts[0]
        with patch("imsg.cli.prompt_for_conversation", return_value=store.contacts[1]):
            result = handle_input(
                "/list",
                store,
                current,
                set(),
                Counter(),
                SeenState(path=Path("/tmp/nonexistent-seen-state.json")),
                10,
            )
        self.assertEqual(result.next_contact, store.contacts[1])
        self.assertTrue(result.keep_running)

    def test_handle_input_sends_to_chat_guid_when_available(self) -> None:
        store = FakeMessageStore([])
        contact = Contact(
            handle="+15550000001",
            label="Group Chat",
            chat_identifier="chat123",
            chat_guid="iMessage;+;chat123",
            participant_handles=("+15550000001", "+15550000002", "+15550000003"),
        )
        with patch("imsg.cli.send_message") as send_mock, patch("time.sleep", return_value=None):
            result = handle_input(
                "hello",
                store,
                contact,
                set(),
                Counter(),
                SeenState(path=Path("/tmp/nonexistent-seen-state.json")),
                10,
            )
        self.assertTrue(result.keep_running)
        send_mock.assert_called_once_with(
            "+15550000001",
            "hello",
            participant_handles=("+15550000001", "+15550000002", "+15550000003"),
        )

    def test_row_to_contact_collapses_group_chat(self) -> None:
        row = {
            "participant_handles": "+15550000001,+15550000002,+15550000003,+15550000004",
            "participant_count": 4,
            "chat_identifier": "chat123",
            "display_name": None,
            "service": "iMessage",
            "text": "group hello",
            "attributedBody": None,
            "date": 784_000_000_000_000_000,
            "latest_message_rowid": 99,
            "latest_incoming_rowid": 98,
            "latest_incoming_date": 784_000_000_000_000_000,
            "unread_count": 1,
            "last_read_message_timestamp": 0,
        }
        contact = row_to_contact(row)
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.chat_identifier, "chat123")
        self.assertEqual(contact.handle, "+15550000001")
        self.assertEqual(contact.label, "+15550000001, +15550000002, +15550000003 +1")

    def test_row_to_contact_uses_resolved_contact_name(self) -> None:
        row = {
            "participant_handles": "+15550000001",
            "participant_count": 1,
            "chat_identifier": "chat123",
            "display_name": None,
            "service": "iMessage",
            "text": "hello",
            "attributedBody": None,
            "date": 784_000_000_000_000_000,
            "latest_message_rowid": 99,
            "latest_incoming_rowid": 98,
            "latest_incoming_date": 784_000_000_000_000_000,
            "unread_count": 1,
            "last_read_message_timestamp": 0,
        }
        resolver = FakeResolver({"+15550000001": "Frida"})
        contact = row_to_contact(row, resolver=resolver)
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.label, "Frida")

    def test_render_message_line_uses_colors_for_sender_roles(self) -> None:
        sent = Message(
            rowid=1,
            guid="1",
            text="hello",
            timestamp=apple_timestamp_to_datetime(0),
            is_from_me=True,
        )
        received = Message(
            rowid=2,
            guid="2",
            text="hi",
            timestamp=apple_timestamp_to_datetime(0),
            is_from_me=False,
        )
        sent_line = render_message_line(sent, them_label="Frida Marie Ranghild Schaefer Bastian", use_color=True)
        received_line = render_message_line(received, them_label="Frida Marie Ranghild Schaefer Bastian", use_color=True)
        self.assertIn(ANSI_BLUE, sent_line)
        self.assertIn("you>", sent_line)
        self.assertIn(ANSI_CYAN, received_line)
        self.assertIn("Frida>", received_line)

    def test_render_message_line_prefers_message_sender_label_for_group_chat(self) -> None:
        received = Message(
            rowid=2,
            guid="2",
            text="hi",
            timestamp=apple_timestamp_to_datetime(0),
            is_from_me=False,
            handle="+15551234567",
            sender_label="Madi",
        )
        received_line = render_message_line(received, them_label="Trail Blazzers", use_color=False)
        self.assertIn("Madi>", received_line)
        self.assertNotIn("Trail Blazzers>", received_line)

    def test_row_to_message_resolves_sender_name(self) -> None:
        row = {
            "ROWID": 10,
            "guid": "abc",
            "text": "hello",
            "attributedBody": None,
            "date": 784_000_000_000_000_000,
            "is_from_me": 0,
            "handle_id": "+15550000001",
            "service": "iMessage",
            "chat_identifier": "chat123",
        }
        resolver = FakeResolver({"+15550000001": "Frida"})
        message = row_to_message(row, resolver=resolver)
        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message.sender_label, "Frida")

    def test_recent_messages_prefers_chat_scope_over_handle_scope(self) -> None:
        store = MessageStore()
        store.contact_resolver = FakeResolver({})
        connection = RecordingConnection()
        contact = Contact(
            handle="+15551234567",
            label="Frida",
            chat_identifier="chat-group-123",
        )
        with patch.object(store, "_connect", return_value=connection):
            store.recent_messages(contact, limit=10)
        self.assertEqual(connection.executed, [(MESSAGE_QUERY_BY_CHAT, ("chat-group-123", 10))])

    def test_recent_messages_falls_back_to_handle_scope_without_chat_identifier(self) -> None:
        store = MessageStore()
        store.contact_resolver = FakeResolver({})
        connection = RecordingConnection()
        contact = Contact(
            handle="+15551234567",
            label="Frida",
            chat_identifier=None,
        )
        with patch.object(store, "_connect", return_value=connection):
            store.recent_messages(contact, limit=10)
        self.assertEqual(connection.executed, [(MESSAGE_QUERY_BY_HANDLE, ("+15551234567", 10))])

    def test_flush_new_messages_skips_db_echo_for_optimistic_send(self) -> None:
        contact = Contact(handle="+15551234567", label="Frida")
        message = Message(
            rowid=10,
            guid="10",
            text="test",
            timestamp=apple_timestamp_to_datetime(0),
            is_from_me=True,
        )
        store = FakeMessageStore([message])
        seen = set()
        pending = Counter({pending_message_key("test"): 1})
        fresh = flush_new_messages(
            store,
            contact,
            seen,
            pending,
            SeenState(path=Path("/tmp/nonexistent-seen-state.json")),
            10,
            "you",
            "Frida",
        )
        self.assertEqual(fresh, [])
        self.assertEqual(pending, Counter())
        self.assertIn(message.dedupe_key, seen)

    def test_pending_message_key_normalizes_whitespace(self) -> None:
        self.assertEqual(
            pending_message_key("hello   world\nagain"),
            "hello world again",
        )

    def test_contact_is_unread_uses_db_state(self) -> None:
        contact = Contact(
            handle="+15551234567",
            label="Frida",
            latest_incoming_rowid=10,
            unread_count=1,
            latest_incoming_at=datetime(2026, 4, 7, 15, 0, tzinfo=timezone.utc),
            last_read_message_timestamp=datetime(2026, 4, 7, 14, 0, tzinfo=timezone.utc),
        )
        seen_state = SeenState(path=Path("/tmp/nonexistent-seen-state.json"))
        self.assertTrue(contact_is_unread(contact, seen_state))

    def test_contact_is_unread_respects_local_seen_override(self) -> None:
        with TemporaryDirectory() as temp_dir:
            seen_state = SeenState(path=Path(temp_dir) / "seen.json")
            contact = Contact(
                handle="+15551234567",
                label="Frida",
                latest_incoming_rowid=10,
                unread_count=1,
                latest_incoming_at=datetime(2026, 4, 7, 15, 0, tzinfo=timezone.utc),
                last_read_message_timestamp=datetime(2026, 4, 7, 14, 0, tzinfo=timezone.utc),
            )
            seen_state.mark_contact_seen(contact)
            self.assertFalse(contact_is_unread(contact, seen_state))


if __name__ == "__main__":
    unittest.main()

