"""CCR — the Content-addressed, Cached, Reversible store of originals.

This is the escape hatch that makes lossy *display* compression *safe*: a
compressor may drop detail from what the model sees, but only after handing the
original to :meth:`CCR.stash`, which stores it verbatim and returns a stable
placeholder. If the model later needs the dropped detail, it calls
``brainspace_retrieve`` with the placeholder and gets the exact original bytes back.

Why content-addressed?
    The store key is ``sha256(content)``. Identical content — the same file read
    twice, the same stack trace emitted twice, the same chunk retrieved by two
    different agents — hashes to the same key, so it is stored once and yields the
    *same placeholder every time*. That identity is two things at once:
      * **Dedup** — repeated context costs one store, not N.
      * **Cache stability** — a deterministic placeholder is a byte-identical
        block across requests, so it never perturbs the provider's prompt-cache
        prefix hash. (A volatile placeholder — one carrying a timestamp or a
        hit-counter — would silently break caching; the meta we embed is derived
        only from the content, never from mutable state.)

Placeholder format (the one contract every compressor shares)::

    [[BR:<12-hex-hash>|<type>; <source>; <size>]]

    e.g.  [[BR:9f3a2b1c4d5e|code; validation.py:check_array; 142L]]

The 12-hex hash is the retrieval key; everything after ``|`` is human/model-facing
metadata so the model can decide whether it even *needs* to expand (usually it
does not — that decision is where the savings live). Only the hash is parsed back.

Safety contract:
    * :meth:`stash` never raises — on any storage failure it returns ``None`` and
      the caller MUST keep the original content (stay lossless).
    * :meth:`retrieve` returns the exact original or ``None`` if unknown/evicted.
    * Eviction (:meth:`gc`) is LRU and **opt-in**. It is never called
      automatically mid-request, because evicting an original whose placeholder is
      still live in the context window would strand the model at a hole it cannot
      fill. Callers evict between sessions, not within one.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Optional

# --- Placeholder format: defined ONCE, here, and imported everywhere. ----------

_HASH_LEN = 12  # hex chars of the sha256 used as the short key (48 bits)

# Matches [[BR:<hash>|<meta>]] and [[BR:<hash>]]. Only the hash group is load-bearing.
PLACEHOLDER_RE = re.compile(r"\[\[BR:([0-9a-f]{6,64})(?:\|[^\]]*)?\]\]")


def make_placeholder(short_hash: str, ctype: str = "", source: str = "", size: str = "") -> str:
    """Build the canonical placeholder token. Meta is derived only from content."""
    meta_parts = [p for p in (ctype, source, size) if p]
    meta = "; ".join(meta_parts)
    return f"[[BR:{short_hash}|{meta}]]" if meta else f"[[BR:{short_hash}]]"


def parse_placeholders(text: str) -> list[str]:
    """Return every short hash referenced by a placeholder in ``text`` (in order)."""
    return PLACEHOLDER_RE.findall(text)


def _resolve_db_path() -> Path:
    """Locate the CCR sqlite file.

    Priority:
      1. ``BRAINSPACE_CCR`` env (absolute path) — used to point several host CLIs at
         ONE shared store for cross-agent dedup.
      2. repo-relative ``.token-master/ccr.sqlite``, searched from cwd upward (same
         resolution graphify_mcp.py uses for the graph), so one install serves
         every repo and the store sits beside the graph it complements.
    """
    env = os.environ.get("BRAINSPACE_CCR")
    if env:
        return Path(os.path.expandvars(os.path.expanduser(env))).resolve()
    rel = Path(".token-master") / "ccr.sqlite"
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        cand = d / rel
        if cand.is_file():
            return cand
    # Not found anywhere upward: default to creating under cwd/.token-master.
    return (here / rel).resolve()


class CCR:
    """A content-addressed reversible store backed by SQLite.

    Cheap to construct (no I/O until first use). Safe across processes: opened in
    WAL mode with a busy timeout so a Claude server and a Copilot server can share
    one store file without clobbering each other.
    """

    def __init__(self, db_path: Optional[os.PathLike | str] = None):
        self._db_path = Path(db_path).resolve() if db_path else _resolve_db_path()
        self._init_done = False

    # -- connection / schema -----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        if not self._init_done:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ccr (
                    hash         TEXT PRIMARY KEY,
                    blob         BLOB NOT NULL,
                    orig_bytes   INTEGER NOT NULL,
                    ctype        TEXT,
                    source       TEXT,
                    created      REAL NOT NULL,
                    last_access  REAL NOT NULL,
                    hits         INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.commit()
            self._init_done = True
        return conn

    # -- write -------------------------------------------------------------------

    def stash(
        self,
        content: str,
        *,
        ctype: str = "",
        source: str = "",
        summary: str = "",
    ) -> Optional[str]:
        """Store ``content`` verbatim and return its placeholder.

        Returns ``None`` on any failure — the caller must then keep the original
        content unchanged (the layer's invariant: never lose data, never raise).
        ``summary`` is accepted for caller convenience and folded into ``source``
        metadata; only content-derived fields shape the placeholder.
        """
        try:
            if not content:
                return None
            raw = content.encode("utf-8", errors="replace")
            full_hash = hashlib.sha256(raw).hexdigest()
            short = full_hash[:_HASH_LEN]
            now = time.time()
            blob = zlib.compress(raw, level=6)
            src = source or summary
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO ccr (hash, blob, orig_bytes, ctype, source, created, last_access, hits)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                       ON CONFLICT(hash) DO UPDATE SET last_access=excluded.last_access""",
                    (full_hash, blob, len(raw), ctype, src, now, now),
                )
                conn.commit()
            size = f"{content.count(chr(10)) + 1}L"
            return make_placeholder(short, ctype=ctype, source=src, size=size)
        except (sqlite3.Error, OSError, ValueError, zlib.error):
            return None

    # -- read --------------------------------------------------------------------

    def retrieve(self, ref: str) -> Optional[str]:
        """Return the original content for a placeholder or bare hash.

        Accepts a full ``[[BR:...]]`` placeholder, or just the hash. Bumps the
        access stats (for LRU + failure-mining). Returns ``None`` if not found.
        """
        try:
            hashes = parse_placeholders(ref)
            short = hashes[0] if hashes else ref.strip()
            short = re.sub(r"[^0-9a-f]", "", short.lower())[:64]
            if len(short) < 6:
                return None
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT hash, blob FROM ccr WHERE hash LIKE ? LIMIT 2",
                    (short + "%",),
                ).fetchall()
                if not row:
                    return None
                if len(row) > 1:
                    # Ambiguous short hash (astronomically unlikely at 12 hex, but
                    # be correct): refuse rather than return the wrong original.
                    return None
                full_hash, blob = row[0]
                conn.execute(
                    "UPDATE ccr SET hits = hits + 1, last_access = ? WHERE hash = ?",
                    (time.time(), full_hash),
                )
                conn.commit()
            return zlib.decompress(blob).decode("utf-8", errors="replace")
        except (sqlite3.Error, OSError, ValueError, zlib.error):
            return None

    # -- introspect / maintain ---------------------------------------------------

    def stats(self) -> dict:
        """Aggregate store stats (never raises; returns zeros if unreadable)."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT COUNT(*), COALESCE(SUM(orig_bytes), 0),
                              COALESCE(SUM(LENGTH(blob)), 0), COALESCE(SUM(hits), 0)
                       FROM ccr"""
                ).fetchone()
            entries, orig, stored, hits = row
            return {
                "entries": entries,
                "original_bytes": orig,
                "stored_bytes": stored,
                "compression_ratio": round(orig / stored, 2) if stored else None,
                "total_retrievals": hits,
                "db_path": str(self._db_path),
            }
        except (sqlite3.Error, OSError):
            return {"entries": 0, "db_path": str(self._db_path), "error": "unreadable"}

    def gc(self, max_bytes: int = 500 * 1024 * 1024) -> int:
        """Evict least-recently-accessed entries until stored size <= ``max_bytes``.

        Opt-in and cross-session only (see module docstring). Returns the number of
        entries evicted. Never raises.
        """
        try:
            with self._connect() as conn:
                total = conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(blob)), 0) FROM ccr"
                ).fetchone()[0]
                if total <= max_bytes:
                    return 0
                evicted = 0
                rows = conn.execute(
                    "SELECT hash, LENGTH(blob) FROM ccr ORDER BY last_access ASC"
                ).fetchall()
                for full_hash, blen in rows:
                    if total <= max_bytes:
                        break
                    conn.execute("DELETE FROM ccr WHERE hash = ?", (full_hash,))
                    total -= blen
                    evicted += 1
                conn.commit()
                return evicted
        except (sqlite3.Error, OSError):
            return 0
