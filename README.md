# tmsg

`tmsg` is a terminal client for iMessage on macOS.

Package name: `terminal-messenger`  
Command name: `tmsg`

## Features

- Sends messages through `Messages.app` using AppleScript.
- Reads recent messages from the local Messages database.
- Lets you pick recent conversations from the terminal.
- Loads recent message history when you open a chat.
- Resolves many phone numbers and emails to contact names from macOS Contacts.
- Supports arrow-key navigation and live search.
- Shows unread chats in the picker.

## Requirements

- macOS
- iMessage set up in `Messages.app`
- Python 3.8+

## Install

Recommended:

```bash
pipx install terminal-messenger
```

If you do not use `pipx`:

```bash
python3 -m pip install terminal-messenger
```

## First-time macOS permissions

`tmsg` needs macOS permissions to work:

- `Automation` so it can send through `Messages.app`
- `Full Disk Access` so it can read `~/Library/Messages/chat.db`

The first send should trigger the Automation prompt automatically.

If reading or sending fails, check:

- `System Settings > Privacy & Security > Automation`
- `System Settings > Privacy & Security > Full Disk Access`

You may need to grant access to both your terminal app and the Python binary it uses.

## Quick start

```bash
tmsg
```

That opens the conversation picker.

## Common commands

Open the chat picker:

```bash
tmsg
```

Open a specific conversation:

```bash
tmsg frida
```

Open a specific phone number or email:

```bash
tmsg --contact "+15555555555"
```

List recent conversations without opening one:

```bash
tmsg --list-chats
```

Show more history when opening a chat:

```bash
tmsg --history-limit 200
```

## While using it

In the picker:

- Type to search
- `Up` / `Down` to move
- `Enter` to open
- `Esc` or `q` to cancel

In a chat:

- `/help`
- `/history`
- `/list`
- `/quit`

## Troubleshooting

- `Operation not permitted` usually means Full Disk Access is missing
- send failures usually mean Automation permission was denied
- if `tmsg` is not found after install, reopen your terminal or refresh your shell shims
- macOS Messages internals are undocumented, so some reactions and rich content may still be imperfect

## Development

```bash
git clone <your-repo-url>
cd terminal-messenger
python3 -m pip install -e .
python3 -m unittest discover -s tests
```

You can also run it directly during development:

```bash
python3 -m tmsg
```

## Releasing

Publish a new version to PyPI:

```bash
yarn deploy 0.1.1
```

That command:

- updates the version in `pyproject.toml`
- rebuilds the package
- checks the built files
- uploads them to PyPI

If you want non-interactive upload, either set `PYPI_TOKEN` in your shell or create a local `.env` file:

```bash
export PYPI_TOKEN=pypi-...
yarn deploy 0.1.1
```

or:

```bash
cp .env.example .env
```

Then edit `.env` and set:

```bash
PYPI_TOKEN=pypi-...
```

