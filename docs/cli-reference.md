# CLI Reference

The `vscode-chat-browser` CLI is available after `pip install vscode-chat-browser`, or by running `src/vscode_chat_browser/cli.py` directly from a clone.

```
usage: chat_browser [-h] <command> ...

VS Code Chat Browser — CLI

positional arguments:
  <command>
    list      List workspaces and sessions
    show      Print conversation turns
    archive   Zip session(s) to an archive
    delete    Delete session(s)
    copy      Copy session(s) between workspaces
    repair    Repair DB index mismatches in a workspace
    restore   Restore sessions from an archive
    ui        Open the graphical chat browser

options:
  -h, --help  show this help message and exit
```

---

## Terminology

| Term | Meaning |
|---|---|
| `<storage_root>` | The `workspaceStorage` parent directory. Defaults to the platform-appropriate VS Code default. |
| `<ws_dir>` | The hash-named subdirectory for one workspace, e.g. `workspaceStorage/43d22b07bf23d2dd`. |
| `<session_id>` | The UUID of a single chat session (the `.jsonl` / `.json` filename without its extension). |

---

## Commands

### `list`

List all workspaces and their sessions under a storage root.

```
vscode-chat-browser list [<storage_root>]
```

| Argument | Default | Description |
|---|---|---|
| `<storage_root>` | VS Code default | Path to the `workspaceStorage` folder to scan |

**Output includes:** workspace name, on-disk path, storage hash directory, session count, each session's ID, timestamp, title, and any mismatch warnings.

**Example:**

```bash
vscode-chat-browser list
vscode-chat-browser list ~/Library/Application\ Support/Code/User/workspaceStorage
vscode-chat-browser list tests/fixtures/demo_storage
```

---

### `show`

Print the full conversation turns of a single session to stdout.

```
vscode-chat-browser show <ws_dir> <session_id> [--thinking]
```

| Argument | Description |
|---|---|
| `<ws_dir>` | The workspace hash directory |
| `<session_id>` | UUID of the session to display |
| `--thinking` | Also print Copilot reasoning / thinking blocks |

**Example:**

```bash
vscode-chat-browser show \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd \
  7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d

# with reasoning blocks visible
vscode-chat-browser show \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd \
  7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d \
  --thinking
```

---

### `archive`

Zip session(s) into a destination directory.

```
vscode-chat-browser archive <ws_dir> <dest_dir> [--session <id>]
```

| Argument | Description |
|---|---|
| `<ws_dir>` | The workspace hash directory |
| `<dest_dir>` | Directory where the zip file will be created |
| `--session <id>` | Archive a single session. Omit to archive the entire workspace. |

Archive filenames are automatically generated with a timestamp and session title:

- Single session: `chatarchive_<title>_<id[:8]>_<stamp>.zip`
- Full workspace: `chatarchive_<workspace_name>_<stamp>.zip`

**Example:**

```bash
# archive one session
vscode-chat-browser archive \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd \
  ~/Desktop/chat-backups \
  --session 7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d

# archive entire workspace
vscode-chat-browser archive \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd \
  ~/Desktop/chat-backups
```

---

### `delete`

Delete session file(s) and update the DB index.

```
vscode-chat-browser delete <ws_dir> [--session <id>] [--no-backup]
```

| Argument | Description |
|---|---|
| `<ws_dir>` | The workspace hash directory |
| `--session <id>` | Delete a single session. Omit to delete **all** sessions in the workspace. |
| `--no-backup` | Skip the automatic `state.vscdb` backup |

> **Warning:** This permanently removes session files. A timestamped DB backup (`state.vscdb.repair-backup-<stamp>`) is created by default unless `--no-backup` is passed.

**Example:**

```bash
# delete one session (with automatic DB backup)
vscode-chat-browser delete \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd \
  --session 7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d

# delete all sessions in a workspace
vscode-chat-browser delete \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd
```

---

### `copy`

Copy one or more sessions (files + DB entries) from one workspace to another.

```
vscode-chat-browser copy <src_ws_dir> <dst_ws_dir> --session <id> [<id> ...] [--no-backup]
```

| Argument | Description |
|---|---|
| `<src_ws_dir>` | Source workspace hash directory |
| `<dst_ws_dir>` | Destination workspace hash directory |
| `--session <id> [<id> ...]` | One or more session UUIDs to copy (required) |
| `--no-backup` | Skip DB backup in the destination workspace |

Only sessions that have a file on disk in the source workspace are copied. The destination's `chatSessions/` directory is created if it does not exist. A `state.vscdb.merge-backup-<stamp>` is created in the destination by default.

**Example:**

```bash
vscode-chat-browser copy \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd \
  ~/.config/Code/User/workspaceStorage/9f1a2b3c4d5e6f70 \
  --session 7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d \
             8b9c0d1e-2f3a-4b5c-6d7e-8f9a0b1c2d3e
```

---

### `repair`

Repair mismatches between the `state.vscdb` DB index and session files on disk.

```
vscode-chat-browser repair <ws_dir> [--session <id>] [--no-backup]
```

| Argument | Description |
|---|---|
| `<ws_dir>` | The workspace hash directory |
| `--session <id>` | Repair a single session. Omit to repair all mismatches. |
| `--no-backup` | Skip DB backup |

**Repair actions performed:**

| Situation | Action |
|---|---|
| File on disk, not in DB | Added to DB index |
| DB has session as `isEmpty`, file exists | DB entry updated to active |
| DB references session, no file on disk | DB entry flagged as `isEmpty` |
| DB and disk are in sync | No change (`already_in_sync`) |

**Example:**

```bash
# repair all mismatches
vscode-chat-browser repair \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd

# repair one session
vscode-chat-browser repair \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd \
  --session 7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d
```

---

### `restore`

Restore session files from a zip archive created by `archive`.

```
vscode-chat-browser restore <zip_path> <ws_dir> [--no-backup]
```

| Argument | Description |
|---|---|
| `<zip_path>` | Path to the `.zip` archive |
| `<ws_dir>` | Destination workspace hash directory |
| `--no-backup` | Skip DB backup |

Sessions that already exist in the destination are not overwritten. The DB index is updated with entries for all restored sessions.

**Example:**

```bash
vscode-chat-browser restore \
  ~/Desktop/chat-backups/chatarchive_MyProject_20260518-120000.zip \
  ~/.config/Code/User/workspaceStorage/43d22b07bf23d2dd
```

---

### `ui`

Open the graphical Tkinter chat browser.

```
vscode-chat-browser ui [--storage-root <path>]
```

| Argument | Default | Description |
|---|---|---|
| `--storage-root <path>` | VS Code default | Override the workspaceStorage root shown on launch |

**Example:**

```bash
# open using VS Code's default storage
vscode-chat-browser ui

# open pointing at the test fixture directory
vscode-chat-browser ui --storage-root tests/fixtures/demo_storage
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error (message printed to stderr) |

---

## Running without pip install

From the repository root, invoke the CLI module directly:

```bash
# if running from the cloned repo root
python src/vscode_chat_browser/cli.py list

# or make cli.py executable (Unix)
chmod +x src/vscode_chat_browser/cli.py
./src/vscode_chat_browser/cli.py list
```
