"""
test_core.py

Tests for src/core.py — pure data functions and all action functions.

Fixture layout (see conftest.py):
  storage_root/ws_alpha  — JSONL sessions; two mismatches
  storage_root/ws_beta   — JSON  session;  all healthy
"""

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from vscode_chat_browser import core
from conftest import (
    SESS_ALPHA_JSONL,
    SESS_BETA_JSON,
    SESS_DB_ONLY,
    SESS_DISK_ONLY,
)

# ══════════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════════


def _read_db_index(ws_dir: Path) -> dict:
    """Convenience: read the raw index dict from a state.vscdb."""
    return core._db_read_index(ws_dir / "state.vscdb")


# ══════════════════════════════════════════════════════════════════════════════
# _set_nested / _append_nested / replay_jsonl
# ══════════════════════════════════════════════════════════════════════════════


class TestSetNested:

    def test_top_level(self):
        d = {}
        core._set_nested(d, ["key"], "val")
        assert d == {"key": "val"}

    def test_nested_creates_dicts(self):
        d = {}
        core._set_nested(d, ["a", "b", "c"], 99)
        assert d == {"a": {"b": {"c": 99}}}

    def test_overwrites_existing(self):
        d = {"x": "old"}
        core._set_nested(d, ["x"], "new")
        assert d["x"] == "new"

    def test_non_dict_intermediate_is_noop(self):
        d = {"a": "string"}
        core._set_nested(d, ["a", "b"], "val")
        assert d["a"] == "string"

    def test_single_key_list_value(self):
        d = {}
        core._set_nested(d, ["items"], [1, 2, 3])
        assert d["items"] == [1, 2, 3]


class TestAppendNested:

    def test_appends_list(self):
        d = {"items": []}
        core._append_nested(d, ["items"], [1, 2])
        assert d["items"] == [1, 2]

    def test_creates_missing_key(self):
        d = {}
        core._append_nested(d, ["items"], [42])
        assert d["items"] == [42]

    def test_extends_existing(self):
        d = {"items": [1]}
        core._append_nested(d, ["items"], [2, 3])
        assert d["items"] == [1, 2, 3]

    def test_appends_dict(self):
        d = {"items": []}
        core._append_nested(d, ["items"], {"id": "x"})
        assert d["items"] == [{"id": "x"}]

    def test_intermediate_non_dict_is_noop(self):
        d = {"a": "string"}
        core._append_nested(d, ["a", "items"], [1])
        assert d["a"] == "string"


class TestReplayJsonl:

    def test_replays_alpha_fixture(self):
        p = (Path(__file__).parent / "fixtures" / "sessions" /
             "aaaa-0001.jsonl")
        state = core.replay_jsonl(p)
        assert state.get("customTitle") == "Alpha Chat One"
        reqs = state.get("requests", [])
        assert len(reqs) == 2
        assert reqs[0]["id"] == "req-1"

    def test_replays_disk_only_fixture(self):
        p = (Path(__file__).parent / "fixtures" / "sessions" /
             "bbbb-0002.jsonl")
        state = core.replay_jsonl(p)
        assert state.get("customTitle") == "Alpha Chat Two (disk only)"
        assert len(state.get("requests", [])) == 1

    def test_missing_file_returns_empty(self, tmp_path):
        state = core.replay_jsonl(tmp_path / "nonexistent.jsonl")
        assert state == {}

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text(
            '{"kind": 0, "v": {"requests": [], "customTitle": ""}}\n'
            "NOT_JSON\n"
            '{"kind": 1, "k": ["customTitle"], "v": "title"}\n',
            encoding="utf-8",
        )
        state = core.replay_jsonl(p)
        assert state.get("customTitle") == "title"


# ══════════════════════════════════════════════════════════════════════════════
# _quick_scan_json / _quick_scan_jsonl
# ══════════════════════════════════════════════════════════════════════════════


class TestQuickScanJson:

    def test_scans_beta_fixture(self):
        p = (Path(__file__).parent / "fixtures" / "sessions" /
             "cccc-0003.json")
        title, ts, has_req = core._quick_scan_json(p)
        assert title == "Beta Chat One"
        assert ts == 1700000020000
        assert has_req is True

    def test_missing_file(self, tmp_path):
        title, ts, has_req = core._quick_scan_json(tmp_path / "missing.json")
        assert title == ""
        assert not has_req

    def test_empty_requests(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(
            json.dumps({
                "sessionId": "x",
                "customTitle": "Empty",
                "lastMessageDate": 1000,
                "requests": [],
            }),
            encoding="utf-8",
        )
        title, ts, has_req = core._quick_scan_json(p)
        assert title == "Empty"
        assert has_req is False


class TestQuickScanJsonl:

    def test_scans_alpha_fixture(self):
        p = (Path(__file__).parent / "fixtures" / "sessions" /
             "aaaa-0001.jsonl")
        title, ts, has_req = core._quick_scan_jsonl(p)
        assert title == "Alpha Chat One"
        assert ts == 1700000002000
        assert has_req is True

    def test_scans_disk_only_fixture(self):
        p = (Path(__file__).parent / "fixtures" / "sessions" /
             "bbbb-0002.jsonl")
        title, ts, has_req = core._quick_scan_jsonl(p)
        assert title == "Alpha Chat Two (disk only)"
        assert ts == 1700000010000
        assert has_req is True

    def test_empty_file(self, tmp_path):
        p = tmp_path / "e.jsonl"
        p.write_bytes(b"")
        title, ts, has_req = core._quick_scan_jsonl(p)
        assert title == ""
        assert has_req is False


# ══════════════════════════════════════════════════════════════════════════════
# workspace_display_name / session_file / fmt_ts / fmt_mtime
# ══════════════════════════════════════════════════════════════════════════════


class TestWorkspaceDisplayName:

    def test_alpha_workspace(self, storage_root):
        name, path = core.workspace_display_name(storage_root / "ws_alpha")
        assert name == "alpha"
        assert "alpha" in path.lower()

    def test_beta_workspace(self, storage_root):
        name, path = core.workspace_display_name(storage_root / "ws_beta")
        assert name == "beta"

    def test_missing_workspace_json(self, tmp_path):
        name, path = core.workspace_display_name(tmp_path)
        # Falls back to first 12 chars of dir name
        assert len(name) <= 12

    def test_folder_key(self, tmp_path):
        (tmp_path / "workspace.json").write_text(
            json.dumps({"folder": "file:///home/user/myproject"}),
            encoding="utf-8",
        )
        name, path = core.workspace_display_name(tmp_path)
        assert name == "myproject"


class TestSessionFile:

    def test_returns_jsonl_path_when_present(self, storage_root):
        p = core.session_file(storage_root / "ws_alpha", SESS_ALPHA_JSONL)
        assert p.suffix == ".jsonl"
        assert p.exists()

    def test_prefers_json_over_jsonl(self, tmp_path):
        cs = tmp_path / "chatSessions"
        cs.mkdir()
        (cs / "s.json").write_text("{}")
        (cs / "s.jsonl").write_text("")
        p = core.session_file(tmp_path, "s")
        assert p.suffix == ".json"

    def test_missing_returns_jsonl_path(self, tmp_path):
        p = core.session_file(tmp_path, "nonexistent")
        assert p.suffix == ".jsonl"
        assert not p.exists()


class TestFmtTs:

    def test_formats_correctly(self):
        s = core.fmt_ts(1700000000000)
        assert "2023" in s

    def test_zero_returns_empty(self):
        assert core.fmt_ts(0) == ""

    def test_none_returns_empty(self):
        assert core.fmt_ts(None) == ""


class TestFmtMtime:

    def test_formats_float(self):
        s = core.fmt_mtime(1700000000.0)
        assert "2023" in s

    def test_zero_returns_empty(self):
        assert core.fmt_mtime(0.0) == ""


# ══════════════════════════════════════════════════════════════════════════════
# load_session_index
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadSessionIndex:

    def test_ws_alpha_returns_three_sessions(self, storage_root):
        sessions = core.load_session_index(storage_root / "ws_alpha")
        ids = {s["id"] for s in sessions}
        assert SESS_ALPHA_JSONL in ids
        assert SESS_DISK_ONLY in ids
        assert SESS_DB_ONLY in ids

    def test_healthy_session_has_no_mismatch(self, storage_root):
        sessions = core.load_session_index(storage_root / "ws_alpha")
        alpha = next(s for s in sessions if s["id"] == SESS_ALPHA_JSONL)
        assert alpha["mismatch_reason"] is None
        assert alpha["source"] == "both"
        assert alpha["has_requests"] is True

    def test_disk_only_session_flagged(self, storage_root):
        sessions = core.load_session_index(storage_root / "ws_alpha")
        disk = next(s for s in sessions if s["id"] == SESS_DISK_ONLY)
        assert disk["mismatch_reason"] is not None
        assert disk["source"] == "disk"

    def test_db_only_session_flagged(self, storage_root):
        sessions = core.load_session_index(storage_root / "ws_alpha")
        db_only = next(s for s in sessions if s["id"] == SESS_DB_ONLY)
        assert db_only["mismatch_reason"] is not None
        assert db_only["source"] == "db"

    def test_ws_beta_returns_healthy_json_session(self, storage_root):
        sessions = core.load_session_index(storage_root / "ws_beta")
        assert len(sessions) == 1
        s = sessions[0]
        assert s["id"] == SESS_BETA_JSON
        assert s["mismatch_reason"] is None
        assert s["source"] == "both"

    def test_empty_dir_returns_empty_list(self, tmp_path):
        result = core.load_session_index(tmp_path)
        assert result == []

    def test_sorted_by_timestamp_descending(self, storage_root):
        sessions = core.load_session_index(storage_root / "ws_alpha")
        timestamps = [s["ts"] for s in sessions]
        assert timestamps == sorted(timestamps, reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# load_requests / extract_* helpers
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadRequests:

    def test_alpha_jsonl_has_two_requests(self, storage_root):
        reqs = core.load_requests(storage_root / "ws_alpha", SESS_ALPHA_JSONL)
        assert len(reqs) == 2

    def test_beta_json_has_one_request(self, storage_root):
        reqs = core.load_requests(storage_root / "ws_beta", SESS_BETA_JSON)
        assert len(reqs) == 1

    def test_missing_session_returns_empty(self, storage_root):
        reqs = core.load_requests(storage_root / "ws_alpha", "no-such-id")
        assert reqs == []


class TestExtractUserText:

    def test_dict_message(self):
        req = {"message": {"text": "hello"}}
        assert core.extract_user_text(req) == "hello"

    def test_string_message(self):
        req = {"message": "plain text"}
        assert core.extract_user_text(req) == "plain text"

    def test_missing_message(self):
        assert core.extract_user_text({}) == ""


class TestExtractResponseText:

    def test_collects_plain_values(self):
        req = {
            "response": [
                {
                    "value": "First part."
                },
                {
                    "value": "Second part."
                },
            ]
        }
        text = core.extract_response_text(req)
        assert "First part." in text
        assert "Second part." in text

    def test_excludes_thinking_blocks(self):
        req = {
            "response": [
                {
                    "value": "Real answer"
                },
                {
                    "kind": "thinking",
                    "value": "Private reasoning"
                },
            ]
        }
        text = core.extract_response_text(req)
        assert "Real answer" in text
        assert "Private reasoning" not in text

    def test_empty_response(self):
        assert core.extract_response_text({"response": []}) == ""


class TestExtractThinkingText:

    def test_collects_thinking_blocks(self):
        req = {
            "response": [
                {
                    "value": "Real answer"
                },
                {
                    "kind": "thinking",
                    "value": "My reasoning"
                },
            ]
        }
        text = core.extract_thinking_text(req)
        assert "My reasoning" in text
        assert "Real answer" not in text

    def test_no_thinking_returns_empty(self):
        req = {"response": [{"value": "Just text"}]}
        assert core.extract_thinking_text(req) == ""

    def test_alpha_req2_has_thinking(self, storage_root):
        reqs = core.load_requests(storage_root / "ws_alpha", SESS_ALPHA_JSONL)
        # req-2 has a thinking block
        thinking = core.extract_thinking_text(reqs[1])
        assert "capabilities" in thinking.lower()


# ══════════════════════════════════════════════════════════════════════════════
# _make_db_entry
# ══════════════════════════════════════════════════════════════════════════════


class TestMakeDbEntry:

    def _sample_sess(self):
        return {
            "id": "test-uuid",
            "title": "My Session",
            "ts": 1700000001000,
            "has_requests": True,
            "file_ctime": 1700000000.0,
        }

    def test_produces_required_fields(self):
        entry = core._make_db_entry(self._sample_sess())
        for field in (
                "sessionId",
                "title",
                "lastMessageDate",
                "timing",
                "initialLocation",
                "hasPendingEdits",
                "isEmpty",
                "isExternal",
                "lastResponseState",
        ):
            assert field in entry, f"Missing field: {field}"

    def test_isEmpty_is_false(self):
        entry = core._make_db_entry(self._sample_sess())
        assert entry["isEmpty"] is False

    def test_session_id_matches(self):
        entry = core._make_db_entry(self._sample_sess())
        assert entry["sessionId"] == "test-uuid"

    def test_title_preserved(self):
        entry = core._make_db_entry(self._sample_sess())
        assert entry["title"] == "My Session"

    def test_timing_uses_file_ctime(self):
        entry = core._make_db_entry(self._sample_sess())
        assert entry["timing"]["created"] == 1700000000000


# ══════════════════════════════════════════════════════════════════════════════
# action_archive_session / action_archive_workspace
# ══════════════════════════════════════════════════════════════════════════════


class TestActionArchiveSession:

    def test_creates_zip(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        dest = tmp_path / "archives"
        zip_path = core.action_archive_session(ws, SESS_ALPHA_JSONL, dest)
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

    def test_zip_contains_session_file(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        dest = tmp_path / "archives"
        zip_path = core.action_archive_session(ws, SESS_ALPHA_JSONL, dest)
        with zipfile.ZipFile(str(zip_path)) as zf:
            names = zf.namelist()
        assert any(SESS_ALPHA_JSONL in n for n in names)

    def test_unknown_session_raises(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        with pytest.raises(RuntimeError):
            core.action_archive_session(ws, "no-such-id", tmp_path)

    def test_db_only_session_raises(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        with pytest.raises(RuntimeError):
            core.action_archive_session(ws, SESS_DB_ONLY, tmp_path)

    def test_creates_dest_dir_if_missing(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        dest = tmp_path / "new" / "nested" / "dir"
        zip_path = core.action_archive_session(ws, SESS_ALPHA_JSONL, dest)
        assert dest.is_dir()
        assert zip_path.exists()


class TestActionArchiveWorkspace:

    def test_creates_zip(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        dest = tmp_path / "archives"
        zip_path = core.action_archive_workspace(ws, dest)
        assert zip_path.exists()

    def test_zip_contains_all_session_files(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_alpha"
        dest = tmp_path / "archives"
        zip_path = core.action_archive_workspace(ws, dest)
        with zipfile.ZipFile(str(zip_path)) as zf:
            names = zf.namelist()
        # Both on-disk sessions should be in the archive
        assert any(SESS_ALPHA_JSONL in n for n in names)
        assert any(SESS_DISK_ONLY in n for n in names)

    def test_empty_workspace_raises(self, tmp_path):
        ws = tmp_path / "empty_ws"
        ws.mkdir()
        with pytest.raises(RuntimeError):
            core.action_archive_workspace(ws, tmp_path / "out")

    def test_json_workspace_creates_zip(self, writable_storage, tmp_path):
        ws = writable_storage / "ws_beta"
        dest = tmp_path / "archives"
        zip_path = core.action_archive_workspace(ws, dest)
        with zipfile.ZipFile(str(zip_path)) as zf:
            names = zf.namelist()
        assert any(SESS_BETA_JSON in n for n in names)


# ══════════════════════════════════════════════════════════════════════════════
# action_delete_session / action_delete_workspace_chats
# ══════════════════════════════════════════════════════════════════════════════


class TestActionDeleteSession:

    def test_removes_file(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        sf = core.session_file(ws, SESS_ALPHA_JSONL)
        assert sf.exists()
        core.action_delete_session(ws, SESS_ALPHA_JSONL, backup=False)
        assert not sf.exists()

    def test_removes_from_db(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        core.action_delete_session(ws, SESS_ALPHA_JSONL, backup=False)
        idx = _read_db_index(ws)
        assert SESS_ALPHA_JSONL not in idx["entries"]

    def test_backup_created(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        before = list(ws.glob("state.vscdb.*"))
        core.action_delete_session(ws, SESS_ALPHA_JSONL, backup=True)
        after = list(ws.glob("state.vscdb.*"))
        assert len(after) > len(before)

    def test_no_backup_when_disabled(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        core.action_delete_session(ws, SESS_ALPHA_JSONL, backup=False)
        assert not list(ws.glob("state.vscdb.*-backup-*"))

    def test_disk_only_session_file_removed(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        sf = core.session_file(ws, SESS_DISK_ONLY)
        assert sf.exists()
        core.action_delete_session(ws, SESS_DISK_ONLY, backup=False)
        assert not sf.exists()

    def test_missing_session_is_safe(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        # Should not raise even if session ID doesn't exist anywhere
        core.action_delete_session(ws, "no-such-id", backup=False)


class TestActionDeleteWorkspaceChats:

    def test_removes_all_files(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        cs = ws / "chatSessions"
        core.action_delete_workspace_chats(ws, backup=False)
        remaining = list(cs.glob("*.json")) + list(cs.glob("*.jsonl"))
        assert remaining == []

    def test_clears_db_entries(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        core.action_delete_workspace_chats(ws, backup=False)
        idx = _read_db_index(ws)
        assert idx["entries"] == {}

    def test_returns_count(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        cs = ws / "chatSessions"
        n_files = len(list(cs.glob("*.json")) + list(cs.glob("*.jsonl")))
        n = core.action_delete_workspace_chats(ws, backup=False)
        assert n == n_files

    def test_backup_created(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        before = list(ws.glob("state.vscdb.*"))
        core.action_delete_workspace_chats(ws, backup=True)
        after = list(ws.glob("state.vscdb.*"))
        assert len(after) > len(before)


# ══════════════════════════════════════════════════════════════════════════════
# action_copy_sessions
# ══════════════════════════════════════════════════════════════════════════════


class TestActionCopySessions:

    def test_copies_file_to_destination(self, writable_storage):
        src = writable_storage / "ws_alpha"
        dst = writable_storage / "ws_beta"
        copied = core.action_copy_sessions(src,
                                           dst, [SESS_ALPHA_JSONL],
                                           backup=False)
        assert SESS_ALPHA_JSONL in copied
        dest_file = dst / "chatSessions" / f"{SESS_ALPHA_JSONL}.jsonl"
        assert dest_file.exists()

    def test_updates_destination_db(self, writable_storage):
        src = writable_storage / "ws_alpha"
        dst = writable_storage / "ws_beta"
        core.action_copy_sessions(src, dst, [SESS_ALPHA_JSONL], backup=False)
        idx = _read_db_index(dst)
        assert SESS_ALPHA_JSONL in idx["entries"]

    def test_multiple_sessions_copied(self, writable_storage):
        src = writable_storage / "ws_alpha"
        dst = writable_storage / "ws_beta"
        copied = core.action_copy_sessions(src,
                                           dst,
                                           [SESS_ALPHA_JSONL, SESS_DISK_ONLY],
                                           backup=False)
        assert set(copied) == {SESS_ALPHA_JSONL, SESS_DISK_ONLY}

    def test_db_only_session_not_copied_to_disk(self, writable_storage):
        src = writable_storage / "ws_alpha"
        dst = writable_storage / "ws_beta"
        # SESS_DB_ONLY has no file → action silently skips it
        copied = core.action_copy_sessions(src,
                                           dst, [SESS_DB_ONLY],
                                           backup=False)
        assert SESS_DB_ONLY not in copied

    def test_unknown_session_raises(self, writable_storage):
        src = writable_storage / "ws_alpha"
        dst = writable_storage / "ws_beta"
        with pytest.raises(RuntimeError):
            core.action_copy_sessions(src, dst, ["bad-id"], backup=False)

    def test_copy_to_new_workspace_creates_db(self, writable_storage,
                                              tmp_path):
        src = writable_storage / "ws_alpha"
        dst = tmp_path / "new_ws"
        dst.mkdir()
        (dst / "workspace.json").write_text(
            json.dumps({"folder": "file:///C:/new"}))
        copied = core.action_copy_sessions(src,
                                           dst, [SESS_ALPHA_JSONL],
                                           backup=False)
        assert SESS_ALPHA_JSONL in copied
        assert (dst / "state.vscdb").exists()


# ══════════════════════════════════════════════════════════════════════════════
# action_repair_session / action_repair_all
# ══════════════════════════════════════════════════════════════════════════════


class TestActionRepairSession:

    def test_disk_only_session_added_to_db(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        result = core.action_repair_session(ws, SESS_DISK_ONLY, backup=False)
        assert result == "added_to_db"
        idx = _read_db_index(ws)
        assert SESS_DISK_ONLY in idx["entries"]
        assert idx["entries"][SESS_DISK_ONLY]["isEmpty"] is False

    def test_db_only_session_marked_empty(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        result = core.action_repair_session(ws, SESS_DB_ONLY, backup=False)
        assert result == "marked_empty"
        idx = _read_db_index(ws)
        assert idx["entries"][SESS_DB_ONLY]["isEmpty"] is True

    def test_healthy_session_returns_already_in_sync(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        result = core.action_repair_session(ws, SESS_ALPHA_JSONL, backup=False)
        assert result == "already_in_sync"

    def test_unknown_session_raises(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        with pytest.raises(RuntimeError):
            core.action_repair_session(ws, "no-such-id", backup=False)

    def test_backup_created(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        before = list(ws.glob("state.vscdb.*"))
        core.action_repair_session(ws, SESS_DISK_ONLY, backup=True)
        after = list(ws.glob("state.vscdb.*"))
        assert len(after) > len(before)


class TestActionRepairAll:

    def test_repairs_both_mismatches(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        n = core.action_repair_all(ws, backup=False)
        assert n == 2  # disk-only + db-only

    def test_disk_only_added_to_db_after_repair(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        core.action_repair_all(ws, backup=False)
        idx = _read_db_index(ws)
        assert SESS_DISK_ONLY in idx["entries"]
        assert idx["entries"][SESS_DISK_ONLY]["isEmpty"] is False

    def test_db_only_marked_empty_after_repair(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        core.action_repair_all(ws, backup=False)
        idx = _read_db_index(ws)
        assert idx["entries"][SESS_DB_ONLY]["isEmpty"] is True

    def test_healthy_workspace_returns_zero(self, writable_storage):
        ws = writable_storage / "ws_beta"
        n = core.action_repair_all(ws, backup=False)
        assert n == 0

    def test_backup_created_once(self, writable_storage):
        ws = writable_storage / "ws_alpha"
        before = list(ws.glob("state.vscdb.*"))
        core.action_repair_all(ws, backup=True)
        after = list(ws.glob("state.vscdb.*"))
        assert len(after) == len(before) + 1

    def test_missing_db_raises(self, tmp_path):
        ws = tmp_path / "ws"
        cs = ws / "chatSessions"
        cs.mkdir(parents=True)
        p = cs / "sess.jsonl"
        p.write_text(
            '{"kind":0,"v":{"requests":[],"customTitle":""}}\n'
            '{"kind":1,"k":["customTitle"],"v":"T"}\n'
            '{"kind":2,"k":["requests"],"v":[{"id":"r","timestamp":1,"message":{"text":"q"},"response":[{"value":"a"}]}]}\n',
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError):
            core.action_repair_all(ws, backup=False)


# ══════════════════════════════════════════════════════════════════════════════
# action_restore_archive
# ══════════════════════════════════════════════════════════════════════════════


class TestActionRestoreArchive:

    @pytest.fixture
    def alpha_archive(self, writable_storage, tmp_path):
        """Archive ws_alpha first, then return the zip path."""
        ws = writable_storage / "ws_alpha"
        dest = tmp_path / "archives"
        return core.action_archive_workspace(ws, dest)

    def test_restores_sessions_to_new_workspace(self, alpha_archive, tmp_path):
        ws = tmp_path / "new_ws"
        ws.mkdir()
        (ws / "workspace.json").write_text(
            json.dumps({"folder": "file:///C:/restored"}))
        restored = core.action_restore_archive(alpha_archive, ws, backup=False)
        assert len(restored) == 2
        cs = ws / "chatSessions"
        assert any(cs.glob("*.jsonl"))

    def test_restored_sessions_in_db(self, alpha_archive, tmp_path):
        ws = tmp_path / "new_ws"
        ws.mkdir()
        (ws / "workspace.json").write_text(
            json.dumps({"folder": "file:///C:/restored"}))
        restored = core.action_restore_archive(alpha_archive, ws, backup=False)
        idx = core._db_read_index(ws / "state.vscdb")
        for sid in restored:
            assert sid in idx["entries"]
            assert idx["entries"][sid]["isEmpty"] is False

    def test_skips_already_existing_sessions(self, writable_storage,
                                             alpha_archive):
        # ws_alpha already has aaaa-0001 — restore to same ws should skip it
        ws = writable_storage / "ws_alpha"
        restored = core.action_restore_archive(alpha_archive, ws, backup=False)
        # aaaa-0001 and bbbb-0002 already exist on disk → both skipped
        for sid in [SESS_ALPHA_JSONL, SESS_DISK_ONLY]:
            assert sid not in restored

    def test_empty_zip_raises(self, tmp_path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(str(zip_path), "w"):
            pass
        ws = tmp_path / "ws"
        ws.mkdir()
        with pytest.raises(RuntimeError):
            core.action_restore_archive(zip_path, ws, backup=False)

    def test_backup_created_when_db_exists(self, writable_storage,
                                           alpha_archive):
        ws = writable_storage / "ws_beta"
        before = list(ws.glob("state.vscdb.*"))
        core.action_restore_archive(alpha_archive, ws, backup=True)
        after = list(ws.glob("state.vscdb.*"))
        assert len(after) > len(before)
