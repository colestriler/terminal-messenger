# imsg

`imsg` is a local macOS CLI that opens an interactive iMessage session inside your current terminal window.

## What v1 does

- Sends messages through `Messages.app` using AppleScript.
- Polls your local Messages database for recent inbound and outbound messages.
- Opens a lightweight REPL so you can type `imsg` much like `claude`.

## Install

```bash
cd /Users/colestriler/code/terminal-messenger
python3 -m pip install -e .
```

After that, you can start a session with:

```bash
python3 -m imsg --contact "+15555555555"
```

or:

```bash
python3 -m imsg frida
```

If no contact is passed, `imsg` will list recent conversations and let you pick one.
Use the arrow keys to move, start typing to search, and press Return to open a chat.

To just list recent conversations:

```bash
python3 -m imsg --list-chats
```

## Commands

- `python3 -m imsg --list-chats`
- `/help`
- `/history`
- `/list` to go back to the full chat list and switch conversations
- `/quit`

## Permissions

This tool depends on macOS privacy permissions.

- The first send should trigger an Automation prompt so Terminal or your Python runtime can control `Messages`.
- Reading `~/Library/Messages/chat.db` may require Full Disk Access for Terminal, iTerm, or the Python binary you are using.

If sending fails, check:

- `System Settings > Privacy & Security > Automation`
- `System Settings > Privacy & Security > Full Disk Access`

## Known limitations

- The local Messages database schema is undocumented and may change across macOS versions.
- Some rich-text or attachment-only messages may not decode cleanly in v1.
- Contact-name resolution is best-effort; if a name does not resolve, pass the phone number or email directly.

## Local verification

1. Run `python3 -m unittest discover -s tests`.
2. Start a chat with `python3 -m imsg --contact "+15555555555"`.
3. Or run `python3 -m imsg` and choose a recent conversation.
4. Send a message and approve the Automation prompt if macOS asks.
5. Reply from another device and confirm the terminal prints the incoming message.

