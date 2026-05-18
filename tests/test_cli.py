"""
test_cli.py

Integration tests for src/cli.py.

Tests invoke the CLI by calling cli.main(argv) directly, which is
fast and avoids subprocess overhead while still exercising the full
argument-parsing → action → output chain.
"""

import json
import zipfile
from pathlib import Path

import pytest

from vscode_chat_browser import cli, core
from conftest import (
    SESS_ALPHA_JSONL,
    SESS_BETA_JSON,
    SESS_DB_ONLY,
    SESS_DISK_ONLY,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _run(argv: list[str], capsys=None) -> tuple[int, str, str]:
    """Run the CLI and return (exit_code, stdout, stderr)."""
    code = cli.main(argv)
    if capsys:
        cap = capsys.readouterr()
        return code, cap.out, cap.err
    return code, "", ""


def _read_db(ws_dir: Path) -> dict:
    return core._db_read_index(ws_dir / "state.vscdb")


# ══════════════════════════════════════════════════════════════════════════════
# list
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdList:

    def test_lists_workspaces(self, storage_root, capsys):
        code, out, err = _run(["list", str(storage_root)], capsys)
        assert code == 0
        assert "alpha" in out.lower() or "ws_alpha" in out.lower()
        assert "beta" in out.lower() or "ws_beta" in out.lower()

    def test_lists_session_ids(self, storage_root, capsys):
        code, out, err = _run(["list", str(storage_root)], capsys)
        assert SESS_ALPHA_JSONL in out
        assert SESS_BETA_JSON in out

    def test_flags_mismatches(self, storage_root, capsys):
        code, out, err = _run(["list", str(storage_root)], capsys)
        # At least the two mismatch marker symbols or "⚠" should appear
        assert SESS_DISK_ONLY in out or SESS_DB_ONLY in out

    def test_missing_root_returns_error(self, tmp_path, capsys):
        missing = str(tmp_path / "no_such_dir")
        code, out, err = _run(["list", missing], capsys)
        assert code != 0


# ══════════════════════════════════════════════════════════════════════════════
# show
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdShow:

    def test_prints_conversation(self, storage_root, capsys):
        code, out, err = _run(
            ["show", str(storage_root / "ws_alpha"), SESS_ALPHA_JSONL],
            capsys,
        )
        assert code == 0
        assert "Hello from alpha" in out
        assert "Hi there from the assistant!" in out

    def test_thinking_flag_shows_reasoning(self, storage_root, capsys):
        code, out, err = _run(
            [
                "show",
                str(storage_root / "ws_alpha"), SESS_ALPHA_JSONL, "--thinking"
            ],
            capsys,
        )
        assert code == 0
        assert "capabilities" in out.lower()

    def test_json_session(self, storage_root, capsys):
        code, out, err = _run(
            ["show", str(storage_root / "ws_beta"), SESS_BETA_JSON],
            capsys,
        )
        assert code == 0
        assert "Question in json format" in out

    def test_missing_session_returns_error(self, storage_root, capsys):
        code, out, err = _run(
            ["show", str(storage_root / "ws_alpha"), "no-such-id"],
            capsys,
        )
        assert code != 0


# ══════════════════════════════════════════════════════════════════════════════
# archive
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdArchive:

    def test_archives_single_session(self, writable_storage, tmp_path, capsys):
        ws = str(writable_storage / "ws_alpha")
        dest = str(tmp_path / "out")
        code, out, err = _run(
            ["archive", ws, dest, "--session", SESS_ALPHA_JSONL], capsys)
        assert code == 0
        assert "Archived" in out
        archives = list((tmp_path / "out").glob("*.zip"))
        assert len(archives) == 1

    def test_archives_all_sessions(self, writable_storage, tmp_path, capsys):
        ws = str(writable_storage / "ws_alpha")
        dest = str(tmp_path / "out")
        code, out, err = _run(["archive", ws, dest], capsys)
        assert code == 0
        archives = list((tmp_path / "out").glob("*.zip"))
        assert len(archives) == 1
        with zipfile.ZipFile(str(archives[0])) as zf:
            names = zf.namelist()
        assert any(SESS_ALPHA_JSONL in n for n in names)
        assert any(SESS_DISK_ONLY in n for n in names)

    def test_bad_session_returns_error(self, writable_storage, tmp_path,
                                       capsys):
        ws = str(writable_storage / "ws_alpha")
        dest = str(tmp_path / "out")
        code, out, err = _run(["archive", ws, dest, "--session", "no-such"],
                              capsys)
        assert code != 0
        assert "ERROR" in err


# ══════════════════════════════════════════════════════════════════════════════
# delete
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdDelete:

    def test_deletes_single_session(self, writable_storage, capsys):
        ws = writable_storage / "ws_alpha"
        sf = core.session_file(ws, SESS_ALPHA_JSONL)
        code, out, err = _run(
            ["delete",
             str(ws), "--session", SESS_ALPHA_JSONL, "--no-backup"], capsys)
        assert code == 0
        assert not sf.exists()

    def test_deletes_all_sessions(self, writable_storage, capsys):
        ws = writable_storage / "ws_alpha"
        cs = ws / "chatSessions"
        code, out, err = _run(["delete", str(ws), "--no-backup"], capsys)
        assert code == 0
        remaining = list(cs.glob("*.json")) + list(cs.glob("*.jsonl"))
        assert remaining == []

    def test_delete_creates_backup_by_default(self, writable_storage, capsys):
        ws = writable_storage / "ws_alpha"
        before = list(ws.glob("state.vscdb.*"))
        _run(["delete", str(ws), "--session", SESS_ALPHA_JSONL], capsys)
        after = list(ws.glob("state.vscdb.*"))
        assert len(after) > len(before)


# ══════════════════════════════════════════════════════════════════════════════
# copy
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdCopy:

    def test_copies_session(self, writable_storage, capsys):
        src = str(writable_storage / "ws_alpha")
        dst = str(writable_storage / "ws_beta")
        code, out, err = _run(
            ["copy", src, dst, "--session", SESS_ALPHA_JSONL, "--no-backup"],
            capsys)
        assert code == 0
        assert "Copied" in out
        dest_file = (writable_storage / "ws_beta" / "chatSessions" /
                     f"{SESS_ALPHA_JSONL}.jsonl")
        assert dest_file.exists()

    def test_multiple_sessions(self, writable_storage, capsys):
        src = str(writable_storage / "ws_alpha")
        dst = str(writable_storage / "ws_beta")
        code, out, err = _run([
            "copy", src, dst, "--session", SESS_ALPHA_JSONL, SESS_DISK_ONLY,
            "--no-backup"
        ], capsys)
        assert code == 0

    def test_bad_session_returns_error(self, writable_storage, capsys):
        src = str(writable_storage / "ws_alpha")
        dst = str(writable_storage / "ws_beta")
        code, out, err = _run(
            ["copy", src, dst, "--session", "bad-id", "--no-backup"], capsys)
        assert code != 0


# ══════════════════════════════════════════════════════════════════════════════
# repair
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdRepair:

    def test_repairs_all_mismatches(self, writable_storage, capsys):
        ws = str(writable_storage / "ws_alpha")
        code, out, err = _run(["repair", ws, "--no-backup"], capsys)
        assert code == 0
        assert "2" in out  # "Repaired 2 mismatch(es)"

    def test_repairs_single_session(self, writable_storage, capsys):
        ws = str(writable_storage / "ws_alpha")
        code, out, err = _run(
            ["repair", ws, "--session", SESS_DISK_ONLY, "--no-backup"], capsys)
        assert code == 0
        assert "added_to_db" in out

    def test_healthy_workspace_reports_zero(self, writable_storage, capsys):
        ws = str(writable_storage / "ws_beta")
        code, out, err = _run(["repair", ws, "--no-backup"], capsys)
        assert code == 0
        assert "0" in out


# ══════════════════════════════════════════════════════════════════════════════
# restore
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdRestore:

    @pytest.fixture
    def alpha_zip(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        return core.action_archive_workspace(ws, tmp_path / "arch")

    def test_restores_to_new_workspace(self, alpha_zip, tmp_path, capsys):
        ws = tmp_path / "new_ws"
        ws.mkdir()
        (ws / "workspace.json").write_text(
            json.dumps({"folder": "file:///C:/new"}))
        code, out, err = _run(
            ["restore", str(alpha_zip),
             str(ws), "--no-backup"], capsys)
        assert code == 0
        assert "Restored" in out

    def test_skips_existing_sessions(self, writable_storage, alpha_zip,
                                     capsys):
        ws = str(writable_storage / "ws_alpha")
        code, out, err = _run(
            ["restore", str(alpha_zip), ws, "--no-backup"], capsys)
        assert code == 0
        assert "Nothing restored" in out

    def test_empty_zip_returns_error(self, tmp_path, capsys):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(str(zip_path), "w"):
            pass
        ws = tmp_path / "ws"
        ws.mkdir()
        code, out, err = _run(
            ["restore", str(zip_path),
             str(ws), "--no-backup"], capsys)
        assert code != 0
        assert "ERROR" in err
