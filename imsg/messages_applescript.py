from __future__ import annotations

import subprocess


SEND_SCRIPT = """
on run argv
  if (count of argv) is less than 2 then
    error "Expected contact handle and message text."
  end if

  set targetHandle to item 1 of argv
  set messageText to item 2 of argv
  set participantCsv to ""
  if (count of argv) is greater than or equal to 3 then
    set participantCsv to item 3 of argv
  end if

  set targetParticipants to my csv_to_list(participantCsv)

  tell application "Messages"
    if (count of targetParticipants) is greater than 1 then
      repeat with candidateChat in chats
        if my chat_matches_handles(candidateChat, targetParticipants) then
          send messageText to contents of candidateChat
          return
        end if
      end repeat
    end if

    repeat with candidateChat in chats
      if my chat_contains_handle(candidateChat, targetHandle) then
        send messageText to contents of candidateChat
        return
      end if
    end repeat
  end tell

  error "Could not find an existing Messages chat for this target."
end run

on csv_to_list(valueText)
  if valueText is "" then
    return {}
  end if

  set AppleScript's text item delimiters to ","
  set parsedItems to text items of valueText
  set AppleScript's text item delimiters to ""

  set filteredItems to {}
  repeat with itemText in parsedItems
    set normalizedItem to contents of itemText
    if normalizedItem is not "" then
      set end of filteredItems to normalizedItem
    end if
  end repeat
  return filteredItems
end csv_to_list

on chat_contains_handle(candidateChat, targetHandle)
  tell application "Messages"
    repeat with participantRef in participants of contents of candidateChat
      if (handle of contents of participantRef) is targetHandle then
        return true
      end if
    end repeat
  end tell
  return false
end chat_contains_handle

on chat_matches_handles(candidateChat, expectedHandles)
  tell application "Messages"
    set chatHandles to {}
    repeat with participantRef in participants of contents of candidateChat
      set end of chatHandles to handle of contents of participantRef
    end repeat
  end tell

  if (count of chatHandles) is not (count of expectedHandles) then
    return false
  end if

  repeat with expectedHandle in expectedHandles
    if (contents of expectedHandle) is not in chatHandles then
      return false
    end if
  end repeat
  return true
end chat_matches_handles
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


def send_message(contact: str, text: str, participant_handles: tuple[str, ...] = ()) -> None:
    try:
        completed = subprocess.run(
            ["osascript", "-", contact, text, ",".join(participant_handles)],
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

