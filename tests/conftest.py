"""
conftest.py

Two responsibilities:

1. Patch tkinter before the main module is imported so that tests run headless.
2. Build reusable storage fixture trees for action/integration tests.

Fixture layout (built from tests/fixtures/sessions/ static files)
------------------------------------------------------------------
storage_root/
  ws_alpha/          <- JSONL workspace
    workspace.json
    state.vscdb      <- aaaa-0001 in DB; bbbb-0002 missing (disk-only);
    chatSessions/       dddd-0004 in DB only (no file)
      aaaa-0001.jsonl  <- healthy, both DB + disk
      bbbb-0002.jsonl  <- disk-only mismatch
  ws_beta/           <- JSON workspace
    workspace.json
    state.vscdb      <- cccc-0003 in DB
    chatSessions/
      cccc-0003.json   <- healthy, both DB + disk

Session IDs exported as module-level constants for convenient use in tests.
"""

import sys
import types
from unittest.mock import MagicMock


def _stub_tkinter():
    """Install stub modules for tkinter and its children."""
    # Only stub if tkinter isn't already importable (e.g. a real display exists)
    # We stub unconditionally so test-suite behaviour is consistent everywhere.
    tk_stub = types.ModuleType("tkinter")

    # Classes / constants that the module references at module level
    for name in (
            "Tk",
            "Frame",
            "Label",
            "Text",
            "Entry",
            "Listbox",
            "BooleanVar",
            "StringVar",
            "Toplevel",
            "Menu",
            "Widget",
            "Event",
            "BOTH",
            "BOTTOM",
            "DISABLED",
            "END",
            "FLAT",
            "HORIZONTAL",
            "LEFT",
            "NONE",
            "NORMAL",
            "RIGHT",
            "SUNKEN",
            "TOP",
            "VERTICAL",
            "WORD",
            "X",
            "Y",
            "ttk",
            "messagebox",
    ):
        setattr(tk_stub, name, MagicMock())

    sys.modules["tkinter"] = tk_stub

    # tkinter.ttk
    ttk_stub = types.ModuleType("tkinter.ttk")
    for name in (
            "Style",
            "Frame",
            "Label",
            "Entry",
            "Button",
            "Checkbutton",
            "Radiobutton",
            "Separator",
            "Scrollbar",
            "Treeview",
            "PanedWindow",
            "Progressbar",
    ):
        setattr(ttk_stub, name, MagicMock())
    sys.modules["tkinter.ttk"] = ttk_stub
    tk_stub.ttk = ttk_stub

    # tkinter.messagebox
    mb_stub = types.ModuleType("tkinter.messagebox")
    for name in ("showerror", "showinfo", "showwarning", "askyesno"):
        setattr(mb_stub, name, MagicMock())
    sys.modules["tkinter.messagebox"] = mb_stub
    tk_stub.messagebox = mb_stub

    # tkinter.filedialog
    fd_stub = types.ModuleType("tkinter.filedialog")
    for name in ("askdirectory", "askopenfilename"):
        setattr(fd_stub, name, MagicMock())
    sys.modules["tkinter.filedialog"] = fd_stub


_stub_tkinter()

# ── session IDs referenced in tests ──────────────────────────────────────────

SESS_ALPHA_JSONL = "aaaa-0001"  # healthy (DB + disk), ws_alpha
SESS_DISK_ONLY = "bbbb-0002"  # disk-only mismatch, ws_alpha
SESS_BETA_JSON = "cccc-0003"  # healthy (DB + disk), ws_beta
SESS_DB_ONLY = "dddd-0004"  # DB-only mismatch, ws_alpha

# ── storage fixture builders ──────────────────────────────────────────────────

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

_FIXTURE_SESSIONS = Path(__file__).parent / "fixtures" / "sessions"

_WS_ALPHA_INDEX = {
    "version": 1,
    "entries": {
        SESS_ALPHA_JSONL: {
            "sessionId": SESS_ALPHA_JSONL,
            "title": "Alpha Chat One",
            "lastMessageDate": 1700000002000,
            "timing": {
                "created": 1700000001000
            },
            "initialLocation": "panel",
            "hasPendingEdits": False,
            "isEmpty": False,
            "isExternal": False,
            "lastResponseState": 1,
        },
        # SESS_DISK_ONLY intentionally absent → disk-only mismatch
        SESS_DB_ONLY: {
            "sessionId": SESS_DB_ONLY,
            "title": "Alpha Chat Four (DB only)",
            "lastMessageDate": 1700000030000,
            "timing": {
                "created": 1700000030000
            },
            "initialLocation": "panel",
            "hasPendingEdits": False,
            "isEmpty": False,
            "isExternal": False,
            "lastResponseState": 1,
        },
    },
}

_WS_BETA_INDEX = {
    "version": 1,
    "entries": {
        SESS_BETA_JSON: {
            "sessionId": SESS_BETA_JSON,
            "title": "Beta Chat One",
            "lastMessageDate": 1700000020000,
            "timing": {
                "created": 1700000020000
            },
            "initialLocation": "panel",
            "hasPendingEdits": False,
            "isEmpty": False,
            "isExternal": False,
            "lastResponseState": 1,
        },
    },
}


def _write_db(db_path: Path, index: dict) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        ("chat.ChatSessionStore.index", json.dumps(index)),
    )
    conn.commit()
    conn.close()


def _build_ws_alpha(base: Path) -> Path:
    ws = base / "ws_alpha"
    cs = ws / "chatSessions"
    cs.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps(
        {"folder": "file:///C:/projects/alpha"}),
                                       encoding="utf-8")
    shutil.copy(_FIXTURE_SESSIONS / "aaaa-0001.jsonl", cs / "aaaa-0001.jsonl")
    shutil.copy(_FIXTURE_SESSIONS / "bbbb-0002.jsonl", cs / "bbbb-0002.jsonl")
    # dddd-0004 intentionally NOT on disk → DB-only mismatch
    _write_db(ws / "state.vscdb", _WS_ALPHA_INDEX)
    return ws


def _build_ws_beta(base: Path) -> Path:
    ws = base / "ws_beta"
    cs = ws / "chatSessions"
    cs.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps(
        {"folder": "file:///C:/projects/beta"}),
                                       encoding="utf-8")
    shutil.copy(_FIXTURE_SESSIONS / "cccc-0003.json", cs / "cccc-0003.json")
    _write_db(ws / "state.vscdb", _WS_BETA_INDEX)
    return ws


@pytest.fixture(scope="session")
def storage_root(tmp_path_factory):
    """
    Immutable fixture: a fully-populated workspaceStorage hierarchy.
    Tests that need to mutate state should use ``writable_storage`` instead.
    """
    base = tmp_path_factory.mktemp("storage")
    _build_ws_alpha(base)
    _build_ws_beta(base)
    return base


@pytest.fixture
def writable_storage(tmp_path, storage_root):
    """
    Per-test mutable copy of the fixture storage tree.
    Use this for any test that archives, deletes, copies, repairs, or restores.
    Returns the storage root (contains ws_alpha/ and ws_beta/ sub-dirs).
    """
    dest = tmp_path / "storage"
    shutil.copytree(str(storage_root), str(dest))
    return dest
