"""
tests/test_workspace_chat_browser.py

Unit tests for the pure (non-UI) helpers in workspace_chat_browser.py.
The tkinter stubs are installed by conftest.py before this module is imported.
"""

import json
import sqlite3
import time

import pytest

# conftest.py has already stubbed tkinter so the top-level import of
# tk / ttk / messagebox etc. succeeds without a display.
from vscode_chat_browser import workspace_chat_browser as wcb

# ===========================================================================
# _set_nested
# ===========================================================================


class TestSetNested:

    def test_single_key(self):
        obj = {}
        wcb._set_nested(obj, ["a"], 1)
        assert obj == {"a": 1}

    def test_nested_two_levels(self):
        obj = {}
        wcb._set_nested(obj, ["a", "b"], 42)
        assert obj == {"a": {"b": 42}}

    def test_nested_three_levels(self):
        obj = {}
        wcb._set_nested(obj, ["x", "y", "z"], "hello")
        assert obj["x"]["y"]["z"] == "hello"

    def test_overwrites_existing(self):
        obj = {"a": {"b": 1}}
        wcb._set_nested(obj, ["a", "b"], 99)
        assert obj["a"]["b"] == 99

    def test_non_dict_intermediate_is_ignored(self):
        obj = {"a": "not_a_dict"}
        wcb._set_nested(obj, ["a", "b"], 5)
        # should not raise; "a" stays unchanged
        assert obj["a"] == "not_a_dict"


# ===========================================================================
# _append_nested
# ===========================================================================


class TestAppendNested:

    def test_append_single_item(self):
        obj = {}
        wcb._append_nested(obj, ["items"], "x")
        assert obj == {"items": ["x"]}

    def test_append_list_extends(self):
        obj = {}
        wcb._append_nested(obj, ["items"], [1, 2, 3])
        assert obj["items"] == [1, 2, 3]

    def test_append_to_existing_list(self):
        obj = {"items": [1, 2]}
        wcb._append_nested(obj, ["items"], 3)
        assert obj["items"] == [1, 2, 3]

    def test_nested_path_intermediate_becomes_list(self):
        # _append_nested uses setdefault(k, []) for intermediate keys, so
        # "a" becomes a list and the final key can never be reached — the
        # function silently does nothing rather than raising.
        obj = {}
        wcb._append_nested(obj, ["a", "b"], "v")
        # "a" was created as an empty list; "b" was never set
        assert isinstance(obj["a"], list)
        assert obj["a"] == []

    def test_non_dict_intermediate_is_ignored(self):
        obj = {"a": "scalar"}
        wcb._append_nested(obj, ["a", "b"], "v")
        assert obj["a"] == "scalar"


# ===========================================================================
# replay_jsonl
# ===========================================================================


class TestReplayJsonl:

    def test_kind0_sets_initial_state(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text(
            json.dumps({
                "kind": 0,
                "v": {
                    "requests": [],
                    "title": "My Chat"
                }
            }) + "\n")
        state = wcb.replay_jsonl(p)
        assert state["title"] == "My Chat"
        assert state["requests"] == []

    def test_kind1_sets_property(self, tmp_path):
        p = tmp_path / "s.jsonl"
        lines = [
            json.dumps({
                "kind": 0,
                "v": {
                    "customTitle": ""
                }
            }),
            json.dumps({
                "kind": 1,
                "k": ["customTitle"],
                "v": "Renamed"
            }),
        ]
        p.write_text("\n".join(lines) + "\n")
        state = wcb.replay_jsonl(p)
        assert state["customTitle"] == "Renamed"

    def test_kind2_appends_to_list(self, tmp_path):
        p = tmp_path / "s.jsonl"
        lines = [
            json.dumps({
                "kind": 0,
                "v": {
                    "requests": []
                }
            }),
            json.dumps({
                "kind": 2,
                "k": ["requests"],
                "v": [{
                    "id": "r1"
                }]
            }),
            json.dumps({
                "kind": 2,
                "k": ["requests"],
                "v": [{
                    "id": "r2"
                }]
            }),
        ]
        p.write_text("\n".join(lines) + "\n")
        state = wcb.replay_jsonl(p)
        assert len(state["requests"]) == 2
        assert state["requests"][0]["id"] == "r1"

    def test_missing_file_returns_empty_dict(self, tmp_path):
        state = wcb.replay_jsonl(tmp_path / "nonexistent.jsonl")
        assert state == {}

    def test_blank_and_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text(
            json.dumps({
                "kind": 0,
                "v": {
                    "x": 1
                }
            }) + "\n"
            "\n"
            "NOT JSON\n" + json.dumps({
                "kind": 1,
                "k": ["x"],
                "v": 2
            }) + "\n")
        state = wcb.replay_jsonl(p)
        assert state["x"] == 2

    def test_full_roundtrip(self, tmp_path):
        p = tmp_path / "chat.jsonl"
        req = {
            "id": "req-1",
            "message": {
                "text": "Hello"
            },
            "timestamp": 1_700_000_000_000
        }
        lines = [
            json.dumps({
                "kind": 0,
                "v": {
                    "requests": [],
                    "customTitle": ""
                }
            }),
            json.dumps({
                "kind": 1,
                "k": ["customTitle"],
                "v": "Intro chat"
            }),
            json.dumps({
                "kind": 2,
                "k": ["requests"],
                "v": [req]
            }),
        ]
        p.write_text("\n".join(lines) + "\n")
        state = wcb.replay_jsonl(p)
        assert state["customTitle"] == "Intro chat"
        assert state["requests"][0]["id"] == "req-1"


# ===========================================================================
# workspace_display_name
# ===========================================================================


class TestWorkspaceDisplayName:

    def test_reads_folder_key(self, tmp_path):
        (tmp_path / "workspace.json").write_text(
            json.dumps({"folder": "file:///C:/projects/myapp"}))
        name, path = wcb.workspace_display_name(tmp_path)
        assert name == "myapp"
        assert "myapp" in path

    def test_reads_workspace_key_as_fallback(self, tmp_path):
        (tmp_path / "workspace.json").write_text(
            json.dumps(
                {"workspace":
                 "file:///C:/workspaces/monorepo.code-workspace"}))
        name, path = wcb.workspace_display_name(tmp_path)
        assert name == "monorepo.code-workspace"

    def test_missing_workspace_json_uses_dir_name(self, tmp_path):
        name, path = wcb.workspace_display_name(tmp_path)
        # falls back to first 12 chars of the directory stem
        assert name == tmp_path.name[:12]
        assert path == str(tmp_path)

    def test_malformed_json_falls_back(self, tmp_path):
        (tmp_path / "workspace.json").write_text("{ not json }")
        name, path = wcb.workspace_display_name(tmp_path)
        assert name == tmp_path.name[:12]

    def test_url_encoded_path_decoded(self, tmp_path):
        (tmp_path / "workspace.json").write_text(
            json.dumps({"folder": "file:///C:/my%20projects/cool%20app"}))
        name, path = wcb.workspace_display_name(tmp_path)
        assert "cool app" in path


# ===========================================================================
# session_file
# ===========================================================================


class TestSessionFile:

    def test_prefers_json_over_jsonl(self, tmp_path):
        cs = tmp_path / "chatSessions"
        cs.mkdir()
        uid = "abc123"
        (cs / f"{uid}.json").write_text("{}")
        (cs / f"{uid}.jsonl").write_text("")
        result = wcb.session_file(tmp_path, uid)
        assert result.suffix == ".json"

    def test_returns_jsonl_when_only_jsonl_present(self, tmp_path):
        cs = tmp_path / "chatSessions"
        cs.mkdir()
        uid = "abc123"
        (cs / f"{uid}.jsonl").write_text("")
        result = wcb.session_file(tmp_path, uid)
        assert result.suffix == ".jsonl"

    def test_returns_default_jsonl_when_neither_present(self, tmp_path):
        result = wcb.session_file(tmp_path, "missing-id")
        assert result.suffix == ".jsonl"
        assert result.name == "missing-id.jsonl"


# ===========================================================================
# _quick_scan_json
# ===========================================================================


class TestQuickScanJson:

    def test_reads_title_and_requests(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(
            json.dumps({
                "title":
                "My session",
                "requests": [{
                    "id": "r1",
                    "timestamp": 1_700_000_000_000
                }],
                "lastMessageDate":
                1_700_000_000_000,
            }))
        title, ts, has_req = wcb._quick_scan_json(p)
        assert title == "My session"
        assert ts == 1_700_000_000_000
        assert has_req is True

    def test_prefers_customTitle(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(
            json.dumps({
                "title": "Generic",
                "customTitle": "My Custom Title",
                "requests": [],
            }))
        title, _, _ = wcb._quick_scan_json(p)
        assert title == "My Custom Title"

    def test_empty_requests_has_requests_false(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(
            json.dumps({
                "title": "x",
                "requests": [],
                "lastMessageDate": 0
            }))
        _, _, has_req = wcb._quick_scan_json(p)
        assert has_req is False

    def test_falls_back_to_mtime_when_no_timestamp(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"requests": []}))
        _, ts, _ = wcb._quick_scan_json(p)
        expected = int(p.stat().st_mtime * 1000)
        assert abs(ts - expected) < 1000  # within 1 second

    def test_malformed_json_returns_defaults(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text("not json")
        title, ts, has_req = wcb._quick_scan_json(p)
        assert title == ""
        assert has_req is False
        assert ts > 0  # falls back to mtime


# ===========================================================================
# _quick_scan_jsonl
# ===========================================================================


class TestQuickScanJsonl:

    def _make_jsonl(self, tmp_path, lines):
        p = tmp_path / "s.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        return p

    def test_extracts_title_from_kind1(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {
                "kind": 0,
                "v": {}
            },
            {
                "kind": 1,
                "k": ["customTitle"],
                "v": "My Title"
            },
        ])
        title, _, _ = wcb._quick_scan_jsonl(p)
        assert title == "My Title"

    def test_extracts_last_timestamp_from_requests(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {
                "kind": 0,
                "v": {}
            },
            {
                "kind": 2,
                "k": ["requests"],
                "v": [{
                    "timestamp": 1_000
                }]
            },
            {
                "kind": 2,
                "k": ["requests"],
                "v": [{
                    "timestamp": 2_000
                }]
            },
        ])
        _, ts, has_req = wcb._quick_scan_jsonl(p)
        assert ts == 2_000
        assert has_req is True

    def test_has_requests_false_for_empty(self, tmp_path):
        p = self._make_jsonl(tmp_path, [{"kind": 0, "v": {}}])
        _, _, has_req = wcb._quick_scan_jsonl(p)
        assert has_req is False

    def test_falls_back_to_mtime(self, tmp_path):
        p = self._make_jsonl(tmp_path, [{"kind": 0, "v": {}}])
        _, ts, _ = wcb._quick_scan_jsonl(p)
        expected = int(p.stat().st_mtime * 1000)
        assert abs(ts - expected) < 1000

    def test_missing_file_returns_empty(self, tmp_path):
        title, ts, has_req = wcb._quick_scan_jsonl(tmp_path / "no.jsonl")
        assert title == ""
        assert ts == 0
        assert has_req is False


# ===========================================================================
# load_session_index
# ===========================================================================


def _make_storage(tmp_path, db_entries=None, disk_sessions=None):
    """
    Build a minimal workspaceStorage folder.

    db_entries  : {uid: entry_dict} written into state.vscdb
    disk_sessions: {uid: content_str} written as chatSessions/<uid>.jsonl
    """
    storage = tmp_path / "storage"
    storage.mkdir()
    cs = storage / "chatSessions"
    cs.mkdir()

    if db_entries:
        index = {"version": 1, "entries": db_entries}
        conn = sqlite3.connect(str(storage / "state.vscdb"))
        conn.execute(
            "CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("chat.ChatSessionStore.index", json.dumps(index)),
        )
        conn.commit()
        conn.close()

    if disk_sessions:
        for uid, content in disk_sessions.items():
            (cs / f"{uid}.jsonl").write_text(content)

    return storage


class TestLoadSessionIndex:

    def test_db_only_session_detected_as_mismatch(self, tmp_path):
        uid = "aaaa-1111"
        entries = {
            uid: {
                "title": "DB only",
                "lastMessageDate": 1_000,
                "isEmpty": False
            }
        }
        storage = _make_storage(tmp_path, db_entries=entries)
        sessions = wcb.load_session_index(storage)
        sess = next(s for s in sessions if s["id"] == uid)
        assert sess["source"] == "db"
        assert sess["mismatch_reason"] is not None

    def test_disk_only_session_detected_as_mismatch(self, tmp_path):
        uid = "bbbb-2222"
        content = (
            json.dumps({
                "kind": 0,
                "v": {
                    "requests": [{
                        "timestamp": 1_000,
                        "message": {
                            "text": "hi"
                        }
                    }],
                    "customTitle": "Disk Only"
                }
            }) + "\n" +
            json.dumps({
                "kind": 2,
                "k": ["requests"],
                "v": [{
                    "timestamp": 1_000,
                    "message": {
                        "text": "hi"
                    }
                }]
            }) + "\n")
        storage = _make_storage(tmp_path, disk_sessions={uid: content})
        sessions = wcb.load_session_index(storage)
        sess = next(s for s in sessions if s["id"] == uid)
        assert sess["source"] == "disk"
        assert sess["mismatch_reason"] is not None

    def test_both_healthy_session(self, tmp_path):
        uid = "cccc-3333"
        entries = {
            uid: {
                "title": "Healthy",
                "lastMessageDate": 2_000,
                "isEmpty": False
            }
        }
        disk = {
            uid:
            json.dumps({
                "kind": 0,
                "v": {
                    "requests": [],
                    "customTitle": "Healthy"
                }
            }) + "\n"
        }
        storage = _make_storage(tmp_path,
                                db_entries=entries,
                                disk_sessions=disk)
        sessions = wcb.load_session_index(storage)
        sess = next(s for s in sessions if s["id"] == uid)
        assert sess["source"] == "both"
        assert sess["mismatch_reason"] is None

    def test_empty_dir_returns_empty_list(self, tmp_path):
        storage = tmp_path / "empty"
        storage.mkdir()
        assert wcb.load_session_index(storage) == []

    def test_sorted_descending_by_timestamp(self, tmp_path):
        entries = {
            "id-old": {
                "title": "Old",
                "lastMessageDate": 1_000,
                "isEmpty": False
            },
            "id-new": {
                "title": "New",
                "lastMessageDate": 9_000,
                "isEmpty": False
            },
        }
        disk = {
            "id-old": json.dumps({
                "kind": 0,
                "v": {}
            }) + "\n",
            "id-new": json.dumps({
                "kind": 0,
                "v": {}
            }) + "\n",
        }
        storage = _make_storage(tmp_path,
                                db_entries=entries,
                                disk_sessions=disk)
        sessions = wcb.load_session_index(storage)
        ids = [s["id"] for s in sessions]
        assert ids.index("id-new") < ids.index("id-old")

    def test_isEmpty_db_entry_with_disk_file_is_mismatch(self, tmp_path):
        uid = "dddd-4444"
        entries = {
            uid: {
                "title": "Empty",
                "lastMessageDate": 0,
                "isEmpty": True
            }
        }
        disk = {uid: json.dumps({"kind": 0, "v": {}}) + "\n"}
        storage = _make_storage(tmp_path,
                                db_entries=entries,
                                disk_sessions=disk)
        sessions = wcb.load_session_index(storage)
        sess = next((s for s in sessions if s["id"] == uid), None)
        assert sess is not None
        assert sess["mismatch_reason"] is not None


# ===========================================================================
# load_requests
# ===========================================================================


class TestLoadRequests:

    def test_loads_from_json_snapshot(self, tmp_path):
        cs = tmp_path / "chatSessions"
        cs.mkdir()
        reqs = [{"id": "r1", "message": {"text": "Hi"}}]
        (cs / "sess.json").write_text(json.dumps({"requests": reqs}))
        result = wcb.load_requests(tmp_path, "sess")
        assert len(result) == 1
        assert result[0]["id"] == "r1"

    def test_loads_from_jsonl_replay(self, tmp_path):
        cs = tmp_path / "chatSessions"
        cs.mkdir()
        lines = [
            json.dumps({
                "kind": 0,
                "v": {
                    "requests": []
                }
            }),
            json.dumps({
                "kind": 2,
                "k": ["requests"],
                "v": [{
                    "id": "r2"
                }]
            }),
        ]
        (cs / "sess.jsonl").write_text("\n".join(lines) + "\n")
        result = wcb.load_requests(tmp_path, "sess")
        assert result[0]["id"] == "r2"

    def test_missing_session_returns_empty_list(self, tmp_path):
        result = wcb.load_requests(tmp_path, "nonexistent")
        assert result == []

    def test_malformed_json_snapshot_returns_empty(self, tmp_path):
        cs = tmp_path / "chatSessions"
        cs.mkdir()
        (cs / "sess.json").write_text("INVALID")
        assert wcb.load_requests(tmp_path, "sess") == []


# ===========================================================================
# extract_user_text
# ===========================================================================


class TestExtractUserText:

    def test_message_dict(self):
        req = {"message": {"text": "Hello world"}}
        assert wcb.extract_user_text(req) == "Hello world"

    def test_message_string(self):
        req = {"message": "plain string"}
        assert wcb.extract_user_text(req) == "plain string"

    def test_missing_message(self):
        assert wcb.extract_user_text({}) == ""

    def test_message_dict_missing_text(self):
        assert wcb.extract_user_text({"message": {}}) == ""


# ===========================================================================
# extract_response_text
# ===========================================================================


class TestExtractResponseText:

    def test_collects_items_without_kind(self):
        req = {
            "response": [
                {
                    "value": "First paragraph."
                },
                {
                    "kind": "thinking",
                    "value": "reasoning..."
                },
                {
                    "value": "Second paragraph."
                },
            ]
        }
        text = wcb.extract_response_text(req)
        assert "First paragraph." in text
        assert "Second paragraph." in text
        assert "reasoning" not in text

    def test_skips_blank_values(self):
        req = {"response": [{"value": "  "}, {"value": "real"}]}
        assert wcb.extract_response_text(req) == "real"

    def test_no_response_key(self):
        assert wcb.extract_response_text({}) == ""

    def test_joined_with_double_newline(self):
        req = {"response": [{"value": "A"}, {"value": "B"}]}
        assert wcb.extract_response_text(req) == "A\n\nB"


# ===========================================================================
# extract_thinking_text
# ===========================================================================


class TestExtractThinkingText:

    def test_collects_thinking_items(self):
        req = {
            "response": [
                {
                    "value": "normal"
                },
                {
                    "kind": "thinking",
                    "value": "I reasoned about X."
                },
            ]
        }
        text = wcb.extract_thinking_text(req)
        assert "I reasoned about X." in text
        assert "normal" not in text

    def test_no_thinking_blocks(self):
        req = {"response": [{"value": "answer"}]}
        assert wcb.extract_thinking_text(req) == ""

    def test_multiple_thinking_blocks_joined(self):
        req = {
            "response": [
                {
                    "kind": "thinking",
                    "value": "Step 1"
                },
                {
                    "kind": "thinking",
                    "value": "Step 2"
                },
            ]
        }
        result = wcb.extract_thinking_text(req)
        assert result == "Step 1\n\nStep 2"


# ===========================================================================
# fmt_ts / fmt_mtime
# ===========================================================================


class TestFmtTs:

    def test_formats_known_timestamp(self):
        # 2024-01-15 00:00:00 UTC → local time may differ; just check structure
        result = wcb.fmt_ts(1_705_276_800_000)
        assert len(result) == 16  # "YYYY-MM-DD HH:MM"
        assert result[4] == "-"

    def test_zero_returns_empty_string(self):
        assert wcb.fmt_ts(0) == ""

    def test_none_returns_empty_string(self):
        assert wcb.fmt_ts(None) == ""


class TestFmtMtime:

    def test_formats_current_time(self):
        result = wcb.fmt_mtime(time.time())
        assert len(result) == 16
        assert result[4] == "-"

    def test_zero_returns_empty_string(self):
        assert wcb.fmt_mtime(0) == ""

    def test_none_zero_float(self):
        assert wcb.fmt_mtime(0.0) == ""
