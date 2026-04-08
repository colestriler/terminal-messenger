from __future__ import annotations

import argparse
import curses
import os
import sys
import threading
import time
from collections.abc import Iterable
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from imsg.messages_applescript import MessageSendError, send_message
from imsg.messages_store import MessageStore, MessageStoreError
from imsg.models import Contact, Message
from imsg.seen_state import SeenState


DEFAULT_CHAT_LIST_LIMIT = 250
DEFAULT_HISTORY_LIMIT = 100
ANSI_RESET = "\033[0m"
ANSI_DIM = "\033[2m"
ANSI_BLUE = "\033[38;5;39m"
ANSI_CYAN = "\033[38;5;45m"
ANSI_BOLD = "\033[1m"
PICKER_REFRESH_MS = 1200


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmsg",
        description="Open an interactive iMessage session in your terminal.",
    )
    parser.add_argument("contact", nargs="?", help="Phone number, email, or known chat label.")
    parser.add_argument("--contact", dest="contact_flag", help="Explicit contact handle.")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between inbox refreshes.",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=DEFAULT_HISTORY_LIMIT,
        help="How many recent messages to show on startup and refreshes.",
    )
    parser.add_argument(
        "--list-chats",
        action="store_true",
        help="List recent conversations and exit.",
    )
    return parser


def prompt_for_contact() -> str:
    while True:
        value = input("contact> ").strip()
        if value:
            return value


def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colorize(text: str, *styles: str, enabled: bool = True) -> str:
    if not enabled or not styles:
        return text
    return "".join(styles) + text + ANSI_RESET


def transcript_label(label: str) -> str:
    cleaned = " ".join(label.split())
    if len(cleaned) <= 18:
        return cleaned
    if "," not in cleaned and " " in cleaned:
        return cleaned.split()[0]
    return truncate_line(cleaned, 18)


def render_message_line(
    message: Message,
    you_label: str = "you",
    them_label: str = "them",
    use_color: bool = False,
) -> str:
    speaker = you_label if message.is_from_me else transcript_label(message.sender_label or them_label)
    timestamp = colorize(f"[{message.time_label}]", ANSI_DIM, enabled=use_color)
    speaker_text = f"{speaker}>"
    if message.is_from_me:
        speaker_text = colorize(speaker_text, ANSI_BLUE, ANSI_BOLD, enabled=use_color)
        message_text = colorize(message.text, ANSI_BLUE, enabled=use_color)
    else:
        speaker_text = colorize(speaker_text, ANSI_CYAN, ANSI_BOLD, enabled=use_color)
        message_text = message.text
    return f"{timestamp} {speaker_text} {message_text}"


def print_message(message: Message, you_label: str = "you", them_label: str = "them") -> None:
    print(render_message_line(message, you_label=you_label, them_label=them_label, use_color=supports_color()))


def print_history(messages: Iterable[Message], you_label: str, them_label: str) -> None:
    for message in messages:
        print_message(message, you_label=you_label, them_label=them_label)


def now_label() -> str:
    return datetime.now().astimezone().strftime("%H:%M")


def pending_message_key(text: str) -> str:
    return " ".join(text.split())


def clear_previous_input_line() -> None:
    if not sys.stdout.isatty():
        return
    sys.stdout.write("\033[1A\033[2K\r")
    sys.stdout.flush()


def conversation_key(contact: Contact) -> str:
    return contact.chat_identifier or contact.handle


def contact_is_unread(contact: Contact, seen_state: SeenState | None) -> bool:
    latest_incoming_rowid = contact.latest_incoming_rowid or 0
    if latest_incoming_rowid <= 0:
        return False

    local_seen = seen_state.seen_incoming_rowid(contact) if seen_state else 0
    if local_seen >= latest_incoming_rowid:
        return False
    if contact.unread_count > 0:
        return True
    if contact.latest_incoming_at is None:
        return False
    if contact.last_read_message_timestamp is None:
        return True
    return contact.latest_incoming_at > contact.last_read_message_timestamp


def format_contact_option(index: int, contact: Contact, unread: bool = False) -> str:
    unread_prefix = "* " if unread else ""
    parts = [f"{index}. {unread_prefix}{contact.label}"]
    if contact.handle and contact.handle != contact.label and "," not in contact.label:
        parts.append(f"({contact.handle})")
    if contact.last_message_at:
        parts.append(f"[{contact.last_message_at.astimezone().strftime('%H:%M')}]")
    line = " ".join(parts)
    if contact.preview:
        preview = " ".join(contact.preview.split())
        if len(preview) > 140:
            preview = f"{preview[:137]}..."
        line = f"{line} - {preview}"
    return line


def print_conversation_list(conversations: list[Contact], seen_state: SeenState | None = None) -> None:
    if not conversations:
        print("No recent conversations found.")
        return

    for index, contact in enumerate(conversations, start=1):
        print(format_contact_option(index, contact, unread=contact_is_unread(contact, seen_state)))


def truncate_line(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def contact_search_blob(contact: Contact) -> str:
    parts = [contact.label, contact.handle or "", contact.chat_identifier or "", contact.preview or ""]
    return " ".join(parts).lower()


def filter_conversations(conversations: list[Contact], query: str) -> list[Contact]:
    normalized = " ".join(query.lower().split())
    if not normalized:
        return conversations
    return [contact for contact in conversations if normalized in contact_search_blob(contact)]


def select_conversation_with_arrows(
    store: MessageStore,
    seen_state: SeenState,
    limit: int,
) -> Contact | None:
    def run_picker(stdscr: curses.window) -> Contact | None:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.timeout(PICKER_REFRESH_MS)
        selected_index = 0
        scroll_offset = 0
        query = ""
        selected_key: str | None = None
        conversations = store.recent_conversations(limit=limit)

        while True:
            if not conversations:
                return None

            stdscr.erase()
            height, width = stdscr.getmaxyx()
            filtered = filter_conversations(conversations, query)
            if filtered:
                selected_index = min(selected_index, len(filtered) - 1)
            else:
                selected_index = 0
            if selected_key is not None:
                for idx, contact in enumerate(filtered):
                    if conversation_key(contact) == selected_key:
                        selected_index = idx
                        break
            visible_count = max(1, height - 3)
            header = "Select a chat (type to search, Up/Down move, Enter open, Esc cancel)"
            stdscr.addnstr(0, 0, truncate_line(header, width - 1), max(0, width - 1))
            search_line = f"Search: {query}" if query else "Search: "
            stdscr.addnstr(1, 0, truncate_line(search_line, width - 1), max(0, width - 1))

            if not filtered:
                selected_index = 0
                scroll_offset = 0
                stdscr.addnstr(2, 0, truncate_line("No matches", width - 1), max(0, width - 1))
                stdscr.refresh()
                key = stdscr.getch()
                if key in (27, ord("q")):
                    return None
                if key in (curses.KEY_BACKSPACE, 127, 8):
                    query = query[:-1]
                elif 32 <= key <= 126:
                    query += chr(key)
                elif key == 21:
                    query = ""
                continue

            if selected_index < scroll_offset:
                scroll_offset = selected_index
            elif selected_index >= scroll_offset + visible_count:
                scroll_offset = selected_index - visible_count + 1

            visible = filtered[scroll_offset : scroll_offset + visible_count]
            for row_index, contact in enumerate(visible, start=2):
                absolute_index = scroll_offset + row_index - 1
                unread = contact_is_unread(contact, seen_state)
                line = format_contact_option(absolute_index, contact, unread=unread)
                attr = curses.A_REVERSE if absolute_index - 1 == selected_index else curses.A_NORMAL
                if unread:
                    attr |= curses.A_BOLD
                stdscr.addnstr(row_index, 0, truncate_line(line, width - 1), max(0, width - 1), attr)

            stdscr.refresh()
            key = stdscr.getch()
            if key == -1:
                conversations = store.recent_conversations(limit=limit)
                selected_key = filtered[selected_index].chat_identifier or filtered[selected_index].handle
                continue
            if key in (curses.KEY_UP, ord("k")):
                selected_index = max(0, selected_index - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected_index = min(len(filtered) - 1, selected_index + 1)
            elif key in (10, 13, curses.KEY_ENTER):
                return filtered[selected_index]
            elif key in (27, ord("q")):
                return None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
                selected_index = 0
                scroll_offset = 0
            elif key == 21:
                query = ""
                selected_index = 0
                scroll_offset = 0
            elif 32 <= key <= 126:
                query += chr(key)
                selected_index = 0
                scroll_offset = 0
            if filtered:
                selected_key = filtered[selected_index].chat_identifier or filtered[selected_index].handle

    return curses.wrapper(run_picker)


def prompt_for_conversation(
    store: MessageStore,
    seen_state: SeenState,
    limit: int = 10,
    interactive_picker: bool = True,
    allow_cancel: bool = False,
) -> Contact | None:
    conversations = store.recent_conversations(limit=limit)
    if not conversations:
        if allow_cancel:
            return None
        return resolve_contact(store, prompt_for_contact())

    if interactive_picker and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            selected = select_conversation_with_arrows(store, seen_state, limit)
        except curses.error:
            selected = None
        if selected is not None:
            print()
            return selected
        if allow_cancel:
            print()
            return None

    print("Recent conversations:")
    print_conversation_list(conversations, seen_state=seen_state)

    while True:
        choice = input("select chat> ").strip()
        if not choice and allow_cancel:
            return None
        if choice.lower() in {"q", "/cancel"} and allow_cancel:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(conversations):
                return conversations[index - 1]
        if choice:
            return resolve_contact(store, choice)


def flush_new_messages(
    store: MessageStore,
    contact: Contact,
    seen: set[tuple[str | None, int, bool, str]],
    pending_self_messages: Counter[str],
    seen_state: SeenState,
    limit: int,
    you_label: str,
    them_label: str,
) -> list[Message]:
    fresh: list[Message] = []
    for message in store.recent_messages(contact, limit=limit):
        if message.dedupe_key in seen:
            continue
        seen.add(message.dedupe_key)
        pending_key = pending_message_key(message.text)
        if message.is_from_me and pending_self_messages.get(pending_key, 0) > 0:
            pending_self_messages[pending_key] -= 1
            if pending_self_messages[pending_key] <= 0:
                pending_self_messages.pop(pending_key, None)
            continue
        if not message.is_from_me:
            seen_state.mark_message_seen(contact, message)
        fresh.append(message)

    if fresh:
        print_history(fresh, you_label=you_label, them_label=them_label)
    return fresh


def start_poller(
    store: MessageStore,
    contact: Contact,
    seen: set[tuple[str | None, int, bool, str]],
    pending_self_messages: Counter[str],
    seen_state: SeenState,
    limit: int,
    interval: float,
    stop_event: threading.Event,
) -> threading.Thread:
    def poll() -> None:
        while not stop_event.wait(interval):
            try:
                flush_new_messages(
                    store,
                    contact,
                    seen,
                    pending_self_messages,
                    seen_state,
                    limit,
                    "you",
                    contact.label,
                )
            except MessageStoreError as exc:
                print(f"[warn] {exc}")
                return

    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    return worker


def resolve_contact(store: MessageStore, raw_contact: str) -> Contact:
    try:
        return store.resolve_contact(raw_contact)
    except MessageStoreError:
        return Contact(handle=raw_contact, label=raw_contact)


@dataclass
class InputResult:
    keep_running: bool = True
    next_contact: Contact | None = None


def handle_input(
    text: str,
    store: MessageStore,
    contact: Contact,
    seen: set[tuple[str | None, int, bool, str]],
    pending_self_messages: Counter[str],
    seen_state: SeenState,
    limit: int,
) -> InputResult:
    if text == "/quit":
        return InputResult(keep_running=False)
    if text == "/history":
        messages = store.recent_messages(contact, limit=limit)
        print_history(messages, "you", contact.label)
        for message in messages:
            seen.add(message.dedupe_key)
        return InputResult()
    if text == "/list":
        next_contact = prompt_for_conversation(
            store,
            seen_state,
            limit=DEFAULT_CHAT_LIST_LIMIT,
            interactive_picker=True,
            allow_cancel=True,
        )
        return InputResult(next_contact=next_contact)
    if text == "/help":
        print("commands: /help /history /list (back to chats) /quit")
        return InputResult()

    send_message(contact.handle, text, participant_handles=contact.participant_handles)
    echoed = False
    for _ in range(5):
        time.sleep(0.35)
        fresh = flush_new_messages(
            store,
            contact,
            seen,
            pending_self_messages,
            seen_state,
            limit,
            "you",
            contact.label,
        )
        if any(message.is_from_me and message.text == text for message in fresh):
            echoed = True
            break

    if not echoed:
        pending_self_messages[pending_message_key(text)] += 1
        fallback = Message(
            rowid=-1,
            guid=None,
            text=text,
            timestamp=datetime.now().astimezone(),
            is_from_me=True,
            handle=contact.handle,
            chat_identifier=contact.chat_identifier,
            service=contact.service,
        )
        print_message(fallback, you_label="you", them_label=contact.label)

    return InputResult()


def run_chat_session(
    store: MessageStore,
    seen_state: SeenState,
    contact: Contact,
    history_limit: int,
    poll_interval: float,
) -> tuple[bool, Contact | None]:
    history = store.recent_messages(contact, limit=history_limit)
    seen_state.mark_contact_seen(contact)
    print(f"tmsg session: {contact.label}")
    if history:
        print_history(history, "you", contact.label)

    seen = {message.dedupe_key for message in history}
    pending_self_messages: Counter[str] = Counter()
    stop_event = threading.Event()
    poller = start_poller(
        store,
        contact,
        seen,
        pending_self_messages,
        seen_state,
        history_limit,
        poll_interval,
        stop_event,
    )

    try:
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return False, None

            if not text:
                continue

            clear_previous_input_line()
            if text == "/list":
                stop_event.set()
                poller.join(timeout=0.2)
            try:
                result = handle_input(
                    text=text,
                    store=store,
                    contact=contact,
                    seen=seen,
                    pending_self_messages=pending_self_messages,
                    seen_state=seen_state,
                    limit=history_limit,
                )
            except MessageSendError as exc:
                print(f"[send failed] {exc}")
                if text == "/list":
                    stop_event = threading.Event()
                    poller = start_poller(
                        store,
                        contact,
                        seen,
                        pending_self_messages,
                        seen_state,
                        history_limit,
                        poll_interval,
                        stop_event,
                    )
                continue
            except MessageStoreError as exc:
                print(f"[read failed] {exc}")
                if text == "/list":
                    stop_event = threading.Event()
                    poller = start_poller(
                        store,
                        contact,
                        seen,
                        pending_self_messages,
                        seen_state,
                        history_limit,
                        poll_interval,
                        stop_event,
                    )
                continue

            if not result.keep_running:
                return False, None
            if result.next_contact is not None:
                return True, result.next_contact
            if text == "/list":
                stop_event = threading.Event()
                poller = start_poller(
                    store,
                    contact,
                    seen,
                    pending_self_messages,
                    seen_state,
                    history_limit,
                    poll_interval,
                    stop_event,
                )
    finally:
        stop_event.set()
        poller.join(timeout=0.2)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    store = MessageStore()
    seen_state = SeenState()

    try:
        if args.list_chats:
            print_conversation_list(
                store.recent_conversations(limit=DEFAULT_CHAT_LIST_LIMIT),
                seen_state=seen_state,
            )
            return 0

        raw_contact = args.contact_flag or args.contact
        contact = resolve_contact(store, raw_contact) if raw_contact else prompt_for_conversation(
            store, seen_state, limit=DEFAULT_CHAT_LIST_LIMIT
        )
    except MessageStoreError as exc:
        parser.exit(1, f"{exc}\n")

    if contact is None:
        return 0

    keep_running = True
    while keep_running:
        keep_running, next_contact = run_chat_session(
            store=store,
            seen_state=seen_state,
            contact=contact,
            history_limit=args.history_limit,
            poll_interval=args.poll_interval,
        )
        if next_contact is not None:
            contact = next_contact

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

