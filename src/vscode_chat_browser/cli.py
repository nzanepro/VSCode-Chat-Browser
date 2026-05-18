"""
cli.py

Command-line interface for VS Code Chat Browser operations.

Usage
-----
  python src/cli.py list   <storage_root>
  python src/cli.py show   <ws_dir> <session_id>
  python src/cli.py archive <ws_dir> <dest_dir> [--session <id>]
  python src/cli.py delete  <ws_dir> [--session <id>] [--no-backup]
  python src/cli.py copy    <src_ws_dir> <dst_ws_dir> --session <id> [<id>...] [--no-backup]
  python src/cli.py repair  <ws_dir> [--session <id>] [--no-backup]
  python src/cli.py restore <zip_path> <ws_dir> [--no-backup]

<ws_dir> is the workspace's *storage* subfolder (the hash-named directory inside
workspaceStorage), e.g.:
  C:\\Users\\you\\AppData\\Roaming\\Code\\User\\workspaceStorage\\43d22b07bf23d2dd

Pass the workspaceStorage root to `list` to enumerate all workspaces.
"""

import argparse
import json
import sys
from pathlib import Path

# Relative import when installed as a package; fall back to bare name when
# running directly as `python src/vscode_chat_browser/cli.py` with the package dir on sys.path.
try:
    from .core import (
        WORKSPACESTORAGE,
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
        fmt_ts,
        load_requests,
        load_session_index,
        workspace_display_name,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from core import (  # type: ignore[no-redef]
        WORKSPACESTORAGE, action_archive_session, action_archive_workspace,
        action_copy_sessions, action_delete_session,
        action_delete_workspace_chats, action_repair_all,
        action_repair_session, action_restore_archive, extract_response_text,
        extract_thinking_text, extract_user_text, fmt_ts, load_requests,
        load_session_index, workspace_display_name,
    )

# ── helpers ───────────────────────────────────────────────────────────────────


def _ws_dir(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_dir():
        raise argparse.ArgumentTypeError(f"Directory not found: {path_str}")
    return p


def _zip_file(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_file():
        raise argparse.ArgumentTypeError(f"File not found: {path_str}")
    return p


# ── sub-command handlers ──────────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    storage_root = Path(args.storage_root)
    if not storage_root.is_dir():
        print(f"ERROR: not a directory: {storage_root}", file=sys.stderr)
        return 1

    subdirs = sorted(d for d in storage_root.iterdir() if d.is_dir())
    total_ws = total_sess = 0
    for d in subdirs:
        sessions = load_session_index(d)
        if not sessions:
            continue
        name, path = workspace_display_name(d)
        total_ws += 1
        print(f"\n{'─'*60}")
        print(f"  Workspace : {name}")
        print(f"  Path      : {path}")
        print(f"  Storage   : {d}")
        print(f"  Sessions  : {len(sessions)}")
        for s in sessions:
            mm = " ⚠ " + s["mismatch_reason"] if s.get(
                "mismatch_reason") else ""
            flag = " [empty]" if not s.get("has_requests") else ""
            print(f"    {s['id']}  {fmt_ts(s['ts']) or '(no date)':>16}"
                  f"  {s['title']}{flag}{mm}")
        total_sess += len(sessions)

    print(f"\n{'='*60}")
    print(f"  {total_ws} workspaces · {total_sess} sessions")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    ws_dir = Path(args.ws_dir)
    reqs = load_requests(ws_dir, args.session_id)
    if not reqs:
        print(f"No messages found for session {args.session_id!r}",
              file=sys.stderr)
        return 1
    for i, req in enumerate(reqs, 1):
        ts = fmt_ts(req.get("timestamp"))
        print(f"\n{'─'*60}")
        print(f"[{i}] You  {ts}")
        print(extract_user_text(req))
        if args.thinking:
            thinking = extract_thinking_text(req)
            if thinking:
                print("\n  [thinking]")
                for line in thinking.splitlines():
                    print(f"  {line}")
        print(f"\n[{i}] Copilot")
        print(extract_response_text(req))
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    ws_dir = Path(args.ws_dir)
    dest_dir = Path(args.dest_dir)
    try:
        if args.session:
            zip_path = action_archive_session(ws_dir, args.session, dest_dir)
        else:
            zip_path = action_archive_workspace(ws_dir, dest_dir)
        print(f"Archived → {zip_path}")
        return 0
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_delete(args: argparse.Namespace) -> int:
    ws_dir = Path(args.ws_dir)
    do_backup = not args.no_backup
    try:
        if args.session:
            action_delete_session(ws_dir, args.session, backup=do_backup)
            print(f"Deleted session {args.session!r}")
        else:
            n = action_delete_workspace_chats(ws_dir, backup=do_backup)
            print(f"Deleted {n} session file(s) from {ws_dir.name}")
        return 0
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_copy(args: argparse.Namespace) -> int:
    src = Path(args.src_ws_dir)
    dst = Path(args.dst_ws_dir)
    do_backup = not args.no_backup
    try:
        copied = action_copy_sessions(src, dst, args.session, backup=do_backup)
        if copied:
            print(f"Copied {len(copied)} session(s) to {dst.name}:")
            for sid in copied:
                print(f"  {sid}")
        else:
            print("Nothing copied (no matching files found on disk).")
        return 0
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_repair(args: argparse.Namespace) -> int:
    ws_dir = Path(args.ws_dir)
    do_backup = not args.no_backup
    try:
        if args.session:
            result = action_repair_session(ws_dir,
                                           args.session,
                                           backup=do_backup)
            print(f"Repair result for {args.session!r}: {result}")
        else:
            n = action_repair_all(ws_dir, backup=do_backup)
            print(f"Repaired {n} mismatch(es) in {ws_dir.name}")
        return 0
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_restore(args: argparse.Namespace) -> int:
    zip_path = Path(args.zip_path)
    ws_dir = Path(args.ws_dir)
    do_backup = not args.no_backup
    try:
        restored = action_restore_archive(zip_path, ws_dir, backup=do_backup)
        if restored:
            print(f"Restored {len(restored)} session(s) to {ws_dir.name}:")
            for sid in restored:
                print(f"  {sid}")
        else:
            print(
                "Nothing restored (all sessions already exist in destination)."
            )
        return 0
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


# ── argument parser ───────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chat_browser",
        description="VS Code Chat Browser — CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # list
    p_list = sub.add_parser("list", help="List workspaces and sessions")
    p_list.add_argument(
        "storage_root",
        nargs="?",
        default=str(WORKSPACESTORAGE),
        metavar="<storage_root>",
        help="workspaceStorage root (default: VS Code default)",
    )
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="Print conversation turns")
    p_show.add_argument("ws_dir", metavar="<ws_dir>")
    p_show.add_argument("session_id", metavar="<session_id>")
    p_show.add_argument("--thinking",
                        action="store_true",
                        help="Include reasoning blocks")
    p_show.set_defaults(func=cmd_show)

    # archive
    p_arc = sub.add_parser("archive", help="Zip session(s) to an archive")
    p_arc.add_argument("ws_dir", metavar="<ws_dir>")
    p_arc.add_argument("dest_dir", metavar="<dest_dir>")
    p_arc.add_argument("--session",
                       metavar="<id>",
                       help="Archive one session (omit to archive all)")
    p_arc.set_defaults(func=cmd_archive)

    # delete
    p_del = sub.add_parser("delete", help="Delete session(s)")
    p_del.add_argument("ws_dir", metavar="<ws_dir>")
    p_del.add_argument("--session",
                       metavar="<id>",
                       help="Delete one session (omit to delete all)")
    p_del.add_argument("--no-backup",
                       action="store_true",
                       help="Skip DB backup before deleting")
    p_del.set_defaults(func=cmd_delete)

    # copy
    p_copy = sub.add_parser("copy", help="Copy session(s) between workspaces")
    p_copy.add_argument("src_ws_dir", metavar="<src_ws_dir>")
    p_copy.add_argument("dst_ws_dir", metavar="<dst_ws_dir>")
    p_copy.add_argument("--session",
                        metavar="<id>",
                        nargs="+",
                        required=True,
                        help="One or more session IDs to copy")
    p_copy.add_argument("--no-backup",
                        action="store_true",
                        help="Skip DB backup before copying")
    p_copy.set_defaults(func=cmd_copy)

    # repair
    p_rep = sub.add_parser("repair",
                           help="Repair DB index mismatches in a workspace")
    p_rep.add_argument("ws_dir", metavar="<ws_dir>")
    p_rep.add_argument("--session",
                       metavar="<id>",
                       help="Repair one session (omit to repair all)")
    p_rep.add_argument("--no-backup",
                       action="store_true",
                       help="Skip DB backup before repairing")
    p_rep.set_defaults(func=cmd_repair)

    # restore
    p_res = sub.add_parser("restore", help="Restore sessions from an archive")
    p_res.add_argument("zip_path", metavar="<zip_path>")
    p_res.add_argument("ws_dir", metavar="<ws_dir>")
    p_res.add_argument("--no-backup",
                       action="store_true",
                       help="Skip DB backup before restoring")
    p_res.set_defaults(func=cmd_restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
