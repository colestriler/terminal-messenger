# tmsg

`tmsg` is a local macOS terminal client for iMessage. The distributable package name is `terminal-messenger`, and the command people run is `tmsg`.

## What it does

- Sends messages through `Messages.app` using AppleScript.
- Reads recent messages from the local Messages database.
- Shows up to 250 recent conversations in the picker and list view.
- Loads 100 recent messages by default when you open a chat.
- Resolves many phone numbers and emails to contact names from macOS Contacts.
- Supports arrow-key chat selection and live search in the picker.
- Shows `*` markers for chats with unread incoming messages.
- Styles your messages differently from incoming ones for easier scanning.

## Requirements

- macOS
- iMessage set up in `Messages.app`
- Python 3.8+

## Quick start

Install with `pipx`:

```bash
pipx install terminal-messenger
```

Then run:

```bash
tmsg
```

On first use:

- macOS should ask for Automation permission so `tmsg` can control `Messages`
- you may need to grant Full Disk Access so `tmsg` can read `~/Library/Messages/chat.db`

If macOS blocks access, open:

- `System Settings > Privacy & Security > Automation`
- `System Settings > Privacy & Security > Full Disk Access`

## Local development

```bash
git clone <your-repo-url>
cd terminal-messenger
python3 -m pip install -e .
```

You can also run it without installing the console script:

```bash
python3 -m tmsg
```

## Run

Open the interactive picker:

```bash
tmsg
```

Open a specific conversation directly:

```bash
tmsg frida
```

or:

```bash
tmsg --contact "+15555555555"
```

List recent conversations without opening a chat:

```bash
tmsg --list-chats
```

Override the default 100-message history window:

```bash
tmsg --history-limit 200
```

## Picker controls

When the chat picker is open:

- `*` marks chats with unread messages.
- Type to search/filter conversations live.
- `Up` / `Down` moves the selection.
- `Enter` opens the highlighted conversation.
- `Backspace` deletes search text.
- `Esc` or `q` cancels.
- The picker refreshes periodically while open so new unread chats can appear.

## In-chat commands

- `/help`
- `/history`
- `/list` goes back to the conversation picker
- `/quit`

## Notes

- The Messages database schema is undocumented and may change across macOS versions.
- Contact-name resolution is best-effort and depends on local Contacts data.
- Some reactions, attachments, and rich-content previews are still rough around the edges.
- There may still be terminal UX quirks because the chat view currently uses a lightweight terminal loop rather than a full-screen TUI.

## Verify locally

```bash
python3 -m unittest discover -s tests
```

Manual check:

1. Run `tmsg`
2. Open a conversation
3. Send a message and approve any macOS prompt
4. Reply from another device and confirm it appears in the terminal

