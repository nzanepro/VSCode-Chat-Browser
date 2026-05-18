"""
make_demo_storage.py

Generates a fictional workspaceStorage directory that looks like a real
VS Code workspaceStorage tree.  Use this to take screenshots of the UI
without exposing real chat history.

Usage
-----
  python tests/fixtures/make_demo_storage.py
  # → writes to tests/fixtures/demo_storage/  (default)

  python tests/fixtures/make_demo_storage.py /path/to/output
  # → writes to the given directory

Then launch the UI pointing at it:
  python src/vscode_chat_browser/cli.py ui --storage-root tests/fixtures/demo_storage
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

# ── helpers ───────────────────────────────────────────────────────────────────


def _ts(dt: datetime) -> int:
    """Return a millisecond UTC timestamp from a naive/aware datetime."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


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


def _db_entry(session_id: str, title: str, ts_ms: int) -> dict:
    return {
        "sessionId": session_id,
        "title": title,
        "lastMessageDate": ts_ms,
        "timing": {
            "created": ts_ms - 60_000
        },
        "initialLocation": "panel",
        "hasPendingEdits": False,
        "isEmpty": False,
        "isExternal": False,
        "lastResponseState": 1,
    }


def _jsonl_session(session_id: str, title: str, turns: list[dict]) -> str:
    """Produce a JSONL session string from a list of {user, assistant} dicts."""
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
            "v": title
        }),
    ]
    for i, turn in enumerate(turns, 1):
        req = {
            "id": f"req-{session_id[:4]}-{i}",
            "timestamp": turn["ts"],
            "message": {
                "text": turn["user"]
            },
            "response": [{
                "value": turn["assistant"]
            }],
        }
        if turn.get("thinking"):
            req["response"].append({
                "kind": "thinking",
                "value": turn["thinking"]
            })
        lines.append(json.dumps({"kind": 2, "k": ["requests"], "v": [req]}))
    return "\n".join(lines) + "\n"


def _write_workspace(
    base: Path,
    ws_hash: str,
    folder_uri: str,
    sessions: list[dict],
) -> None:
    """Build one workspace directory with its DB and session files."""
    ws = base / ws_hash
    cs = ws / "chatSessions"
    cs.mkdir(parents=True)

    (ws / "workspace.json").write_text(json.dumps({"folder": folder_uri}),
                                       encoding="utf-8")

    index: dict = {"version": 1, "entries": {}}
    for sess in sessions:
        sid = sess["id"]
        title = sess["title"]
        ts = sess["ts"]
        turns = sess["turns"]

        # Write the JSONL session file
        content = _jsonl_session(sid, title, turns)
        (cs / f"{sid}.jsonl").write_text(content, encoding="utf-8")

        index["entries"][sid] = _db_entry(sid, title, ts)

    _write_db(ws / "state.vscdb", index)


# ── demo data ─────────────────────────────────────────────────────────────────


def build(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Workspace 1: react-dashboard ─────────────────────────────────────────
    _write_workspace(
        out_dir,
        ws_hash="a3f8b2c1d4e5f601",
        folder_uri="file:///Users/dev/projects/react-dashboard",
        sessions=[
            {
                "id":
                "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
                "title":
                "Refactor data fetching hooks",
                "ts":
                _ts(datetime(2025, 4, 15, 14, 32)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 4, 15, 14, 32)),
                        "user":
                        "I have a custom `useFetch` hook that mixes data fetching, caching, and error handling all in one. How should I split it up?",
                        "assistant":
                        ("Good instinct to split this up — mixing three concerns in one hook makes it hard to test and reuse.\n\n"
                         "Here's a clean split:\n\n"
                         "**1. `useQuery` — raw fetch + loading/error state**\n"
                         "```ts\n"
                         "function useQuery<T>(url: string) {\n"
                         "  const [data, setData] = useState<T | null>(null);\n"
                         "  const [status, setStatus] = useState<'idle'|'loading'|'error'|'success'>('idle');\n"
                         "  useEffect(() => {\n"
                         "    setStatus('loading');\n"
                         "    fetch(url)\n"
                         "      .then(r => r.json())\n"
                         "      .then(d => { setData(d); setStatus('success'); })\n"
                         "      .catch(() => setStatus('error'));\n"
                         "  }, [url]);\n"
                         "  return { data, status };\n"
                         "}\n"
                         "```\n\n"
                         "**2. `useCache` — memoisation layer on top**\n"
                         "Wrap with `useMemo` or a `Map` ref keyed on `url`.\n\n"
                         "**3. `useDashboardData` — domain hook**\n"
                         "Compose the two above into your feature-specific hook.\n\n"
                         "This keeps each hook independently testable and the composition explicit."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 4, 15, 14, 41)),
                        "user":
                        "Should `useCache` live inside `useQuery` or be a separate wrapper?",
                        "assistant":
                        ("Keep it as a **separate wrapper**. Here's why:\n\n"
                         "- `useQuery` stays pure — it always fetches, making it easy to test in isolation.\n"
                         "- Consumers who don't need caching (e.g. a live-updating ticker) can use `useQuery` directly.\n"
                         "- The caching strategy (LRU, TTL, SWR) becomes a swap-out detail at the wrapper layer.\n\n"
                         "```ts\n"
                         "function useCachedQuery<T>(url: string, ttlMs = 30_000) {\n"
                         "  const cacheRef = useRef<Map<string, {data: T; ts: number}>>(new Map());\n"
                         "  const cached = cacheRef.current.get(url);\n"
                         "  if (cached && Date.now() - cached.ts < ttlMs) {\n"
                         "    return { data: cached.data, status: 'success' as const };\n"
                         "  }\n"
                         "  // fall through to live fetch\n"
                         "  return useQuery<T>(url);\n"
                         "}\n"
                         "```\n\n"
                         "Note the `if` before `useQuery` is only safe at module scope (rules of hooks). "
                         "In practice, store the cache key in state and conditionally skip the effect instead."
                         ),
                        "thinking":
                        ("The user is asking about composition patterns for React hooks. "
                         "The key constraint is rules-of-hooks — you cannot call a hook conditionally. "
                         "I should point that out while still showing the intent."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 4, 15, 14, 55)),
                        "user":
                        "Can you show me the corrected version that respects rules of hooks?",
                        "assistant":
                        ("```ts\n"
                         "function useCachedQuery<T>(url: string, ttlMs = 30_000) {\n"
                         "  const cacheRef = useRef<Map<string, {data: T; ts: number}>>(new Map());\n"
                         "  const { data, status } = useQuery<T>(url);  // always called\n\n"
                         "  useEffect(() => {\n"
                         "    if (data && status === 'success') {\n"
                         "      cacheRef.current.set(url, { data, ts: Date.now() });\n"
                         "    }\n"
                         "  }, [data, status, url]);\n\n"
                         "  const cached = cacheRef.current.get(url);\n"
                         "  if (cached && Date.now() - cached.ts < ttlMs) {\n"
                         "    return { data: cached.data, status: 'success' as const };\n"
                         "  }\n"
                         "  return { data, status };\n"
                         "}\n"
                         "```\n\n"
                         "Now `useQuery` is always called unconditionally. The cache is checked *after* the hook runs, "
                         "so you return stale data while the fresh fetch completes in the background — "
                         "essentially the stale-while-revalidate pattern."),
                    },
                ],
            },
            {
                "id":
                "2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e",
                "title":
                "Tailwind CSS dark mode theming",
                "ts":
                _ts(datetime(2025, 3, 28, 9, 15)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 3, 28, 9, 15)),
                        "user":
                        "How do I set up dark mode in Tailwind v3 using the `class` strategy?",
                        "assistant":
                        ("In `tailwind.config.ts` set `darkMode: 'class'`:\n\n"
                         "```ts\n"
                         "// tailwind.config.ts\n"
                         "export default {\n"
                         "  darkMode: 'class',\n"
                         "  content: ['./src/**/*.{ts,tsx}'],\n"
                         "  theme: { extend: {} },\n"
                         "  plugins: [],\n"
                         "};\n"
                         "```\n\n"
                         "Then toggle the `dark` class on `<html>` (or a root container):\n\n"
                         "```ts\n"
                         "document.documentElement.classList.toggle('dark');\n"
                         "```\n\n"
                         "Use `dark:` variants in your components:\n"
                         "```tsx\n"
                         "<div className=\"bg-white text-gray-900 dark:bg-gray-900 dark:text-gray-100\">\n"
                         "  Dashboard\n"
                         "</div>\n"
                         "```"),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 3, 28, 9, 28)),
                        "user":
                        "How do I persist the user's dark mode preference across reloads?",
                        "assistant":
                        ("Store the preference in `localStorage` and apply it before the first paint "
                         "to avoid a flash of the wrong theme:\n\n"
                         "```ts\n"
                         "// theme.ts  — call this in a <script> tag in <head> (not in React)\n"
                         "const saved = localStorage.getItem('theme');\n"
                         "const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;\n"
                         "if (saved === 'dark' || (!saved && prefersDark)) {\n"
                         "  document.documentElement.classList.add('dark');\n"
                         "}\n"
                         "```\n\n"
                         "In your React context:\n"
                         "```tsx\n"
                         "function toggleTheme() {\n"
                         "  const isDark = document.documentElement.classList.toggle('dark');\n"
                         "  localStorage.setItem('theme', isDark ? 'dark' : 'light');\n"
                         "}\n"
                         "```\n\n"
                         "The inline `<script>` runs synchronously before React hydrates, "
                         "so there's no flash."),
                    },
                ],
            },
            {
                "id":
                "3c4d5e6f-7a8b-9c0d-1e2f-3a4b5c6d7e8f",
                "title":
                "TypeScript generics in Table component",
                "ts":
                _ts(datetime(2025, 2, 11, 16, 5)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 2, 11, 16, 5)),
                        "user":
                        "My `Table` component accepts `columns` and `data` but TypeScript can't infer the row type from the column accessor keys. How do I fix the typings?",
                        "assistant":
                        ("The key is to make `Table` generic over the row type `T` and constrain "
                         "`columns` to use `keyof T` as the accessor:\n\n"
                         "```ts\n"
                         "interface Column<T> {\n"
                         "  key: keyof T;\n"
                         "  header: string;\n"
                         "  render?: (value: T[keyof T], row: T) => React.ReactNode;\n"
                         "}\n\n"
                         "interface TableProps<T> {\n"
                         "  data: T[];\n"
                         "  columns: Column<T>[];\n"
                         "}\n\n"
                         "function Table<T>({ data, columns }: TableProps<T>) {\n"
                         "  return (\n"
                         "    <table>\n"
                         "      <thead><tr>{columns.map(c => <th key={String(c.key)}>{c.header}</th>)}</tr></thead>\n"
                         "      <tbody>\n"
                         "        {data.map((row, i) => (\n"
                         "          <tr key={i}>\n"
                         "            {columns.map(c => (\n"
                         "              <td key={String(c.key)}>{c.render ? c.render(row[c.key], row) : String(row[c.key])}</td>\n"
                         "            ))}\n"
                         "          </tr>\n"
                         "        ))}\n"
                         "      </tbody>\n"
                         "    </table>\n"
                         "  );\n"
                         "}\n"
                         "```\n\n"
                         "TypeScript will now infer `T` from `data` and enforce that every `column.key` is a valid property of that type."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 2, 11, 16, 20)),
                        "user":
                        "What if a column's `render` function should only accept the specific value type for that key, not `T[keyof T]`?",
                        "assistant":
                        ("Use a mapped/distributive trick with a helper type:\n\n"
                         "```ts\n"
                         "type Column<T> = {\n"
                         "  [K in keyof T]: {\n"
                         "    key: K;\n"
                         "    header: string;\n"
                         "    render?: (value: T[K], row: T) => React.ReactNode;\n"
                         "  };\n"
                         "}[keyof T];\n"
                         "```\n\n"
                         "This is a **distributive object type** — it creates a union of column shapes, "
                         "one per key, so `render` receives the exact type for that key rather than the wide union `T[keyof T]`.\n\n"
                         "Usage stays the same:\n"
                         "```ts\n"
                         "const cols: Column<User>[] = [\n"
                         "  { key: 'age', header: 'Age', render: (v) => `${v} yrs` }, // v: number ✓\n"
                         "];\n"
                         "```"),
                    },
                ],
            },
        ],
    )

    # ── Workspace 2: auth-service ─────────────────────────────────────────────
    _write_workspace(
        out_dir,
        ws_hash="7c9e1d2a5f3b8042",
        folder_uri="file:///Users/dev/projects/auth-service",
        sessions=[
            {
                "id":
                "4d5e6f7a-8b9c-0d1e-2f3a-4b5c6d7e8f9a",
                "title":
                "JWT refresh token rotation",
                "ts":
                _ts(datetime(2025, 4, 20, 10, 0)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 4, 20, 10, 0)),
                        "user":
                        "What's the safest way to implement refresh token rotation in a FastAPI app?",
                        "assistant":
                        ("Refresh token rotation means issuing a new refresh token every time the old one is used. "
                         "Here's the pattern:\n\n"
                         "1. **Store a hash of the refresh token** (not the raw token) in your DB alongside a `family_id`.\n"
                         "2. On `/token/refresh`:\n"
                         "   - Verify the token signature and find the matching DB row.\n"
                         "   - If found and not revoked → issue a new access token + new refresh token; revoke the old one.\n"
                         "   - If already revoked → **revoke the entire family** (detects token theft).\n\n"
                         "```python\n"
                         "@router.post('/token/refresh')\n"
                         "async def refresh(token: str, db: AsyncSession = Depends(get_db)):\n"
                         "    payload = verify_jwt(token, secret=REFRESH_SECRET)\n"
                         "    stored = await db.get(RefreshToken, payload['jti'])\n"
                         "    if not stored or stored.revoked:\n"
                         "        await revoke_family(db, payload['family_id'])\n"
                         "        raise HTTPException(401, 'Token reuse detected')\n"
                         "    stored.revoked = True\n"
                         "    new_rt = issue_refresh_token(family_id=stored.family_id)\n"
                         "    new_at = issue_access_token(sub=stored.user_id)\n"
                         "    db.add(new_rt)\n"
                         "    await db.commit()\n"
                         "    return {'access_token': new_at, 'refresh_token': new_rt.token}\n"
                         "```\n\n"
                         "Keep the refresh token TTL short (7–14 days) and use `Secure; HttpOnly; SameSite=Strict` cookies for storage."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 4, 20, 10, 18)),
                        "user":
                        "How should I handle the race condition where two requests hit /token/refresh simultaneously with the same refresh token?",
                        "assistant":
                        ("Use a **database-level optimistic lock** (or `SELECT FOR UPDATE`) so only one request wins:\n\n"
                         "```python\n"
                         "# With SQLAlchemy async + PostgreSQL\n"
                         "async with db.begin():\n"
                         "    stored = await db.execute(\n"
                         "        select(RefreshToken)\n"
                         "        .where(RefreshToken.jti == jti)\n"
                         "        .with_for_update(skip_locked=True)  # or nowait\n"
                         "    )\n"
                         "    stored = stored.scalar_one_or_none()\n"
                         "    if not stored:\n"
                         "        raise HTTPException(409, 'Token already consumed')\n"
                         "    # ... proceed with rotation\n"
                         "```\n\n"
                         "`skip_locked=True` means the second concurrent request gets `None` back immediately "
                         "and can return a 409, preventing a double-spend without blocking."
                         ),
                        "thinking":
                        ("The race condition here is a classic double-spend problem. "
                         "The cleanest solution at the DB layer is a row-level lock. "
                         "I should mention both `SKIP LOCKED` and `NOWAIT` variants."
                         ),
                    },
                ],
            },
            {
                "id":
                "5e6f7a8b-9c0d-1e2f-3a4b-5c6d7e8f9a0b",
                "title":
                "OAuth2 PKCE flow implementation",
                "ts":
                _ts(datetime(2025, 3, 14, 11, 30)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 3, 14, 11, 30)),
                        "user":
                        "Walk me through implementing the PKCE flow for a public client (React SPA).",
                        "assistant":
                        ("PKCE (Proof Key for Code Exchange) prevents auth code interception for clients that can't keep a secret. Here are the steps:\n\n"
                         "**Step 1 — Generate a code verifier and challenge**\n"
                         "```ts\n"
                         "function generatePKCE() {\n"
                         "  const verifier = crypto.randomUUID().replace(/-/g, '') + crypto.randomUUID().replace(/-/g, '');\n"
                         "  return crypto.subtle\n"
                         "    .digest('SHA-256', new TextEncoder().encode(verifier))\n"
                         "    .then(buf => ({\n"
                         "      verifier,\n"
                         "      challenge: btoa(String.fromCharCode(...new Uint8Array(buf)))\n"
                         "        .replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, ''),\n"
                         "    }));\n"
                         "}\n"
                         "```\n\n"
                         "**Step 2 — Redirect to authorization endpoint**\n"
                         "Include `code_challenge` and `code_challenge_method=S256` in the query string.\n\n"
                         "**Step 3 — Exchange code for tokens**\n"
                         "Include the original `code_verifier` (never the challenge) in the token request body.\n\n"
                         "Store the verifier in `sessionStorage` — not `localStorage` — because it only needs to survive the redirect."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 3, 14, 11, 52)),
                        "user":
                        "Why `sessionStorage` specifically? Couldn't an attacker in the same tab read it?",
                        "assistant":
                        ("Yes, any script running in the same tab can read `sessionStorage` — that's the "
                         "trade-off. The choice is about **threat model scope**:\n\n"
                         "| Storage | XSS in same tab | XSS in another tab | Tab survives close |\n"
                         "|---------|-----------------|--------------------|--------------------|\n"
                         "| `sessionStorage` | Exposed | Not exposed | No |\n"
                         "| `localStorage` | Exposed | Exposed | Yes |\n"
                         "| In-memory variable | Exposed | Not exposed | No |\n\n"
                         "`sessionStorage` is preferred over `localStorage` because:\n"
                         "1. The verifier is short-lived (seconds to minutes) — no value in persisting it.\n"
                         "2. It doesn't propagate to other tabs, reducing the blast radius.\n\n"
                         "For the highest security, hold the verifier in a closure/module variable and never write it to any Web Storage at all — "
                         "but you then lose the ability to survive the OAuth redirect in some edge cases."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 3, 14, 12, 10)),
                        "user":
                        "What's the right way to validate the `state` parameter on the redirect back?",
                        "assistant":
                        ("The `state` parameter prevents CSRF. The flow:\n\n"
                         "1. Generate a cryptographically random value before the redirect:\n"
                         "```ts\n"
                         "const state = crypto.getRandomValues(new Uint32Array(2)).join('-');\n"
                         "sessionStorage.setItem('oauth_state', state);\n"
                         "```\n\n"
                         "2. Include it in the authorization URL: `&state=<value>`.\n\n"
                         "3. On the callback route, **compare immediately before doing anything else**:\n"
                         "```ts\n"
                         "const params = new URLSearchParams(window.location.search);\n"
                         "const returnedState = params.get('state');\n"
                         "const savedState = sessionStorage.getItem('oauth_state');\n"
                         "sessionStorage.removeItem('oauth_state');  // consume it\n"
                         "if (!returnedState || returnedState !== savedState) {\n"
                         "  throw new Error('State mismatch — possible CSRF');\n"
                         "}\n"
                         "```\n\n"
                         "Remove it from storage immediately after the check so it can't be replayed."
                         ),
                    },
                ],
            },
            {
                "id":
                "6f7a8b9c-0d1e-2f3a-4b5c-6d7e8f9a0b1c",
                "title":
                "Password hashing with bcrypt vs Argon2",
                "ts":
                _ts(datetime(2025, 1, 22, 15, 0)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 1, 22, 15, 0)),
                        "user":
                        "Should I use bcrypt or Argon2 for new projects?",
                        "assistant":
                        ("For new projects in 2025, prefer **Argon2id** — it's the winner of the Password Hashing Competition "
                         "and is recommended by OWASP over bcrypt for new code.\n\n"
                         "Key differences:\n\n"
                         "| | bcrypt | Argon2id |\n"
                         "|-|--------|----------|\n"
                         "| Memory hardness | No (CPU only) | Yes |\n"
                         "| Parallelism tuning | No | Yes |\n"
                         "| Password length limit | 72 bytes | Unlimited |\n"
                         "| Library maturity | Very high | High |\n\n"
                         "Argon2id's memory hardness makes GPU/ASIC attacks much more expensive.\n\n"
                         "In Python:\n"
                         "```python\n"
                         "from argon2 import PasswordHasher\n"
                         "ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)\n"
                         "hashed = ph.hash('super-secret')\n"
                         "ph.verify(hashed, 'super-secret')  # raises VerifyMismatchError on failure\n"
                         "```\n\n"
                         "If you need to stay on bcrypt for compatibility, use `passlib[bcrypt]` with `rounds=12`."
                         ),
                    },
                ],
            },
        ],
    )

    # ── Workspace 3: data-pipeline ────────────────────────────────────────────
    _write_workspace(
        out_dir,
        ws_hash="2d5f8a1b3c4e9053",
        folder_uri="file:///Users/dev/projects/data-pipeline",
        sessions=[
            {
                "id":
                "7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
                "title":
                "Optimise Pandas CSV ingestion pipeline",
                "ts":
                _ts(datetime(2025, 4, 18, 9, 0)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 4, 18, 9, 0)),
                        "user":
                        "Reading a 2 GB CSV with `pd.read_csv` is taking 45 seconds. What are my options?",
                        "assistant":
                        ("Several techniques can cut that dramatically:\n\n"
                         "**1. Specify `dtype` upfront** — avoids Pandas doing two passes to infer types:\n"
                         "```python\n"
                         "dtypes = {'user_id': 'int32', 'amount': 'float32', 'status': 'category'}\n"
                         "df = pd.read_csv('data.csv', dtype=dtypes)\n"
                         "```\n\n"
                         "**2. Use `usecols`** — only load the columns you need:\n"
                         "```python\n"
                         "df = pd.read_csv('data.csv', usecols=['user_id', 'amount', 'ts'])\n"
                         "```\n\n"
                         "**3. Switch to Polars** — lazy evaluation + columnar reads:\n"
                         "```python\n"
                         "import polars as pl\n"
                         "df = pl.scan_csv('data.csv').select(['user_id', 'amount']).collect()\n"
                         "```\n"
                         "Polars is typically 5–10× faster for large CSVs.\n\n"
                         "**4. Chunk it** — if you're doing aggregations, read in chunks and combine:\n"
                         "```python\n"
                         "chunks = pd.read_csv('data.csv', chunksize=200_000)\n"
                         "result = pd.concat(chunk.query('amount > 0') for chunk in chunks)\n"
                         "```"),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 4, 18, 9, 22)),
                        "user":
                        "We're stuck on Pandas for now. After reading, writing the result back to Parquet also takes 30s. Why?",
                        "assistant":
                        ("Two common culprits:\n\n"
                         "**1. Object dtype columns** — if string columns are stored as `object`, the Parquet writer "
                         "must iterate row-by-row. Fix with `astype('string')` (nullable string) or `astype('category')` before writing.\n\n"
                         "**2. Default `engine='auto'` picking `fastparquet`** — `pyarrow` is usually faster:\n"
                         "```python\n"
                         "df.to_parquet('out.parquet', engine='pyarrow', compression='snappy')\n"
                         "```\n\n"
                         "Also check for mixed-type columns (`df.dtypes` — anything showing `object` that should be numeric "
                         "will slow both read and write). Run:\n"
                         "```python\n"
                         "print(df.memory_usage(deep=True).sum() / 1e6, 'MB')\n"
                         "```\n"
                         "If the in-memory size is much larger than the source CSV, you have type-inference bloat."
                         ),
                    },
                ],
            },
            {
                "id":
                "8b9c0d1e-2f3a-4b5c-6d7e-8f9a0b1c2d3e",
                "title":
                "Retry logic for S3 uploads with boto3",
                "ts":
                _ts(datetime(2025, 4, 10, 14, 0)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 4, 10, 14, 0)),
                        "user":
                        "How do I add exponential back-off retries to my boto3 S3 upload without reinventing the wheel?",
                        "assistant":
                        ("boto3 already has built-in retry logic via `botocore` — you just need to configure it:\n\n"
                         "```python\n"
                         "import boto3\n"
                         "from botocore.config import Config\n\n"
                         "config = Config(\n"
                         "    retries={\n"
                         "        'max_attempts': 5,\n"
                         "        'mode': 'adaptive',  # exponential + jitter\n"
                         "    }\n"
                         ")\n"
                         "s3 = boto3.client('s3', config=config)\n"
                         "s3.upload_file('local.parquet', 'my-bucket', 'uploads/local.parquet')\n"
                         "```\n\n"
                         "Mode options:\n"
                         "- `legacy` — basic fixed retry\n"
                         "- `standard` — exponential back-off (recommended)\n"
                         "- `adaptive` — standard + client-side rate limiting based on throttle responses\n\n"
                         "For large files, prefer `upload_file` over `put_object` — it uses multipart upload automatically and retries per-part."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 4, 10, 14, 15)),
                        "user":
                        "What if I need to retry the whole job (not just the upload) when a downstream step fails?",
                        "assistant":
                        ("Use `tenacity` — it's the most ergonomic retry library for Python:\n\n"
                         "```python\n"
                         "from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type\n"
                         "from botocore.exceptions import ClientError\n\n"
                         "@retry(\n"
                         "    stop=stop_after_attempt(4),\n"
                         "    wait=wait_exponential(multiplier=1, min=2, max=30),\n"
                         "    retry=retry_if_exception_type((ClientError, ConnectionError)),\n"
                         "    reraise=True,\n"
                         ")\n"
                         "def run_pipeline(input_path: str) -> None:\n"
                         "    df = load_and_transform(input_path)\n"
                         "    upload_to_s3(df, bucket='my-bucket', key='output.parquet')\n"
                         "    register_in_catalog(key='output.parquet')\n"
                         "```\n\n"
                         "`reraise=True` means if all attempts fail, the original exception propagates "
                         "rather than a `tenacity.RetryError`, which makes your error logs cleaner."
                         ),
                    },
                ],
            },
            {
                "id":
                "9c0d1e2f-3a4b-5c6d-7e8f-9a0b1c2d3e4f",
                "title":
                "Airflow DAG for daily ETL",
                "ts":
                _ts(datetime(2025, 2, 5, 8, 30)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 2, 5, 8, 30)),
                        "user":
                        "What's the minimal Airflow 2.x DAG structure for a daily ETL that extracts from Postgres, transforms with Pandas, and loads to S3?",
                        "assistant":
                        ("```python\n"
                         "from datetime import datetime\n"
                         "from airflow.decorators import dag, task\n"
                         "from airflow.providers.postgres.hooks.postgres import PostgresHook\n"
                         "import pandas as pd, boto3\n\n"
                         "@dag(schedule='@daily', start_date=datetime(2025, 1, 1), catchup=False)\n"
                         "def daily_etl():\n\n"
                         "    @task()\n"
                         "    def extract() -> str:\n"
                         "        hook = PostgresHook(postgres_conn_id='pg_prod')\n"
                         "        df = hook.get_pandas_df('SELECT * FROM events WHERE date = CURRENT_DATE - 1')\n"
                         "        path = f'/tmp/events_{datetime.today().date()}.parquet'\n"
                         "        df.to_parquet(path, engine='pyarrow')\n"
                         "        return path\n\n"
                         "    @task()\n"
                         "    def transform(path: str) -> str:\n"
                         "        df = pd.read_parquet(path)\n"
                         "        df['revenue_usd'] = df['amount'] * df['fx_rate']\n"
                         "        out = path.replace('.parquet', '_transformed.parquet')\n"
                         "        df.to_parquet(out, engine='pyarrow')\n"
                         "        return out\n\n"
                         "    @task()\n"
                         "    def load(path: str) -> None:\n"
                         "        s3 = boto3.client('s3')\n"
                         "        key = f'etl/events/{path.split(\"/\")[-1]}'\n"
                         "        s3.upload_file(path, 'data-lake-bucket', key)\n\n"
                         "    load(transform(extract()))\n\n"
                         "daily_etl()\n"
                         "```\n\n"
                         "Using the TaskFlow API (`@task` decorators) keeps XCom passing implicit and the DAG definition clean. "
                         "The `catchup=False` prevents Airflow from back-filling on first deployment."
                         ),
                    },
                ],
            },
        ],
    )

    # ── Workspace 4: mobile-app ───────────────────────────────────────────────
    _write_workspace(
        out_dir,
        ws_hash="f1e2d3c4b5a69074",
        folder_uri="file:///Users/dev/projects/mobile-app",
        sessions=[
            {
                "id":
                "0d1e2f3a-4b5c-6d7e-8f9a-0b1c2d3e4f5a",
                "title":
                "React Native navigation stack setup",
                "ts":
                _ts(datetime(2025, 3, 5, 13, 0)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 3, 5, 13, 0)),
                        "user":
                        "How do I set up a bottom tab navigator inside a stack navigator with React Navigation 6?",
                        "assistant":
                        ("The typical pattern is a root stack with an `App` screen that holds the tab navigator:\n\n"
                         "```tsx\n"
                         "// navigation/RootStack.tsx\n"
                         "import { createNativeStackNavigator } from '@react-navigation/native-stack';\n"
                         "import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';\n\n"
                         "const Tab = createBottomTabNavigator();\n"
                         "function Tabs() {\n"
                         "  return (\n"
                         "    <Tab.Navigator>\n"
                         "      <Tab.Screen name=\"Home\" component={HomeScreen} />\n"
                         "      <Tab.Screen name=\"Profile\" component={ProfileScreen} />\n"
                         "    </Tab.Navigator>\n"
                         "  );\n"
                         "}\n\n"
                         "const Stack = createNativeStackNavigator();\n"
                         "export function RootStack() {\n"
                         "  return (\n"
                         "    <Stack.Navigator>\n"
                         "      <Stack.Screen name=\"App\" component={Tabs} options={{ headerShown: false }} />\n"
                         "      <Stack.Screen name=\"Detail\" component={DetailScreen} />\n"
                         "    </Stack.Navigator>\n"
                         "  );\n"
                         "}\n"
                         "```\n\n"
                         "`headerShown: false` on the `App` screen hides the stack header so only the tab bar shows. "
                         "Full-screen modals (`presentation: 'modal'`) still appear above the tab bar."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 3, 5, 13, 20)),
                        "user":
                        "How do I navigate from a tab screen to the `Detail` screen in the root stack?",
                        "assistant":
                        ("Use the `useNavigation` hook with the root stack's `navigate` method. "
                         "Because the tab screen is nested inside the root stack, it has access to the parent navigator:\n\n"
                         "```tsx\n"
                         "import { useNavigation } from '@react-navigation/native';\n"
                         "import type { NativeStackNavigationProp } from '@react-navigation/native-stack';\n\n"
                         "type RootStackParams = {\n"
                         "  App: undefined;\n"
                         "  Detail: { itemId: string };\n"
                         "};\n\n"
                         "function HomeScreen() {\n"
                         "  const nav = useNavigation<NativeStackNavigationProp<RootStackParams>>();\n"
                         "  return (\n"
                         "    <Button\n"
                         "      title=\"Open Detail\"\n"
                         "      onPress={() => nav.navigate('Detail', { itemId: '42' })}\n"
                         "    />\n"
                         "  );\n"
                         "}\n"
                         "```\n\n"
                         "React Navigation automatically bubbles the `navigate` call up to the nearest navigator that can handle `'Detail'`."
                         ),
                    },
                ],
            },
            {
                "id":
                "1e2f3a4b-5c6d-7e8f-9a0b-1c2d3e4f5a6b",
                "title":
                "Offline sync with WatermelonDB",
                "ts":
                _ts(datetime(2025, 2, 18, 10, 45)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 2, 18, 10, 45)),
                        "user":
                        "We want offline-first sync in the mobile app. Is WatermelonDB still the right choice in 2025?",
                        "assistant":
                        ("WatermelonDB is still a solid choice for offline-first React Native apps, "
                         "especially when you have relational data and need incremental sync.\n\n"
                         "**Pros in 2025:**\n"
                         "- SQLite-backed (fast, battle-tested)\n"
                         "- Built-in sync protocol with `synchronize()` — you just implement two server endpoints\n"
                         "- Lazy loading keeps the main thread unblocked\n"
                         "- TypeScript support is good\n\n"
                         "**Consider alternatives if:**\n"
                         "- Your data is mostly flat key-value → `MMKV` or `AsyncStorage` suffices\n"
                         "- You want a hosted sync backend → `Realm` (Atlas Device Sync) or `PowerSync`\n"
                         "- You're on Expo without custom native modules → wait for Expo SQLite's sync story to mature\n\n"
                         "For a custom backend, the WatermelonDB sync protocol is well-documented and the two-endpoint design "
                         "(`/pull` and `/push`) maps cleanly to a REST API."),
                    },
                ],
            },
        ],
    )

    # ── Workspace 5: infra-as-code ────────────────────────────────────────────
    _write_workspace(
        out_dir,
        ws_hash="e5d4c3b2a1f09085",
        folder_uri="file:///Users/dev/projects/infra-as-code",
        sessions=[
            {
                "id":
                "2f3a4b5c-6d7e-8f9a-0b1c-2d3e4f5a6b7c",
                "title":
                "Terraform remote state with S3 and DynamoDB",
                "ts":
                _ts(datetime(2025, 4, 22, 16, 0)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 4, 22, 16, 0)),
                        "user":
                        "How do I configure Terraform remote state in S3 with DynamoDB locking?",
                        "assistant":
                        ("```hcl\n"
                         "# backend.tf\n"
                         "terraform {\n"
                         "  backend \"s3\" {\n"
                         "    bucket         = \"my-tf-state-prod\"\n"
                         "    key            = \"services/auth-service/terraform.tfstate\"\n"
                         "    region         = \"us-east-1\"\n"
                         "    encrypt        = true\n"
                         "    dynamodb_table = \"terraform-lock\"\n"
                         "  }\n"
                         "}\n"
                         "```\n\n"
                         "The DynamoDB table needs a `LockID` partition key (String type). Create it once:\n\n"
                         "```bash\n"
                         "aws dynamodb create-table \\\n"
                         "  --table-name terraform-lock \\\n"
                         "  --attribute-definitions AttributeName=LockID,AttributeType=S \\\n"
                         "  --key-schema AttributeName=LockID,KeyType=HASH \\\n"
                         "  --billing-mode PAY_PER_REQUEST\n"
                         "```\n\n"
                         "Terraform acquires a lock before `plan`/`apply` and releases it after. "
                         "If a run is killed, delete the `LockID` row manually or use `terraform force-unlock <id>`."
                         ),
                    },
                    {
                        "ts":
                        _ts(datetime(2025, 4, 22, 16, 18)),
                        "user":
                        "How should I structure the S3 key for multiple environments and services?",
                        "assistant":
                        ("A common convention:\n\n"
                         "```\n"
                         "<env>/<service>/<component>/terraform.tfstate\n"
                         "```\n\n"
                         "Examples:\n"
                         "```\n"
                         "prod/auth-service/rds/terraform.tfstate\n"
                         "prod/auth-service/ecs/terraform.tfstate\n"
                         "staging/auth-service/rds/terraform.tfstate\n"
                         "```\n\n"
                         "In `backend.tf`, reference a variable — but Terraform doesn't support variables in `backend` blocks. "
                         "Use **partial configuration** instead:\n\n"
                         "```bash\n"
                         "terraform init \\\n"
                         "  -backend-config=\"key=prod/auth-service/rds/terraform.tfstate\"\n"
                         "```\n\n"
                         "Or use a tool like **Terragrunt** which templates backend configs across environments automatically."
                         ),
                    },
                ],
            },
            {
                "id":
                "3a4b5c6d-7e8f-9a0b-1c2d-3e4f5a6b7c8d",
                "title":
                "GitHub Actions CI/CD for Python microservice",
                "ts":
                _ts(datetime(2025, 3, 30, 14, 30)),
                "turns": [
                    {
                        "ts":
                        _ts(datetime(2025, 3, 30, 14, 30)),
                        "user":
                        "Write a GitHub Actions workflow that lints, tests, builds a Docker image, and pushes to ECR on merge to main.",
                        "assistant":
                        ("```yaml\n"
                         "# .github/workflows/ci-cd.yml\n"
                         "name: CI/CD\n\n"
                         "on:\n"
                         "  push:\n"
                         "    branches: [main]\n"
                         "  pull_request:\n\n"
                         "env:\n"
                         "  AWS_REGION: us-east-1\n"
                         "  ECR_REPOSITORY: auth-service\n\n"
                         "jobs:\n"
                         "  test:\n"
                         "    runs-on: ubuntu-latest\n"
                         "    steps:\n"
                         "      - uses: actions/checkout@v4\n"
                         "      - uses: actions/setup-python@v5\n"
                         "        with: { python-version: '3.12' }\n"
                         "      - run: pip install -e '.[dev]'\n"
                         "      - run: ruff check .\n"
                         "      - run: pytest --tb=short\n\n"
                         "  build-push:\n"
                         "    needs: test\n"
                         "    if: github.ref == 'refs/heads/main'\n"
                         "    runs-on: ubuntu-latest\n"
                         "    permissions:\n"
                         "      id-token: write   # for OIDC\n"
                         "      contents: read\n"
                         "    steps:\n"
                         "      - uses: actions/checkout@v4\n"
                         "      - uses: aws-actions/configure-aws-credentials@v4\n"
                         "        with:\n"
                         "          role-to-assume: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/github-actions-ecr\n"
                         "          aws-region: ${{ env.AWS_REGION }}\n"
                         "      - uses: aws-actions/amazon-ecr-login@v2\n"
                         "        id: login-ecr\n"
                         "      - name: Build and push\n"
                         "        env:\n"
                         "          REGISTRY: ${{ steps.login-ecr.outputs.registry }}\n"
                         "          IMAGE_TAG: ${{ github.sha }}\n"
                         "        run: |\n"
                         "          docker build -t $REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .\n"
                         "          docker push $REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG\n"
                         "          docker tag $REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $REGISTRY/$ECR_REPOSITORY:latest\n"
                         "          docker push $REGISTRY/$ECR_REPOSITORY:latest\n"
                         "```\n\n"
                         "Uses OIDC (`id-token: write`) so no long-lived AWS credentials are stored as secrets."
                         ),
                    },
                ],
            },
        ],
    )

    print(f"Demo storage written to: {out_dir.resolve()}")
    print(f"  {len(list(out_dir.iterdir()))} workspaces")
    print()
    print("To launch the UI against this storage:")
    print(
        f"  python src/vscode_chat_browser/cli.py ui --storage-root {out_dir.resolve()}"
    )


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    default = Path(__file__).parent / "demo_storage"
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    build(target)
