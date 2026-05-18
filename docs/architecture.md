# Architecture & Contributing

## Project layout

```
VSCode-Chat-Browser/
├── src/
│   └── vscode_chat_browser/
│       ├── __init__.py                 # package init
│       ├── core.py                     # pure business logic (no GUI)
│       ├── cli.py                      # argparse CLI entry point
│       └── workspace_chat_browser.py  # Tkinter GUI application
├── tests/
│   ├── conftest.py                     # pytest fixtures + tkinter stub
│   ├── test_core.py                    # unit + integration tests for core.py
│   ├── test_cli.py                     # CLI integration tests
│   ├── test_workspace_chat_browser.py  # GUI smoke tests (headless)
│   └── fixtures/
│       ├── sessions/                   # static .jsonl / .json session files
│       └── demo_storage/               # pre-built demo workspaceStorage tree
├── docs/
│   ├── index.md                        # overview and quick-start
│   ├── cli-reference.md                # full CLI reference
│   └── architecture.md                 # this file
├── pyproject.toml
└── README.md
```

---

## Module responsibilities

### `core.py`

Pure business logic with **no GUI dependency**. Importable from tests, the CLI, and the Tkinter app.

**Data helpers (read-only):**

| Function | Description |
|---|---|
| `replay_jsonl(path)` | Reconstruct session state by replaying a JSONL append-log |
| `load_session_index(storage_dir)` | Build a session list from the DB index + files on disk; detects mismatches |
| `load_requests(storage_dir, session_id)` | Load the request list from a session file |
| `workspace_display_name(storage_dir)` | Extract `(short_name, full_path)` from `workspace.json` |
| `session_file(storage_dir, session_id)` | Resolve the file path for a session, preferring `.json` over `.jsonl` |
| `extract_user_text(request)` | Pull the user's message text out of a request dict |
| `extract_response_text(request)` | Collect the main markdown response text |
| `extract_thinking_text(request)` | Collect Copilot reasoning / thinking blocks |
| `fmt_ts(ts_ms)` | Format a millisecond timestamp as `YYYY-MM-DD HH:MM` |
| `fmt_mtime(mtime)` | Format a float mtime as `YYYY-MM-DD HH:MM` |

**Actions (mutate filesystem / DB):**

| Function | Description |
|---|---|
| `action_archive_session(storage_dir, session_id, dest_dir)` | Zip one session to a directory |
| `action_archive_workspace(storage_dir, dest_dir)` | Zip all session files in a workspace |
| `action_delete_session(storage_dir, session_id, *, backup)` | Delete a session file and remove from DB index |
| `action_delete_workspace_chats(storage_dir, *, backup)` | Delete all session files and clear DB index |
| `action_copy_sessions(src_dir, dst_dir, session_ids, *, backup)` | Copy sessions between workspaces |
| `action_repair_session(storage_dir, session_id, *, backup)` | Repair a single index mismatch |
| `action_repair_all(storage_dir, *, backup)` | Repair all index mismatches in a workspace |
| `action_restore_archive(zip_path, storage_dir, *, backup)` | Restore sessions from a zip archive |

All mutating actions accept a `backup: bool` keyword argument. When `True` (the default), a timestamped copy of `state.vscdb` is created before any changes are written.

### `cli.py`

Thin `argparse` wrapper around `core.py`. Each subcommand maps to a `cmd_*` function that validates arguments, calls the relevant `core` action, and prints a human-readable result.

The CLI entry point is registered in `pyproject.toml`:

```toml
[project.scripts]
vscode-chat-browser = "vscode_chat_browser.cli:main"
```

### `workspace_chat_browser.py`

Tkinter GUI (`ChatBrowser` class, subclasses `tk.Tk`). All data operations delegate to `core.py`; the GUI layer is responsible only for display, user interaction, and threading (UI updates are scheduled with `after()`).

---

## Data flow

```
workspaceStorage/
  <hash>/
    state.vscdb          ← SQLite, key "chat.ChatSessionStore.index"
    chatSessions/
      <uuid>.jsonl       ← append-log, replayed by replay_jsonl()
      <uuid>.json        ← snapshot format, parsed directly

load_session_index()  →  merges DB entries + disk files, flags mismatches
load_requests()       →  replay_jsonl() or direct .json parse
extract_*_text()      →  pull fields from request dicts
```

---

## Tests

Tests use `pytest`. No external dependencies are required beyond `pytest` itself.

```bash
pip install pytest
pytest
```

### Fixture structure

`conftest.py` builds two in-memory workspace trees for each test session:

| Workspace | Format | Description |
|---|---|---|
| `ws_alpha` | `.jsonl` | Two healthy sessions + two mismatch cases |
| `ws_beta` | `.json` | One healthy session |

Static session data lives in `tests/fixtures/sessions/`. The `demo_storage/` subdirectory provides a ready-made `workspaceStorage` tree for manual UI testing:

```bash
vscode-chat-browser ui --storage-root tests/fixtures/demo_storage
```

### Tkinter headless testing

`conftest.py` stubs out `tkinter` and its submodules before the GUI module is imported, so all tests run without a display. The `_stub_tkinter()` function installs `MagicMock`-based replacements for every widget class and constant the application references at module level.

---

## Contributing

### Getting started

```bash
git clone https://github.com/yourname/VSCode-Chat-Browser
cd VSCode-Chat-Browser
pip install -e .
pip install pytest
pytest
```

### Guidelines

- **No external runtime dependencies.** The only dependency for running the tool is Python 3.10+. `pytest` is the only dev dependency.
- **Business logic goes in `core.py`.** The GUI and CLI are thin wrappers; keep them that way.
- **All actions must be covered by tests.** Use the `conftest.py` fixtures rather than modifying real workspace data.
- **DB backups before mutations.** Every action that modifies `state.vscdb` should create a timestamped backup (unless `backup=False` is explicitly passed).
- **Cross-platform paths.** Use `pathlib.Path` throughout; avoid hard-coded separators.

### Adding a new CLI command

1. Implement the action in `core.py` as `action_<name>(...)`.
2. Add a `cmd_<name>` handler in `cli.py`.
3. Register the subparser in `build_parser()`.
4. Add tests to `test_core.py` and `test_cli.py`.

### Running the demo UI

```bash
vscode-chat-browser ui --storage-root tests/fixtures/demo_storage
```

This lets you exercise the full UI without touching any real VS Code data.

---

## Session JSONL format (detail)

Each line in a `.jsonl` session file is one of:

```jsonc
// kind 0 — full initial state
{"kind": 0, "v": {"requests": [], "customTitle": "My chat", ...}}

// kind 1 — property update (dot-path in k, new value in v)
{"kind": 1, "k": ["customTitle"], "v": "Renamed chat"}

// kind 2 — array append (dot-path in k, item(s) in v)
{"kind": 2, "k": ["requests"], "v": {"message": {...}, "response": [...], "timestamp": 1716000000000}}
```

`replay_jsonl()` processes lines in order, applying `kind=1` updates with `_set_nested()` and `kind=2` appends with `_append_nested()`, to reconstruct the final session state dict.

---

## DB index format

The `state.vscdb` SQLite database has a single table `ItemTable (key TEXT PRIMARY KEY, value TEXT)`. The chat session index is stored at key `chat.ChatSessionStore.index` as a JSON string:

```jsonc
{
  "version": 1,
  "entries": {
    "<uuid>": {
      "sessionId": "<uuid>",
      "title": "Session title",
      "lastMessageDate": 1716000000000,
      "timing": {"created": 1715900000000},
      "initialLocation": "panel",
      "hasPendingEdits": false,
      "isEmpty": false,
      "isExternal": false,
      "lastResponseState": 1
    }
  }
}
```

The `isEmpty` flag is how VS Code marks sessions it considers cleared. The repair logic uses this flag to detect and fix mismatches.
