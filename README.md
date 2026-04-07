# imsg

`imsg` is a local macOS terminal client for iMessage. It opens inside your current terminal window, lets you browse recent conversations, search the chat picker, open a thread, and text from the command line.

## Current behavior

- Sends messages through `Messages.app` using AppleScript.
- Reads recent messages from the local Messages database.
- Shows up to 250 recent conversations in the picker and list view.
- Loads 100 recent messages by default when you open a chat.
- Resolves many phone numbers and emails to contact names from macOS Contacts.
- Supports arrow-key chat selection and live search in the picker.
- Styles your messages differently from incoming ones for easier scanning.

## Install

```bash
cd /Users/colestriler/code/terminal-messenger
python3 -m pip install -e .
```

## Run

Open the interactive picker:

```bash
python3 -m imsg
```

Open a specific conversation directly:

```bash
python3 -m imsg frida
```

or:

```bash
python3 -m imsg --contact "+15555555555"
```

List recent conversations without opening a chat:

```bash
python3 -m imsg --list-chats
```

Override the default 100-message history window:

```bash
python3 -m imsg --history-limit 200
```

## Picker controls

When the chat picker is open:

- Type to search/filter conversations live.
- `Up` / `Down` moves the selection.
- `Enter` opens the highlighted conversation.
- `Backspace` deletes search text.
- `Esc` or `q` cancels.

## In-chat commands

- `/help`
- `/history`
- `/list` goes back to the conversation picker
- `/quit`

## Permissions

`imsg` depends on macOS privacy permissions.

- The first send should trigger an Automation prompt so your terminal or Python runtime can control `Messages`.
- Reading `~/Library/Messages/chat.db` may require Full Disk Access for your terminal app and sometimes the `python3` binary too.

If sending or reading fails, check:

- `System Settings > Privacy & Security > Automation`
- `System Settings > Privacy & Security > Full Disk Access`

## Notes

- The Messages database schema is undocumented and may change across macOS versions.
- Contact-name resolution is best-effort and depends on local Contacts data.
- Some reactions, attachments, and rich-content previews are still rough around the edges.
- There may still be terminal UX quirks because the chat view currently uses a lightweight terminal loop rather than a full-screen TUI.

## Verify locally

```bash
python3 -m unittest discover -s tests
```

Then:

1. Run `python3 -m imsg`.
2. Search or arrow to a conversation and press `Enter`.
3. Send a message and approve the Automation prompt if macOS asks.
4. Reply from another device and confirm the terminal prints the incoming message.

