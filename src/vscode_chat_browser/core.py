"""
core.py

Pure business logic for the VS Code Chat Browser.
No GUI dependencies — import from tests, the CLI, or the Tkinter app.

Public API
----------
Data helpers (read-only):
    replay_jsonl, load_session_index, load_requests,
    workspace_display_name, session_file,
    extract_user_text, extract_response_text, extract_thinking_text,
    fmt_ts, fmt_mtime

Actions (mutate filesystem / DB):
    action_archive_session, action_archive_workspace,
    action_delete_session, action_delete_workspace_chats,
    action_copy_sessions,
    action_repair_session, action_repair_all,
    action_restore_archive
"""

import json
import os
import re
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

WORKSPACESTORAGE = Path(os.environ.get(
    "APPDATA", "")) / "Code" / "User" / "workspaceStorage"

# ── JSONL replay ──────────────────────────────────────────────────────────────


def _set_nested(obj: dict, keys: list, val) -> None:
    for k in keys[:-1]:
        if isinstance(obj, dict):
            obj = obj.setdefault(k, {})
        else:
            return
    if isinstance(obj, dict):
        obj[keys[-1]] = val


def _append_nested(obj: dict, keys: list, val) -> None:
    for k in keys[:-1]:
        if isinstance(obj, dict):
            obj = obj.setdefault(k, [])
        else:
            return
    if isinstance(obj, dict):
        arr = obj.setdefault(keys[-1], [])
        if isinstance(val, list):
            arr.extend(val)
        else:
            arr.append(val)


def replay_jsonl(path: Path) -> dict:
    """Reconstruct session state by replaying the JSONL log."""
    state: dict = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = obj.get("kind")
                if kind == 0:
                    state = obj.get("v", {})
                elif kind == 1 and obj.get("k"):
                    _set_nested(state, obj["k"], obj.get("v"))
                elif kind == 2 and obj.get("k"):
                    _append_nested(state, obj["k"], obj.get("v"))
    except OSError:
        pass
    return state


# ── data helpers ──────────────────────────────────────────────────────────────


def workspace_display_name(storage_dir: Path) -> tuple[str, str]:
    """Return (short_name, full_path_string) from workspace.json."""
    wj = storage_dir / "workspace.json"
    if wj.exists():
        try:
            data = json.loads(wj.read_text(encoding="utf-8"))
            for key in ("folder", "workspace"):
                if key in data:
                    decoded = unquote(str(data[key]))
                    for prefix in ("file:///", "file://"):
                        if decoded.lower().startswith(prefix):
                            decoded = decoded[len(prefix):]
                            break
                    decoded = decoded.replace("/", os.sep)
                    name = Path(decoded).name or storage_dir.name[:12]
                    return name, decoded
        except Exception:
            pass
    return storage_dir.name[:12], str(storage_dir)


def session_file(storage_dir: Path, session_id: str) -> Path:
    """Return the session file path, preferring .json over .jsonl."""
    for ext in (".json", ".jsonl"):
        p = storage_dir / "chatSessions" / f"{session_id}{ext}"
        if p.exists():
            return p
    return storage_dir / "chatSessions" / f"{session_id}.jsonl"


def _quick_scan_json(path: Path) -> tuple[str, int, bool]:
    """Fast extraction from a direct-snapshot .json session file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        title = (data.get("customTitle") or data.get("title") or "").strip()
        reqs = data.get("requests", [])
        has_requests = bool(reqs)
        last_ts = data.get("lastMessageDate", 0) or 0
        if not last_ts:
            for r in reqs:
                t = r.get("timestamp", 0)
                if t and t > last_ts:
                    last_ts = t
        if not last_ts:
            last_ts = int(path.stat().st_mtime * 1000)
        return title, last_ts, has_requests
    except Exception:
        ts = int(path.stat().st_mtime * 1000) if path.exists() else 0
        return "", ts, False


def _quick_scan_jsonl(path: Path) -> tuple[str, int, bool]:
    """
    Fast single-pass scan of a JSONL file.
    Returns (title, timestamp_ms, has_requests).
    """
    title = ""
    last_ts = 0
    has_requests = False
    try:
        mtime_ms = int(path.stat().st_mtime * 1000)
        with open(path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = obj.get("kind")
                if kind == 1 and obj.get("k") == ["customTitle"]:
                    v = obj.get("v", "")
                    if isinstance(v, str) and v.strip():
                        title = v.strip()
                elif kind == 2 and obj.get("k") == ["requests"]:
                    appended = obj.get("v", [])
                    if isinstance(appended, list):
                        for req in appended:
                            if isinstance(req, dict):
                                t = req.get("timestamp", 0)
                                if t and t > last_ts:
                                    last_ts = t
                                has_requests = True
                    elif isinstance(appended, dict):
                        t = appended.get("timestamp", 0)
                        if t and t > last_ts:
                            last_ts = t
                        has_requests = True
        if not last_ts:
            last_ts = mtime_ms
    except OSError:
        pass
    return title, last_ts, has_requests


def load_session_index(storage_dir: Path) -> list[dict]:
    """
    Build the session list, tracking each session's data source and any
    index mismatches.  Each returned dict has:
      id, title, ts, has_requests,
      source          : 'db' | 'disk' | 'both'
      file_ctime      : float (0 if no file on disk)
      mismatch_reason : str or None  (None = healthy)
      db_entry        : raw DB dict or None
    """
    known: dict[str, dict] = {}
    db_all_ids: set[str] = set()
    db_entries_raw: dict[str, dict] = {}

    # ── source 1: DB index ────────────────────────────────────────────────────
    db = storage_dir / "state.vscdb"
    if db.exists():
        try:
            conn = sqlite3.connect(str(db), timeout=2)
            row = conn.execute(
                "SELECT value FROM ItemTable "
                "WHERE key='chat.ChatSessionStore.index'").fetchone()
            conn.close()
            if row:
                data = json.loads(row[0])
                for uid, entry in data.get("entries", {}).items():
                    db_all_ids.add(uid)
                    db_entries_raw[uid] = entry
                    if entry.get("isEmpty"):
                        continue
                    title = (entry.get("title") or entry.get("name")
                             or "").strip()
                    known[uid] = {
                        "id": uid,
                        "title": title or f"Session {uid[:8]}",
                        "ts": entry.get("lastMessageDate", 0),
                        "has_requests": entry.get("lastMessageDate", 0) > 0,
                        "source": "db",
                        "file_ctime": 0.0,
                        "mismatch_reason": None,
                        "db_entry": entry,
                    }
        except Exception:
            pass

    # ── source 2: files on disk (.jsonl and .json) ───────────────────────────
    cs_dir = storage_dir / "chatSessions"
    if cs_dir.is_dir():
        disk_files = (list(cs_dir.glob("*.jsonl")) +
                      list(cs_dir.glob("*.json")))
        for p in disk_files:
            uid = p.stem
            try:
                fctime = p.stat().st_ctime
            except OSError:
                fctime = 0.0
            if uid in known:
                known[uid]["source"] = "both"
                known[uid]["file_ctime"] = fctime
            elif uid in db_all_ids:
                scan_fn = (_quick_scan_json
                           if p.suffix == ".json" else _quick_scan_jsonl)
                title, ts, has_req = scan_fn(p)
                known[uid] = {
                    "id": uid,
                    "title": title or f"Session {uid[:8]}",
                    "ts": ts,
                    "has_requests": has_req,
                    "source": "disk",
                    "file_ctime": fctime,
                    "mismatch_reason":
                    "DB marks session as empty but file exists on disk",
                    "db_entry": db_entries_raw.get(uid),
                }
            else:
                scan_fn = (_quick_scan_json
                           if p.suffix == ".json" else _quick_scan_jsonl)
                title, ts, has_req = scan_fn(p)
                known[uid] = {
                    "id": uid,
                    "title": title or f"Session {uid[:8]}",
                    "ts": ts,
                    "has_requests": has_req,
                    "source": "disk",
                    "file_ctime": fctime,
                    "mismatch_reason":
                    "File exists on disk but not in DB index",
                    "db_entry": None,
                }

    # ── check DB-only entries (no file on disk) ───────────────────────────────
    for uid, sess in known.items():
        if sess.get("source") == "db":
            has_file = (
                (storage_dir / "chatSessions" / f"{uid}.json").exists()
                or (storage_dir / "chatSessions" / f"{uid}.jsonl").exists())
            if not has_file:
                sess["mismatch_reason"] = (
                    "In DB index but no session file found on disk")

    return sorted(known.values(), key=lambda s: s["ts"], reverse=True)


def load_requests(storage_dir: Path, session_id: str) -> list[dict]:
    """Load requests from a session file (.json snapshot or .jsonl replay)."""
    p = session_file(storage_dir, session_id)
    if not p.exists():
        return []
    if p.suffix == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("requests", [])
        except Exception:
            return []
    state = replay_jsonl(p)
    return state.get("requests", [])


def extract_user_text(request: dict) -> str:
    msg = request.get("message", "")
    if isinstance(msg, dict):
        return msg.get("text", "")
    return str(msg)


def extract_response_text(request: dict) -> str:
    """Collect main markdown text from response parts (no 'kind' key)."""
    parts = []
    for item in request.get("response", []):
        if isinstance(item, dict) and "kind" not in item:
            val = item.get("value", "")
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
    return "\n\n".join(parts)


def extract_thinking_text(request: dict) -> str:
    """Collect thinking/reasoning blocks."""
    parts = []
    for item in request.get("response", []):
        if isinstance(item, dict) and item.get("kind") == "thinking":
            val = item.get("value", "")
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
    return "\n\n".join(parts)


def fmt_ts(ts_ms) -> str:
    if not ts_ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ts_ms) /
                                      1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def fmt_mtime(mtime: float) -> str:
    if not mtime:
        return ""
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _make_db_entry(sess: dict) -> dict:
    """Build a VS Code-compatible DB index entry from a session dict."""
    ctime_ms = (int(sess["file_ctime"] *
                    1000) if sess.get("file_ctime") else sess["ts"])
    return {
        "sessionId": sess["id"],
        "title": sess["title"],
        "lastMessageDate": sess["ts"],
        "timing": {
            "created": ctime_ms
        },
        "initialLocation": "panel",
        "hasPendingEdits": False,
        "isEmpty": False,
        "isExternal": False,
        "lastResponseState": 1,
    }


# ── DB helpers ────────────────────────────────────────────────────────────────


def _db_read_index(db: Path) -> dict:
    """Read the chat session index from a state.vscdb. Returns empty index if absent."""
    conn = sqlite3.connect(str(db), timeout=5)
    try:
        row = conn.execute(
            "SELECT value FROM ItemTable "
            "WHERE key='chat.ChatSessionStore.index'").fetchone()
    finally:
        conn.close()
    if row:
        return json.loads(row[0])
    return {"version": 1, "entries": {}}


def _db_write_index(db: Path, idx: dict) -> None:
    """Write the chat session index to a state.vscdb."""
    conn = sqlite3.connect(str(db), timeout=5)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            ("chat.ChatSessionStore.index", json.dumps(idx)),
        )
        conn.commit()
    finally:
        conn.close()


def _db_ensure(db: Path) -> None:
    """Create an empty ItemTable if the DB doesn't exist yet."""
    conn = sqlite3.connect(str(db), timeout=5)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS ItemTable "
                     "(key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
    finally:
        conn.close()


def _db_backup(db: Path, suffix: str = "backup") -> Path:
    """Create a timestamped backup of the DB. Returns backup path."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db.parent / f"state.vscdb.{suffix}-{stamp}"
    shutil.copy2(str(db), str(backup))
    return backup


# ── actions ───────────────────────────────────────────────────────────────────


def action_archive_session(storage_dir: Path, session_id: str,
                           dest_dir: Path) -> Path:
    """
    Zip a single session file into dest_dir.

    Returns the created zip path.
    Raises RuntimeError if the session or its file cannot be found.
    """
    sessions = load_session_index(storage_dir)
    sess = next((s for s in sessions if s["id"] == session_id), None)
    if sess is None:
        raise RuntimeError(
            f"Session {session_id!r} not found in {storage_dir}")
    sf = session_file(storage_dir, session_id)
    if not sf.exists():
        raise RuntimeError(f"Session file not found on disk: {sf}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", sess["title"])[:40]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = dest_dir / f"chatarchive_{safe}_{session_id[:8]}_{stamp}.zip"
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(sf), sf.name)
    return zip_path


def action_archive_workspace(storage_dir: Path, dest_dir: Path) -> Path:
    """
    Zip all session files in a workspace into dest_dir.

    Returns the created zip path.
    Raises RuntimeError if no session files are found.
    """
    cs_dir = storage_dir / "chatSessions"
    files = (list(cs_dir.glob("*.jsonl")) +
             list(cs_dir.glob("*.json"))) if cs_dir.is_dir() else []
    if not files:
        raise RuntimeError(f"No session files found in {cs_dir}")
    name, _ = workspace_display_name(storage_dir)
    safe = re.sub(r"[^\w\-]", "_", name)[:40]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"chatarchive_{safe}_{stamp}.zip"
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(str(f), f.name)
    return zip_path


def action_delete_session(storage_dir: Path,
                          session_id: str,
                          *,
                          backup: bool = True) -> None:
    """
    Delete a session's file and remove it from the DB index.

    Creates a timestamped DB backup unless backup=False.
    """
    db = storage_dir / "state.vscdb"
    sf = session_file(storage_dir, session_id)
    if backup and db.exists():
        _db_backup(db, "repair-backup")
    if sf.exists():
        sf.unlink()
    if db.exists():
        idx = _db_read_index(db)
        idx.get("entries", {}).pop(session_id, None)
        _db_write_index(db, idx)


def action_delete_workspace_chats(storage_dir: Path,
                                  *,
                                  backup: bool = True) -> int:
    """
    Delete every session file in the workspace and clear the DB index.

    Returns the number of files deleted.
    Creates a DB backup unless backup=False.
    """
    db = storage_dir / "state.vscdb"
    cs_dir = storage_dir / "chatSessions"
    files = (list(cs_dir.glob("*.jsonl")) +
             list(cs_dir.glob("*.json"))) if cs_dir.is_dir() else []
    if backup and db.exists():
        _db_backup(db, "repair-backup")
    for f in files:
        f.unlink()
    if db.exists():
        idx = _db_read_index(db)
        idx["entries"] = {}
        _db_write_index(db, idx)
    return len(files)


def action_copy_sessions(src_dir: Path,
                         dst_dir: Path,
                         session_ids: list[str],
                         *,
                         backup: bool = True) -> list[str]:
    """
    Copy sessions (files + DB entries) from src_dir to dst_dir.

    Only IDs that have a file on disk in src_dir are copied.
    Returns the list of session IDs that were actually copied.
    Creates a DB backup in dst_dir unless backup=False.
    Raises RuntimeError if a requested session_id is unknown in src_dir.
    """
    src_sessions = {s["id"]: s for s in load_session_index(src_dir)}
    for sid in session_ids:
        if sid not in src_sessions:
            raise RuntimeError(
                f"Session {sid!r} not found in source workspace {src_dir}")

    db_dst = dst_dir / "state.vscdb"
    if backup and db_dst.exists():
        _db_backup(db_dst, "merge-backup")

    cs_dst = dst_dir / "chatSessions"
    cs_dst.mkdir(parents=True, exist_ok=True)

    copied = []
    for sid in session_ids:
        sess = src_sessions[sid]
        src = session_file(src_dir, sid)
        if not src.exists():
            continue
        shutil.copy2(str(src), str(cs_dst / src.name))
        copied.append(sid)

    if copied:
        if db_dst.exists():
            idx = _db_read_index(db_dst)
        else:
            _db_ensure(db_dst)
            idx = {"version": 1, "entries": {}}
        entries = idx.setdefault("entries", {})
        for sid in copied:
            sess = src_sessions[sid]
            base = sess.get("db_entry")
            entries[sid] = ({
                **base, "isEmpty": False
            } if base else _make_db_entry(sess))
        _db_write_index(db_dst, idx)

    return copied


def action_repair_session(storage_dir: Path,
                          session_id: str,
                          *,
                          backup: bool = True) -> str:
    """
    Repair a single index mismatch.

    Returns a short action string:
      'already_in_sync'       – nothing to do
      'added_to_db'           – disk-only session added to the DB index
      'restored_empty_to_active' – DB had it as isEmpty; now restored
      'marked_empty'          – DB-only session flagged as isEmpty

    Raises RuntimeError on bad input or a missing DB.
    """
    sessions = load_session_index(storage_dir)
    sess = next((s for s in sessions if s["id"] == session_id), None)
    if sess is None:
        raise RuntimeError(
            f"Session {session_id!r} not found in {storage_dir}")

    reason = sess.get("mismatch_reason")
    if not reason:
        return "already_in_sync"

    source = sess.get("source", "")
    if source == "disk" and not sess.get("has_requests"):
        raise RuntimeError(
            "Empty disk-only session cannot be repaired (no content)")

    db = storage_dir / "state.vscdb"
    if not db.exists():
        raise RuntimeError(f"state.vscdb not found in {storage_dir}")

    if backup:
        _db_backup(db, "repair-backup")

    idx = _db_read_index(db)
    entries = idx.setdefault("entries", {})
    db_entry = sess.get("db_entry")

    if source == "disk" and db_entry is not None:
        entries[session_id] = {**db_entry, "isEmpty": False}
        action = "restored_empty_to_active"
    elif source == "disk":
        entries[session_id] = _make_db_entry(sess)
        action = "added_to_db"
    elif source == "db":
        if session_id in entries:
            entries[session_id]["isEmpty"] = True
        action = "marked_empty"
    else:
        raise RuntimeError(f"Unknown source {source!r} for {session_id!r}")

    _db_write_index(db, idx)
    return action


def action_repair_all(storage_dir: Path, *, backup: bool = True) -> int:
    """
    Repair every mismatch in a workspace (skips empty disk-only sessions).

    Returns the number of sessions repaired.
    Creates one DB backup unless backup=False.
    """
    sessions = load_session_index(storage_dir)
    mismatched = [
        s for s in sessions if s.get("mismatch_reason") and (
            s.get("source") != "disk" or s.get("has_requests"))
    ]
    if not mismatched:
        return 0

    db = storage_dir / "state.vscdb"
    if not db.exists():
        raise RuntimeError(f"state.vscdb not found in {storage_dir}")

    if backup:
        _db_backup(db, "repair-backup")

    idx = _db_read_index(db)
    entries = idx.setdefault("entries", {})
    for sess in mismatched:
        source = sess.get("source", "")
        db_entry = sess.get("db_entry")
        if source == "disk" and db_entry is not None:
            entries[sess["id"]] = {**db_entry, "isEmpty": False}
        elif source == "disk":
            entries[sess["id"]] = _make_db_entry(sess)
        elif source == "db":
            if sess["id"] in entries:
                entries[sess["id"]]["isEmpty"] = True
    _db_write_index(db, idx)
    return len(mismatched)


def action_restore_archive(zip_path: Path,
                           dst_dir: Path,
                           *,
                           backup: bool = True) -> list[str]:
    """
    Extract session files from a zip archive into dst_dir and register them.

    Sessions whose ID already exists in dst_dir are skipped.
    Returns the list of session IDs that were actually restored.
    Creates a DB backup in dst_dir unless backup=False.
    Raises RuntimeError if the zip contains no session files.
    """
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        names = [
            n for n in zf.namelist()
            if n.endswith(".jsonl") or n.endswith(".json")
        ]
    if not names:
        raise RuntimeError(
            "No session files (.jsonl / .json) found in archive")

    existing_ids = {s["id"] for s in load_session_index(dst_dir)}
    to_restore = [n for n in names if Path(n).stem not in existing_ids]
    if not to_restore:
        return []

    db_dst = dst_dir / "state.vscdb"
    if backup and db_dst.exists():
        _db_backup(db_dst, "repair-backup")

    cs_dir = dst_dir / "chatSessions"
    cs_dir.mkdir(parents=True, exist_ok=True)

    restored = []
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        for name in to_restore:
            uid = Path(name).stem
            dest_file = cs_dir / Path(name).name
            dest_file.write_bytes(zf.read(name))
            scan_fn = (_quick_scan_json
                       if name.endswith(".json") else _quick_scan_jsonl)
            title, ts, has_req = scan_fn(dest_file)
            restored.append({
                "id": uid,
                "title": title or f"Session {uid[:8]}",
                "ts": ts,
                "has_requests": has_req,
                "source": "both",
                "file_ctime": dest_file.stat().st_ctime,
                "mismatch_reason": None,
                "db_entry": None,
            })

    if db_dst.exists():
        idx = _db_read_index(db_dst)
    else:
        _db_ensure(db_dst)
        idx = {"version": 1, "entries": {}}
    entries = idx.setdefault("entries", {})
    for sess in restored:
        entries[sess["id"]] = _make_db_entry(sess)
    _db_write_index(db_dst, idx)

    return [s["id"] for s in restored]
