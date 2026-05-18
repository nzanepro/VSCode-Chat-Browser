"""
workspace_chat_browser.py

Browse VS Code workspace chat history stored in workspaceStorage.

JSONL format notes:
  Each chatSessions/<uuid>.jsonl is a state-log:
    kind=0  full initial state object in 'v'
    kind=1  property update: key path in 'k', new value in 'v'
    kind=2  array append:    key path in 'k', item(s) to append in 'v'
  After replay, state.requests[] holds each Q&A turn:
    request.message.text        → user prompt
    request.response[]          → list of content parts
      items with no 'kind' key  → main markdown text (in 'value')
      kind='thinking'           → reasoning (in 'value')
      kind='toolInvocationSerialized' → tool call summary

Usage:
    python workspace_chat_browser.py

All pure business logic lives in core.py (no GUI dependency).
"""

import os
import shutil
import subprocess
import sys
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.filedialog import askdirectory, askopenfilename

# Relative import when installed as a package; fall back to bare name when
# running directly as `python src/vscode_chat_browser/workspace_chat_browser.py`.
try:
    from .core import (
        WORKSPACESTORAGE,
        _append_nested,
        _make_db_entry,
        _quick_scan_json,
        _quick_scan_jsonl,
        _set_nested,
        action_archive_session,
        action_archive_workspace,
        action_copy_sessions,
        action_delete_session,
        action_delete_workspace_chats,
        action_repair_all,
        action_repair_session,
        action_restore_archive,
        extract_response_text,
        extract_thinking_text,
        extract_user_text,
        fmt_mtime,
        fmt_ts,
        load_requests,
        load_session_index,
        replay_jsonl,
        session_file,
        workspace_display_name,
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core import (  # type: ignore[no-redef]
        WORKSPACESTORAGE, _append_nested, _make_db_entry, _quick_scan_json,
        _quick_scan_jsonl, _set_nested, action_archive_session,
        action_archive_workspace, action_copy_sessions, action_delete_session,
        action_delete_workspace_chats, action_repair_all,
        action_repair_session, action_restore_archive, extract_response_text,
        extract_thinking_text, extract_user_text, fmt_mtime, fmt_ts,
        load_requests, load_session_index, replay_jsonl, session_file,
        workspace_display_name,
    )

# ── UI ────────────────────────────────────────────────────────────────────────


class _Tooltip:
    """Delayed hover tooltip for any Tkinter widget."""

    def __init__(self, widget: tk.Widget):
        self._w = widget
        self._win: tk.Toplevel | None = None
        self._job: str | None = None
        self._pending: tuple = ("", 0, 0)

    def schedule(self, text: str, rx: int, ry: int):
        self.cancel()
        self._pending = (text, rx, ry)
        self._job = self._w.after(550, self._show)

    def cancel(self):
        if self._job:
            self._w.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self):
        self._hide()
        text, rx, ry = self._pending
        self._win = tk.Toplevel(self._w)
        self._win.wm_overrideredirect(True)
        self._win.wm_geometry(f"+{rx + 14}+{ry + 14}")
        tk.Label(
            self._win,
            text=text,
            justify=tk.LEFT,
            background="#FFFFC0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=6,
            pady=3,
            wraplength=440,
        ).pack()

    def _hide(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


class ChatBrowser(tk.Tk):

    def __init__(self, initial_storage: str | None = None):
        super().__init__()
        self.title("VS Code Chat Browser")
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        h = int(sh * 0.90)
        w = max(int(sw * 0.70), 1100)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(900, 500)
        self._workspaces: list[dict] = []
        self._node_map: dict[str,
                             tuple[int,
                                   int]] = {}  # tree_id -> (ws_idx, sess_idx)
        self._show_thinking = tk.BooleanVar(value=False)
        self._hide_empty = tk.BooleanVar(value=True)
        self._sort_col = "date"  # "name" | "date" | "created"
        self._sort_rev = True  # True = descending
        self._view_mode = tk.StringVar(value="grouped")
        self._build_ui()
        if initial_storage is not None:
            self._path_var.set(initial_storage)
        self.after(50, self._load_all)

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style(self)
        for theme in ("vista", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        # top bar
        top = ttk.Frame(self, padding=(6, 6, 6, 2))
        top.pack(fill=tk.X)
        ttk.Label(top, text="Storage:").pack(side=tk.LEFT)
        self._path_var = tk.StringVar(value=str(WORKSPACESTORAGE))
        pe = ttk.Entry(top, textvariable=self._path_var, width=74)
        pe.pack(side=tk.LEFT, padx=6)
        pe.bind("<Return>", lambda _: self._refresh())
        ttk.Button(top, text="⟳ Refresh", command=self._refresh,
                   width=10).pack(side=tk.LEFT)
        ttk.Checkbutton(top,
                        text="Show thinking",
                        variable=self._show_thinking).pack(side=tk.LEFT,
                                                           padx=12)
        ttk.Checkbutton(top,
                        text="Hide empty chats",
                        variable=self._hide_empty,
                        command=self._rebuild_tree).pack(side=tk.LEFT, padx=4)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT,
                                                    fill=tk.Y,
                                                    padx=8,
                                                    pady=4)
        ttk.Label(top, text="View:").pack(side=tk.LEFT)
        ttk.Radiobutton(top,
                        text="Grouped",
                        variable=self._view_mode,
                        value="grouped",
                        command=self._rebuild_tree).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(top,
                        text="Flat",
                        variable=self._view_mode,
                        value="flat",
                        command=self._rebuild_tree).pack(side=tk.LEFT, padx=2)

        # filter bar
        fbar = ttk.Frame(self, padding=(6, 0, 6, 4))
        fbar.pack(fill=tk.X)
        ttk.Label(fbar, text="Filter:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._rebuild_tree())
        fe = ttk.Entry(fbar, textvariable=self._filter_var, width=42)
        fe.pack(side=tk.LEFT, padx=6)
        ttk.Button(fbar,
                   text="✕",
                   command=lambda: self._filter_var.set(""),
                   width=3).pack(side=tk.LEFT)

        # paned window
        pw = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        # left: tree
        lf = ttk.Frame(pw)
        pw.add(lf, weight=1)
        self._tree = ttk.Treeview(lf,
                                  show="tree headings",
                                  columns=("date", "created"),
                                  selectmode="browse")
        self._tree.heading("#0",
                           text="Workspace / Session",
                           command=lambda: self._sort_by("name"))
        self._tree.heading("date",
                           text="Last Active",
                           command=lambda: self._sort_by("date"))
        self._tree.heading("created",
                           text="Created",
                           command=lambda: self._sort_by("created"))
        self._tree.column("#0", width=280, minwidth=160, stretch=True)
        self._tree.column("date", width=130, minwidth=80, stretch=False)
        self._tree.column("created", width=130, minwidth=80, stretch=False)
        self._update_sort_arrows()
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Button-3>", self._on_right_click)
        self._tree.tag_configure("ws", font=("Segoe UI", 9, "bold"))
        self._tree.tag_configure("ws_mismatch",
                                 font=("Segoe UI", 9, "bold", "italic"),
                                 foreground="#8B2500")
        self._tree.tag_configure("sess_mismatch",
                                 font=("Segoe UI", 9, "italic"),
                                 foreground="#8B4513")
        self._tooltip = _Tooltip(self._tree)
        self._tree.bind("<Motion>", self._on_tree_motion)
        self._tree.bind("<Leave>", lambda _: self._tooltip.cancel())
        self._ctx_menu = tk.Menu(self, tearoff=0)

        # right: chat view
        rf = ttk.Frame(pw)
        pw.add(rf, weight=3)
        self._hdr_var = tk.StringVar(value="← Select a session")
        ttk.Label(rf,
                  textvariable=self._hdr_var,
                  anchor=tk.W,
                  font=("Segoe UI", 10, "bold"),
                  padding=(6, 4)).pack(fill=tk.X)
        ttk.Separator(rf, orient="horizontal").pack(fill=tk.X)

        tf = ttk.Frame(rf)
        tf.pack(fill=tk.BOTH, expand=True)
        self._txt = tk.Text(
            tf,
            wrap=tk.WORD,
            state=tk.DISABLED,
            padx=10,
            pady=6,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            bg="#F8F8F8",
            cursor="arrow",
        )
        vsb2 = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._txt.yview)
        self._txt.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._txt.pack(fill=tk.BOTH, expand=True)

        # text tags
        self._txt.tag_configure("u_role",
                                font=("Segoe UI", 9, "bold"),
                                foreground="#1A5276",
                                spacing1=14,
                                spacing3=3)
        self._txt.tag_configure("u_body",
                                font=("Segoe UI", 10),
                                background="#EBF5FB",
                                lmargin1=10,
                                lmargin2=10,
                                rmargin=10,
                                spacing3=8)
        self._txt.tag_configure("a_role",
                                font=("Segoe UI", 9, "bold"),
                                foreground="#1E8449",
                                spacing1=14,
                                spacing3=3)
        self._txt.tag_configure("a_body",
                                font=("Segoe UI", 10),
                                background="#EAFAF1",
                                lmargin1=10,
                                lmargin2=10,
                                rmargin=10,
                                spacing3=8)
        self._txt.tag_configure("think_role",
                                font=("Segoe UI", 8, "italic"),
                                foreground="#888",
                                spacing1=6,
                                spacing3=2)
        self._txt.tag_configure("think_body",
                                font=("Segoe UI", 9, "italic"),
                                foreground="#888",
                                background="#F5F5F5",
                                lmargin1=10,
                                lmargin2=10,
                                rmargin=10,
                                spacing3=6)
        self._txt.tag_configure("meta",
                                font=("Segoe UI", 8),
                                foreground="#AAA",
                                spacing3=2)

        # status bar (packed first so progress bar appears above it)
        self._status = tk.StringVar(value="Ready")
        ttk.Label(self,
                  textvariable=self._status,
                  anchor=tk.W,
                  relief=tk.SUNKEN,
                  padding=(6, 2)).pack(fill=tk.X, side=tk.BOTTOM)
        self._progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        # not packed yet — shown only during loading

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_all(self):
        base = Path(self._path_var.get())
        if not base.is_dir():
            self._status.set(f"ERROR: directory not found: {base}")
            return

        subdirs = [d for d in base.iterdir() if d.is_dir()]
        total = len(subdirs)

        self._progress["maximum"] = max(total, 1)
        self._progress["value"] = 0
        self._progress.pack(fill=tk.X, side=tk.BOTTOM)
        self._status.set(f"Scanning 0 / {total}…")
        self.update_idletasks()

        self._workspaces = []
        for i, d in enumerate(subdirs):
            sessions = load_session_index(d)
            self._progress["value"] = i + 1
            if i % 10 == 0:
                self._status.set(f"Scanning {i + 1} / {total}…")
                self.update_idletasks()
            if not sessions:
                continue
            name, full_path = workspace_display_name(d)
            try:
                st = d.stat()
                mtime = st.st_mtime
                ctime = st.st_ctime
            except OSError:
                mtime = 0.0
                ctime = 0.0
            self._workspaces.append({
                "dir": d,
                "name": name,
                "path": full_path,
                "sessions": sessions,
                "mtime": mtime,
                "ctime": ctime,
            })

        self._progress.pack_forget()
        self._rebuild_tree()

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            # dates default descending, name ascending
            self._sort_rev = col in ("date", "created")
        self._update_sort_arrows()
        self._rebuild_tree()

    def _update_sort_arrows(self):
        arrow_asc = " ▲"
        arrow_desc = " ▼"
        cols = {
            "#0": ("name", "Workspace / Session"),
            "date": ("date", "Last Active"),
            "created": ("created", "Created"),
        }
        for col, (key, label) in cols.items():
            if self._sort_col == key:
                suffix = arrow_desc if self._sort_rev else arrow_asc
            else:
                suffix = ""
            self._tree.heading(col, text=label + suffix)

    def _rebuild_tree(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._node_map = {}
        for ws in self._workspaces:
            ws.pop("_node", None)
        term = self._filter_var.get().lower().strip()
        hide_empty = self._hide_empty.get()
        if self._view_mode.get() == "flat":
            self._rebuild_flat(term, hide_empty)
        else:
            self._rebuild_grouped(term, hide_empty)

    def _rebuild_grouped(self, term: str, hide_empty: bool):
        """Workspaces as parent nodes, sessions as children."""
        if self._sort_col == "name":
            self._workspaces.sort(key=lambda w: w["name"].lower(),
                                  reverse=self._sort_rev)
        elif self._sort_col == "created":
            self._workspaces.sort(key=lambda w: w["ctime"],
                                  reverse=self._sort_rev)
        else:
            self._workspaces.sort(key=lambda w: w["mtime"],
                                  reverse=self._sort_rev)

        ws_shown = sess_shown = 0
        for wi, ws in enumerate(self._workspaces):
            name = ws["name"]
            sessions = ws["sessions"]
            idxs = [
                i for i, s in enumerate(sessions)
                if (not hide_empty or s.get("has_requests")) and (
                    not term or term in s["title"].lower()
                    or term in name.lower())
            ]
            if not idxs:
                continue

            nm, nt = len(idxs), len(sessions)
            count_sfx = f"/{nt}" if term and nm != nt else ""
            ws_date = fmt_mtime(ws["mtime"])
            ws_created = fmt_mtime(ws["ctime"])
            has_mm = any(sessions[i].get("mismatch_reason") for i in idxs)
            ws_tags = ("ws", "ws_mismatch") if has_mm else ("ws", )
            node = self._tree.insert(
                "",
                tk.END,
                text=f"{name}  ({nm}{count_sfx})",
                values=(ws_date, ws_created),
                open=bool(term),
                tags=ws_tags,
            )
            ws["_node"] = node

            for si in idxs:
                sess = sessions[si]
                stags = (
                    "sess_mismatch", ) if sess.get("mismatch_reason") else ()
                child = self._tree.insert(
                    node,
                    tk.END,
                    text=f"  {sess['title']}",
                    values=(fmt_ts(sess["ts"]),
                            fmt_mtime(sess.get("file_ctime", 0))),
                    tags=stags,
                )
                self._node_map[child] = (wi, si)

            ws_shown += 1
            sess_shown += nm

        flt = f"  (filter: '{self._filter_var.get()}')" if term else ""
        self._status.set(f"{ws_shown} workspaces · {sess_shown} sessions{flt}")

    def _rebuild_flat(self, term: str, hide_empty: bool):
        """All sessions from all workspaces in a single sorted flat list."""
        all_items: list[tuple[int, int]] = []
        for wi, ws in enumerate(self._workspaces):
            for si, s in enumerate(ws["sessions"]):
                if hide_empty and not s.get("has_requests"):
                    continue
                if term and (term not in s["title"].lower()
                             and term not in ws["name"].lower()):
                    continue
                all_items.append((wi, si))

        if self._sort_col == "name":
            all_items.sort(key=lambda x: self._workspaces[x[0]]["sessions"][x[
                1]]["title"].lower(),
                           reverse=self._sort_rev)
        elif self._sort_col == "created":
            all_items.sort(key=lambda x: self._workspaces[x[0]]["sessions"][x[
                1]].get("file_ctime", 0),
                           reverse=self._sort_rev)
        else:
            all_items.sort(
                key=lambda x: self._workspaces[x[0]]["sessions"][x[1]]["ts"],
                reverse=self._sort_rev)

        for wi, si in all_items:
            ws = self._workspaces[wi]
            sess = ws["sessions"][si]
            stags = ("sess_mismatch", ) if sess.get("mismatch_reason") else ()
            child = self._tree.insert(
                "",
                tk.END,
                text=f"{ws['name']}  \u203a  {sess['title']}",
                values=(fmt_ts(sess["ts"]),
                        fmt_mtime(sess.get("file_ctime", 0))),
                tags=stags,
            )
            self._node_map[child] = (wi, si)

        flt = f"  (filter: '{self._filter_var.get()}')" if term else ""
        self._status.set(f"{len(all_items)} sessions (flat){flt}")

    def _on_tree_motion(self, event: tk.Event):
        node_id = self._tree.identify_row(event.y)
        if not node_id:
            self._tooltip.cancel()
            return
        info = self._node_map.get(node_id)
        if info:
            wi, si = info
            sess = self._workspaces[wi]["sessions"][si]
            reason = sess.get("mismatch_reason")
            if reason:
                self._tooltip.schedule(f"\u26a0 Index mismatch: {reason}",
                                       event.x_root, event.y_root)
                return
        self._tooltip.cancel()

    def _refresh(self):
        self._workspaces.clear()
        self._write_chat("")
        self._hdr_var.set("← Select a session")
        self._load_all()

    # ── context menu ──────────────────────────────────────────────────────────

    def _on_right_click(self, event: tk.Event):
        node_id = self._tree.identify_row(event.y)
        if not node_id:
            return
        self._tree.selection_set(node_id)
        menu = self._ctx_menu
        menu.delete(0, tk.END)

        info = self._node_map.get(node_id)
        if info:
            # Session node
            wi, si = info
            ws = self._workspaces[wi]
            sess = ws["sessions"][si]
            sf = session_file(ws["dir"], sess["id"])
            storage_dir = ws["dir"]

            menu.add_command(label=f"Session: {sess['title']}",
                             state="disabled")
            menu.add_separator()
            menu.add_command(label="Copy session ID",
                             command=lambda: self._copy(sess["id"]))
            menu.add_command(label="Copy session title",
                             command=lambda: self._copy(sess["title"]))
            menu.add_command(label="Copy session file path",
                             command=lambda: self._copy(str(sf)))
            menu.add_separator()
            menu.add_command(label="Open storage folder in Explorer",
                             command=lambda: self._explore(storage_dir))
            menu.add_separator()
            menu.add_command(label="Copy to Workspace\u2026",
                             command=lambda ws_=ws, sess_=sess: self.
                             _copy_session_to(ws_, sess_))
            if sess.get("mismatch_reason"):
                menu.add_separator()
                menu.add_command(label="\u26a0 Repair Index\u2026",
                                 command=lambda ws_=ws, sess_=sess: self.
                                 _repair_index(ws_, sess_))
            menu.add_separator()
            menu.add_command(label="Archive Session…",
                             command=lambda ws_=ws, sess_=sess: self.
                             _archive_session(ws_, sess_))
            menu.add_command(label="Restore Chats from Archive…",
                             command=lambda: self._restore_chats())
            menu.add_separator()
            menu.add_command(label="Delete Session…",
                             command=lambda ws_=ws, sess_=sess: self.
                             _delete_session(ws_, sess_))
            menu.add_separator()
            menu.add_command(
                label="Properties…",
                command=lambda: self._show_session_props(ws, sess))
        else:
            # Workspace node — find by scanning for a ws whose _node matches
            ws = self._find_ws_by_node(node_id)
            if not ws:
                return
            menu.add_command(label=f"Workspace: {ws['name']}",
                             state="disabled")
            menu.add_separator()
            menu.add_command(label="Copy storage folder path",
                             command=lambda: self._copy(str(ws["dir"])))
            menu.add_command(label="Copy workspace path",
                             command=lambda: self._copy(ws["path"]))
            menu.add_separator()
            menu.add_command(label="Open storage folder in Explorer",
                             command=lambda: self._explore(ws["dir"]))
            ws_path = Path(ws["path"])
            if ws_path.exists():
                menu.add_command(label="Open workspace folder in Explorer",
                                 command=lambda: self._explore(ws_path))
            menu.add_separator()
            menu.add_command(label="Copy All Sessions to Workspace\u2026",
                             command=lambda ws_=ws: self._copy_all_to(ws_))
            if any(s.get("mismatch_reason") for s in ws["sessions"]):
                menu.add_separator()
                menu.add_command(
                    label="\u26a0 Repair All Mismatches in Group\u2026",
                    command=lambda ws_=ws: self._repair_all(ws_))
            menu.add_separator()
            menu.add_command(
                label="Archive Workspace Chats…",
                command=lambda ws_=ws: self._archive_workspace(ws_))
            menu.add_command(label="Restore Chats from Archive…",
                             command=lambda: self._restore_chats())
            menu.add_separator()
            menu.add_command(
                label="Delete Workspace Chats…",
                command=lambda ws_=ws: self._delete_workspace_chats(ws_))
            menu.add_separator()
            menu.add_command(label="Properties…",
                             command=lambda: self._show_ws_props(ws))

        menu.tk_popup(event.x_root, event.y_root)

    def _find_ws_by_node(self, node_id: str) -> dict | None:
        """Return the workspace whose tree node matches node_id."""
        for ws in self._workspaces:
            if ws.get("_node") == node_id:
                return ws
        return None

    # ── VS Code running guard ──────────────────────────────────────────

    @staticmethod
    def _vscode_running() -> bool:
        """Return True if a VS Code process is currently running."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Code.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=5)
            return "Code.exe" in result.stdout
        except Exception:
            return False

    def _ensure_vscode_closed(self) -> bool:
        """Return True if safe to proceed; show a blocking dialog if not."""
        while self._vscode_running():
            win = tk.Toplevel(self)
            win.title("VS Code is Running")
            win.resizable(False, False)
            win.grab_set()
            win.focus_set()
            ttk.Label(
                win,
                text=("VS Code is currently open.\n\n"
                      "Close VS Code before repairing the index to avoid\n"
                      "database conflicts, then click Try Again."),
                justify=tk.LEFT,
                padding=16).pack()
            result = tk.BooleanVar(value=False)
            frm = ttk.Frame(win)
            frm.pack(pady=(0, 12))
            ttk.Button(frm,
                       text="Try Again When Closed",
                       command=lambda:
                       (result.set(True), win.destroy())).pack(side=tk.LEFT,
                                                               padx=6)
            ttk.Button(frm,
                       text="Cancel",
                       command=lambda:
                       (result.set(False), win.destroy())).pack(side=tk.LEFT,
                                                                padx=6)
            win.wait_window()
            if not result.get():
                return False
        return True

    # ── Tag-only repair helpers ───────────────────────────────────────────────

    def _clear_mismatch_tags(self, ws: dict, sessions: list[dict]):
        """Remove mismatch styling from given sessions without rebuilding."""
        wi = self._workspaces.index(ws)
        for sess in sessions:
            si = ws["sessions"].index(sess)
            for nid, (w, s) in self._node_map.items():
                if w == wi and s == si:
                    self._tree.item(nid, tags=())
                    break
        # Update workspace node tag if no mismatches remain
        ws_node = ws.get("_node")
        if ws_node and not any(
                s.get("mismatch_reason") for s in ws["sessions"]):
            current = list(self._tree.item(ws_node, "tags"))
            if "ws_mismatch" in current:
                current.remove("ws_mismatch")
                self._tree.item(ws_node, tags=tuple(current))

    def _repair_index(self, ws: dict, sess: dict):
        """Add a disk-only session to the DB index, or flag a db-only entry."""
        db = ws["dir"] / "state.vscdb"
        if not db.exists():
            messagebox.showerror("Repair Error",
                                 "state.vscdb not found.",
                                 parent=self)
            return

        source = sess.get("source", "")
        db_entry = sess.get("db_entry")
        reason = sess.get("mismatch_reason", "")
        if source == "disk" and not sess.get("has_requests"):
            messagebox.showinfo(
                "Empty Session",
                "This session has no content — skipping repair.",
                parent=self)
            return
        if source == "disk" and db_entry is not None:
            action = (f"Restore session in DB index (was marked empty):\n"
                      f"  Title: {sess['title']}\n"
                      f"  ID:    {sess['id']}")
        elif source == "disk":
            action = (f"Add session to the DB index:\n"
                      f"  Title: {sess['title']}\n"
                      f"  ID:    {sess['id']}")
        elif source == "db":
            action = (f"Mark session as empty in the DB index\n"
                      f"(file not found on disk):\n"
                      f"  Title: {sess['title']}\n"
                      f"  ID:    {sess['id']}")
        else:
            messagebox.showinfo("Nothing to Repair",
                                "Session appears to be in sync.",
                                parent=self)
            return

        msg = (f"Mismatch detected:\n  {reason}\n\n"
               f"Proposed action:\n  {action}\n\n"
               f"A .repair-backup will be created before any changes.")
        if not messagebox.askyesno("Repair Index", msg, parent=self):
            return

        if not self._ensure_vscode_closed():
            return

        try:
            result = action_repair_session(ws["dir"], sess["id"])
        except Exception as e:
            messagebox.showerror("Repair Failed", str(e), parent=self)
            return

        if result in ("added_to_db", "restored_empty_to_active"):
            sess["source"] = "both"
        sess["mismatch_reason"] = None
        self._status.set(f"Index repaired ({result}).")
        self._clear_mismatch_tags(ws, [sess])

    def _repair_all(self, ws: dict):
        """Repair every mismatched session in one workspace at once."""
        mismatched = [
            s for s in ws["sessions"] if s.get("mismatch_reason") and (
                s.get("source") != "disk" or s.get("has_requests"))
        ]
        if not mismatched:
            messagebox.showinfo("Nothing to Repair",
                                "No index mismatches found in this workspace.",
                                parent=self)
            return

        db = ws["dir"] / "state.vscdb"
        if not db.exists():
            messagebox.showerror("Repair Error",
                                 "state.vscdb not found.",
                                 parent=self)
            return

        _MAX = 20
        shown = mismatched[:_MAX]
        summary = "\n".join(f"  [{s.get('source','?')}] {s['title']}"
                            for s in shown)
        if len(mismatched) > _MAX:
            summary += f"\n  … and {len(mismatched) - _MAX} more"
        msg = (f"Repair {len(mismatched)} mismatched session(s) in:\n"
               f"  {ws['name']}\n\n"
               f"{summary}\n\n"
               f"A single .repair-backup will be created before any changes.")
        if not messagebox.askyesno("Repair All in Group", msg, parent=self):
            return

        if not self._ensure_vscode_closed():
            return

        try:
            n = action_repair_all(ws["dir"])
        except Exception as e:
            messagebox.showerror("Repair Failed", str(e), parent=self)
            return

        for sess in mismatched:
            if sess.get("source") == "disk":
                sess["source"] = "both"
            sess["mismatch_reason"] = None
        self._status.set(f"Repaired {n} session(s).")
        self._clear_mismatch_tags(ws, mismatched)

    def _pick_workspace_dialog(self,
                               title: str,
                               prompt: str,
                               exclude_ws: dict | None = None) -> dict | None:
        """Searchable workspace picker dialog; returns chosen ws or None."""
        candidates = [
            w for w in self._workspaces
            if exclude_ws is None or w["dir"] != exclude_ws["dir"]
        ]
        if not candidates:
            messagebox.showinfo(title,
                                "No other workspaces available.",
                                parent=self)
            return None

        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("540x360")
        win.resizable(True, True)
        win.grab_set()
        win.focus_set()

        ttk.Label(win,
                  text=prompt,
                  wraplength=500,
                  justify=tk.LEFT,
                  padding=(12, 10, 12, 0)).pack(fill=tk.X)

        frow = ttk.Frame(win, padding=(12, 6, 12, 4))
        frow.pack(fill=tk.X)
        ttk.Label(frow, text="Filter:").pack(side=tk.LEFT)
        fvar = tk.StringVar()
        ttk.Entry(frow, textvariable=fvar).pack(side=tk.LEFT,
                                                fill=tk.X,
                                                expand=True,
                                                padx=(6, 0))

        lframe = ttk.Frame(win, padding=(12, 0, 12, 0))
        lframe.pack(fill=tk.BOTH, expand=True)
        lb = tk.Listbox(lframe,
                        selectmode=tk.SINGLE,
                        activestyle="dotbox",
                        font=("Segoe UI", 9))
        sb = ttk.Scrollbar(lframe, orient=tk.VERTICAL, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.pack(fill=tk.BOTH, expand=True)

        shown: list[int] = []

        def refresh(*_):
            term = fvar.get().lower().strip()
            lb.delete(0, tk.END)
            shown.clear()
            for i, w in enumerate(candidates):
                if term and term not in w["name"].lower():
                    continue
                shown.append(i)
                n = len(w["sessions"])
                lb.insert(
                    tk.END,
                    f"{w['name']}  ({n} session{'s' if n != 1 else ''})")
            if shown:
                lb.selection_set(0)
                lb.activate(0)

        fvar.trace_add("write", refresh)
        refresh()

        result: list[dict | None] = [None]

        def on_ok(*_):
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning(title,
                                       "Please select a workspace.",
                                       parent=win)
                return
            result[0] = candidates[shown[sel[0]]]
            win.destroy()

        lb.bind("<Double-1>", on_ok)
        lb.bind("<Return>", on_ok)

        brow = ttk.Frame(win, padding=(12, 8))
        brow.pack(fill=tk.X)
        ttk.Button(brow, text="Select", command=on_ok).pack(side=tk.RIGHT,
                                                            padx=(4, 0))
        ttk.Button(brow, text="Cancel",
                   command=win.destroy).pack(side=tk.RIGHT)

        win.wait_window()
        return result[0]

    def _copy_session_to(self, ws_src: dict, sess: dict):
        """Copy one session (file + DB entry) to a chosen workspace."""
        if not sess.get("has_requests"):
            messagebox.showinfo(
                "Empty Session",
                "This session has no content — nothing to copy.",
                parent=self)
            return
        ws_dst = self._pick_workspace_dialog("Copy Session to Workspace",
                                             f"Copy \"{sess['title']}\" to:",
                                             exclude_ws=ws_src)
        if ws_dst is None:
            return

        existing = {s["id"] for s in ws_dst["sessions"]}
        if sess["id"] in existing:
            messagebox.showwarning(
                "Already Exists",
                f"A session with this ID already exists in \"{ws_dst['name']}\"."
                "\n\nNo changes were made.",
                parent=self)
            return

        if not messagebox.askyesno(
                "Confirm Copy", f"Copy session:\n  \"{sess['title']}\"\n\n"
                f"From:  {ws_src['name']}\n"
                f"To:    {ws_dst['name']}\n\n"
                "A .merge-backup of the target DB will be created.",
                parent=self):
            return

        if not self._ensure_vscode_closed():
            return

        self._do_copy_sessions(ws_src, ws_dst, [sess])

    def _copy_all_to(self, ws_src: dict):
        """Copy all non-empty sessions from ws_src to a chosen workspace."""
        sessions = [s for s in ws_src["sessions"] if s.get("has_requests")]
        if not sessions:
            messagebox.showinfo(
                "Nothing to Copy",
                "No sessions with content found in this workspace.",
                parent=self)
            return

        ws_dst = self._pick_workspace_dialog(
            "Copy All Sessions to Workspace",
            f"Copy all sessions from \"{ws_src['name']}\" to:",
            exclude_ws=ws_src)
        if ws_dst is None:
            return

        existing = {s["id"] for s in ws_dst["sessions"]}
        dupes = [s for s in sessions if s["id"] in existing]
        to_copy = [s for s in sessions if s["id"] not in existing]

        if not to_copy:
            messagebox.showinfo(
                "Nothing New",
                "All sessions already exist in the target workspace.",
                parent=self)
            return

        msg = (f"Copy {len(to_copy)} session(s)\n"
               f"From:  {ws_src['name']}\n"
               f"To:    {ws_dst['name']}")
        if dupes:
            msg += f"\n\n{len(dupes)} duplicate(s) will be skipped."
        msg += "\n\nA .merge-backup of the target DB will be created."

        if not messagebox.askyesno("Confirm Copy", msg, parent=self):
            return

        if not self._ensure_vscode_closed():
            return

        self._do_copy_sessions(ws_src, ws_dst, to_copy)

    def _do_copy_sessions(self, ws_src: dict, ws_dst: dict,
                          sessions: list[dict]):
        """Copy session files and update the target workspace DB index."""
        session_ids = [s["id"] for s in sessions]
        try:
            copied_ids = action_copy_sessions(ws_src["dir"], ws_dst["dir"],
                                              session_ids)
        except Exception as e:
            messagebox.showerror("Copy Failed", str(e), parent=self)
            return

        if not copied_ids:
            messagebox.showwarning("Nothing Copied",
                                   "No session files were found on disk.",
                                   parent=self)
            return

        existing = {s["id"] for s in ws_dst["sessions"]}
        for sess in sessions:
            if sess["id"] in copied_ids and sess["id"] not in existing:
                ws_dst["sessions"].append({
                    **sess, "source": "both",
                    "mismatch_reason": None
                })

        n = len(copied_ids)
        self._status.set(f"Copied {n} session(s) to \"{ws_dst['name']}\".")
        self._rebuild_tree()

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status.set(f"Copied: {text}")

    def _explore(self, path: Path):
        import subprocess, sys
        target = Path(path)
        if target.is_file():
            target = target.parent
        try:
            if sys.platform == "win32":
                os.startfile(str(target))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:
            self._status.set(f"Could not open file manager: {e}")

    def _show_ws_props(self, ws: dict):
        sessions = ws["sessions"]
        mtime_str = fmt_mtime(ws["mtime"])
        lines = [
            f"Name:            {ws['name']}",
            f"Storage folder:  {ws['dir']}",
            f"Workspace path:  {ws['path']}",
            f"Folder modified: {mtime_str}",
            f"Sessions:        {len(sessions)}",
        ]
        self._info_dialog(f"Workspace — {ws['name']}", "\n".join(lines))

    def _show_session_props(self, ws: dict, sess: dict):
        sf = session_file(ws["dir"], sess["id"])
        try:
            fsize = (f"{sf.stat().st_size:,} bytes"
                     if sf.exists() else "(not found)")
        except OSError:
            fsize = "(error)"
        file_ext = sf.suffix if sf.exists() else "(not found)"
        lines = [
            f"Title:        {sess['title']}",
            f"ID:           {sess['id']}",
            f"Last message: {fmt_ts(sess['ts'])}",
            f"File:         {sf}",
            f"Format:       {file_ext}",
            f"Size:         {fsize}",
            f"File created: {fmt_mtime(sess.get('file_ctime', 0)) or '(unknown)'}",
            f"Source:       {sess.get('source', 'unknown')}",
            f"Workspace:    {ws['name']}  ({ws['dir'].name})",
        ]
        if sess.get("mismatch_reason"):
            lines += ["", f"\u26a0 MISMATCH: {sess['mismatch_reason']}"]
        else:
            lines.append("Index:        OK (in sync)")
        self._info_dialog(f"Session — {sess['title']}", "\n".join(lines))

    def _info_dialog(self, title: str, body: str):
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.resizable(True, True)
        dlg.geometry("620x200")
        dlg.transient(self)
        txt = tk.Text(dlg,
                      wrap=tk.NONE,
                      font=("Courier New", 9),
                      padx=8,
                      pady=8,
                      relief=tk.FLAT)
        hsb = ttk.Scrollbar(dlg, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(xscrollcommand=hsb.set)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", body)
        txt.configure(state=tk.DISABLED)
        ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=4)

    # ── selection / display ───────────────────────────────────────────────────

    def _on_select(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        info = self._node_map.get(sel[0])
        if info:
            wi, si = info
            ws = self._workspaces[wi]
            sess = ws["sessions"][si]
            self._show_session(ws, sess)

    def _show_session(self, ws: dict, sess: dict):
        self._hdr_var.set(f"{ws['name']}  ›  {sess['title']}")
        self._status.set(f"Loading '{sess['title']}'…")
        self.update_idletasks()

        requests = load_requests(ws["dir"], sess["id"])

        self._txt.configure(state=tk.NORMAL)
        self._txt.delete("1.0", tk.END)

        if not requests:
            path = session_file(ws["dir"], sess["id"])
            self._txt.insert(tk.END, "(No messages found)\n", "meta")
            self._txt.insert(tk.END, f"Expected: {path}\n", "meta")
        else:
            for req in requests:
                ts = fmt_ts(req.get("timestamp"))
                ts_suffix = f"  {ts}" if ts else ""

                # User turn
                user_text = extract_user_text(req)
                self._txt.insert(tk.END, f" ▶ You{ts_suffix}\n", "u_role")
                if user_text.strip():
                    self._txt.insert(tk.END,
                                     user_text.rstrip() + "\n", "u_body")

                # AI thinking (optional)
                if self._show_thinking.get():
                    thinking = extract_thinking_text(req)
                    if thinking:
                        self._txt.insert(tk.END, " ◈ Thinking\n", "think_role")
                        self._txt.insert(tk.END, thinking + "\n", "think_body")

                # AI response
                ai_text = extract_response_text(req)
                self._txt.insert(tk.END, " ◆ Copilot\n", "a_role")
                if ai_text.strip():
                    self._txt.insert(tk.END, ai_text.rstrip() + "\n", "a_body")

        self._txt.configure(state=tk.DISABLED)
        self._txt.yview_moveto(0)
        self._status.set(
            f"'{sess['title']}'  ·  {len(requests)} turns  ·  {sess['id']}")

    # ── Delete / Archive / Restore ─────────────────────────────────────────────

    def _delete_session(self, ws: dict, sess: dict):
        """Delete a single session's file and DB entry."""
        msg = (f"Delete session:\n  \"{sess['title']}\"\n"
               f"  ID: {sess['id']}\n\n"
               f"The session file and DB index entry will be removed.\n"
               f"A .repair-backup will be created first.")
        if not messagebox.askyesno(
                "Delete Session Chat", msg, icon="warning", parent=self):
            return
        if not self._ensure_vscode_closed():
            return
        try:
            action_delete_session(ws["dir"], sess["id"])
        except Exception as e:
            messagebox.showerror("Delete Failed", str(e), parent=self)
            return
        ws["sessions"] = [s for s in ws["sessions"] if s["id"] != sess["id"]]
        self._rebuild_tree()
        self._status.set(f"Deleted session: {sess['title']}")

    def _delete_workspace_chats(self, ws: dict):
        """Delete all chat session files in a workspace."""
        cs_dir = ws["dir"] / "chatSessions"
        files = (list(cs_dir.glob("*.jsonl")) +
                 list(cs_dir.glob("*.json")) if cs_dir.is_dir() else [])
        msg = (f"Delete all chat sessions in:\n  {ws['name']}\n\n"
               f"  {len(files)} session file(s) will be removed.\n"
               f"A .repair-backup will be created first.")
        if not messagebox.askyesno(
                "Delete Workspace Chats", msg, icon="warning", parent=self):
            return
        if not self._ensure_vscode_closed():
            return
        try:
            action_delete_workspace_chats(ws["dir"])
        except Exception as e:
            messagebox.showerror("Delete Failed", str(e), parent=self)
            return
        ws["sessions"] = []
        self._rebuild_tree()
        self._status.set(f"Deleted {len(files)} session(s) from {ws['name']}.")
        if messagebox.askyesno(
                "Delete Workspace Storage Folder?",
                f"Also delete the entire workspace storage folder?\n\n"
                f"  {ws['dir']}\n\n"
                "WARNING: This permanently removes ALL VS Code state for this "
                "workspace.",
                icon="warning",
                parent=self):
            try:
                shutil.rmtree(str(ws["dir"]))
                self._workspaces = [
                    w for w in self._workspaces if w["dir"] != ws["dir"]
                ]
                self._rebuild_tree()
                self._status.set("Workspace storage folder deleted.")
            except Exception as e:
                messagebox.showerror("Delete Failed", str(e), parent=self)

    def _archive_session(self, ws: dict, sess: dict):
        """Zip a single session file to a user-chosen folder."""
        dest = askdirectory(title="Choose archive destination folder",
                            parent=self)
        if not dest:
            return
        try:
            zip_path = action_archive_session(ws["dir"], sess["id"],
                                              Path(dest))
            self._status.set(f"Archived to: {zip_path.name}")
            messagebox.showinfo("Archive Complete",
                                f"Session archived to:\n{zip_path}",
                                parent=self)
        except Exception as e:
            messagebox.showerror("Archive Failed", str(e), parent=self)

    def _archive_workspace(self, ws: dict):
        """Zip all chat session files in a workspace to a user-chosen folder."""
        cs_dir = ws["dir"] / "chatSessions"
        files = (list(cs_dir.glob("*.jsonl")) +
                 list(cs_dir.glob("*.json")) if cs_dir.is_dir() else [])
        if not files:
            messagebox.showinfo("Nothing to Archive",
                                "No session files found.",
                                parent=self)
            return
        dest = askdirectory(title="Choose archive destination folder",
                            parent=self)
        if not dest:
            return
        try:
            zip_path = action_archive_workspace(ws["dir"], Path(dest))
            self._status.set(
                f"Archived {len(files)} session(s) to: {zip_path.name}")
            messagebox.showinfo(
                "Archive Complete",
                f"Archived {len(files)} session(s) to:\n{zip_path}",
                parent=self)
        except Exception as e:
            messagebox.showerror("Archive Failed", str(e), parent=self)

    def _restore_chats(self, ws_hint: dict | None = None):
        """Restore session(s) from a chat archive zip into a chosen workspace."""
        zip_path_str = askopenfilename(title="Select chat archive zip",
                                       filetypes=[("Zip archives", "*.zip"),
                                                  ("All files", "*.*")],
                                       parent=self)
        if not zip_path_str:
            return
        zip_path = Path(zip_path_str)
        try:
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                names = [
                    n for n in zf.namelist()
                    if n.endswith(".jsonl") or n.endswith(".json")
                ]
        except Exception as e:
            messagebox.showerror("Invalid Archive", str(e), parent=self)
            return
        if not names:
            messagebox.showerror(
                "Invalid Archive",
                "No session files (.jsonl / .json) found in the archive.",
                parent=self)
            return
        ws_dst = self._pick_workspace_dialog(
            "Restore Chats to Workspace",
            f"Restore {len(names)} session(s) from archive into:")
        if ws_dst is None:
            return
        existing_ids = {s["id"] for s in ws_dst["sessions"]}
        to_restore = [n for n in names if Path(n).stem not in existing_ids]
        skipped = len(names) - len(to_restore)
        if not to_restore:
            messagebox.showinfo(
                "Nothing to Restore",
                "All sessions in the archive already exist in the target "
                "workspace.",
                parent=self)
            return
        msg = (f"Restore {len(to_restore)} session(s) into:\n"
               f"  {ws_dst['name']}\n")
        if skipped:
            msg += f"\n{skipped} session(s) already exist and will be skipped.\n"
        msg += "\nA .repair-backup will be created first."
        if not messagebox.askyesno("Restore from Archive", msg, parent=self):
            return
        if not self._ensure_vscode_closed():
            return
        try:
            restored_ids = action_restore_archive(zip_path, ws_dst["dir"])
        except Exception as e:
            messagebox.showerror("Restore Failed", str(e), parent=self)
            return
        ws_dst["sessions"] = load_session_index(ws_dst["dir"])
        self._rebuild_tree()
        self._status.set(
            f"Restored {len(restored_ids)} session(s) to {ws_dst['name']}.")
        messagebox.showinfo(
            "Restore Complete",
            f"Restored {len(restored_ids)} session(s) to:\n  {ws_dst['name']}",
            parent=self)

    def _write_chat(self, text: str):
        self._txt.configure(state=tk.NORMAL)
        self._txt.delete("1.0", tk.END)
        if text:
            self._txt.insert(tk.END, text)
        self._txt.configure(state=tk.DISABLED)


if __name__ == "__main__":
    app = ChatBrowser()
    app.mainloop()
