from __future__ import annotations

import subprocess


SEND_SCRIPT = """
on run argv
  if (count of argv) is less than 2 then
    error "Expected contact handle and message text."
  end if

  set targetHandle to item 1 of argv
  set messageText to item 2 of argv

  tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy targetHandle of targetService
    send messageText to targetBuddy
  end tell
end run
""".strip()


class MessageSendError(RuntimeError):
    """Raised when a message could not be sent."""


def _looks_like_permission_error(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        needle in lowered
        for needle in (
            "not authorized",
            "not permitted",
            "automation",
            "appleevent",
            "osascript is not allowed",
            "(-1743)",
        )
    )


def send_message(contact: str, text: str) -> None:
    try:
        completed = subprocess.run(
            ["osascript", "-", contact, text],
            input=SEND_SCRIPT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MessageSendError("`osascript` is not available on this Mac.") from exc

    if completed.returncode == 0:
        return

    stderr = (completed.stderr or "").strip()
    if _looks_like_permission_error(stderr):
        raise MessageSendError(
            "macOS blocked automation. Allow Terminal/Python to control Messages in "
            "System Settings > Privacy & Security > Automation."
        )

    raise MessageSendError(stderr or "Messages rejected the send request.")

