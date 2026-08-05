"""SQLite persistence for the library: songs, presets and renders.

Stdlib ``sqlite3`` behind a thin wrapper rather than an ORM — the schema is
three flat tables and the project's style is plain dataclasses and light
dependencies, so SQLAlchemy would be more machinery than the problem needs.

Config is stored as a JSON blob rather than exploded into columns. ``MixConfig``
already round-trips through dicts, and a normalized schema would need migrating
every time a decay parameter is added.

Every public method holds ``self._lock`` for its whole body. FastAPI runs
``def`` (non-``async``) path operations in a threadpool, so two requests really
do reach this object from different threads — and ``commit()`` is
connection-wide, so one thread's commit would flush another's half-written
statement. The read-modify-write methods (``update_song``, ``update_render``)
would also lose updates without it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from ..paths import data_dir

_SONG_COLUMNS = {"path", "title", "duration_s", "sample_rate",
                 "separation_status", "separation_reason", "stems",
                 "last_preset_id"}
_RENDER_COLUMNS = {"song_id", "config", "path", "status", "duration_min"}

# The vocabulary for songs.separation_status. Written here rather than left
# implicit in a SQL DEFAULT and a couple of call sites, so a later plan
# populating this column reuses these spellings instead of inventing
# "error"/"complete"/"none" alongside them.
#   pending  - imported, separation not attempted yet (the SQL DEFAULT)
#   running  - separation in flight
#   done     - real per-stem separation succeeded
#   fallback - Demucs unavailable; the whole track is a single "mix" stem
#   failed   - separation was attempted and errored
SEPARATION_STATUSES = ("pending", "running", "done", "fallback", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    id                 TEXT PRIMARY KEY,
    path               TEXT NOT NULL,
    title              TEXT NOT NULL,
    duration_s         REAL NOT NULL,
    sample_rate        INTEGER NOT NULL,
    separation_status  TEXT NOT NULL DEFAULT 'pending',
    separation_reason  TEXT,
    stems              TEXT,
    last_preset_id     TEXT,
    added_at           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS presets (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    config     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS renders (
    id           TEXT PRIMARY KEY,
    song_id      TEXT NOT NULL,
    config       TEXT NOT NULL,
    path         TEXT NOT NULL,
    status       TEXT NOT NULL,
    duration_min REAL,
    created_at   TEXT NOT NULL
);

-- Collapse duplicate song rows left by versions predating the unique index,
-- keeping the oldest of each path and re-pointing its renders, so that adding
-- the index below cannot fail on an existing database. A no-op on a fresh one.
UPDATE renders SET song_id = (
    SELECT keep.id FROM songs keep
    WHERE keep.path = (SELECT dup.path FROM songs dup WHERE dup.id = renders.song_id)
    ORDER BY keep.rowid LIMIT 1
)
WHERE song_id IN (
    SELECT id FROM songs
    WHERE rowid NOT IN (SELECT MIN(rowid) FROM songs GROUP BY path)
);

DELETE FROM songs
WHERE rowid NOT IN (SELECT MIN(rowid) FROM songs GROUP BY path);

CREATE UNIQUE INDEX IF NOT EXISTS songs_path_unique ON songs (path);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class Store:
    """The library database. One instance per app; safe to open several."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or str(data_dir() / "library.db")
        # RLock, not Lock, and this matters: update_song and update_render both
        # call get_song/get_render while already holding the lock. A plain Lock
        # would deadlock the first time anything updated a row. Do not
        # "simplify" this to threading.Lock.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate_last_preset_id()
        self._conn.commit()

    def _migrate_last_preset_id(self) -> None:
        """Add ``songs.last_preset_id`` to a database that predates it.

        ``CREATE TABLE IF NOT EXISTS`` in ``_SCHEMA`` only shapes a table that
        does not exist yet — it will not add a column to the operator's real,
        already-existing library. ``PRAGMA table_info`` is how sqlite answers
        "does this column already exist" without an exception-driven check, so
        the ``ALTER TABLE`` only runs once, on the first startup after this
        column was introduced."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(songs)")}
        if "last_preset_id" not in cols:
            self._conn.execute("ALTER TABLE songs ADD COLUMN last_preset_id TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- songs ----------------------------------------------------------
    def add_song(self, path: str, title: str, duration_s: float,
                 sample_rate: int) -> dict:
        """Register a song, or return the existing row for the same path.

        Importing twice used to make two rows with separate ids and separate
        render histories, which reads as a duplicate in the library and splits
        a song's renders across two entries."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM songs WHERE path = ?", (path,)).fetchone()
            if row is not None:
                return _song_from_row(row)
            row_id = _new_id()
            self._conn.execute(
                "INSERT INTO songs (id, path, title, duration_s, sample_rate, added_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (row_id, path, title, float(duration_s), int(sample_rate), _now()))
            self._conn.commit()
            return self._get_song_locked(row_id)

    def get_song(self, song_id: str) -> dict | None:
        with self._lock:
            return self._get_song_locked(song_id)

    def _get_song_locked(self, song_id: str) -> dict | None:
        """``get_song``'s body, callable while ``self._lock`` is already held.

        ``add_song`` needs exactly this after an insert; calling the public
        ``get_song`` would work too (the lock is an ``RLock``) but this makes
        the re-entrance explicit rather than incidental."""
        row = self._conn.execute(
            "SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
        return _song_from_row(row)

    def list_songs(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM songs ORDER BY added_at DESC, rowid DESC").fetchall()
            return [_song_from_row(r) for r in rows]

    def update_song(self, song_id: str, **fields: Any) -> dict | None:
        with self._lock:
            unknown = set(fields) - _SONG_COLUMNS
            if unknown:
                raise ValueError(f"unknown song columns: {sorted(unknown)}")
            if self.get_song(song_id) is None:
                return None
            if fields:
                if "stems" in fields and not isinstance(fields["stems"], str):
                    fields["stems"] = json.dumps(fields["stems"])
                assignments = ", ".join(f"{k} = ?" for k in fields)
                self._conn.execute(
                    f"UPDATE songs SET {assignments} WHERE id = ?",
                    (*fields.values(), song_id))
                self._conn.commit()
            return self.get_song(song_id)

    def reconcile_orphaned_separations(self) -> int:
        """Reset songs stuck at 'running' to 'pending'. Returns how many.

        The job manager holds its jobs in memory, so a row still marked
        running when the process starts has no job behind it and never will —
        the server was killed or suspended mid-separation. Nothing else clears
        those rows, and a song claiming to separate forever cannot be retried
        from the interface."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE songs SET separation_status = 'pending', separation_reason = NULL"
                " WHERE separation_status = 'running'")
            self._conn.commit()
            return cursor.rowcount

    # -- presets --------------------------------------------------------
    def add_preset(self, name: str, config: dict) -> dict:
        with self._lock:
            row_id = _new_id()
            try:
                self._conn.execute(
                    "INSERT INTO presets (id, name, config, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (row_id, name, json.dumps(config), _now()))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"a preset named {name!r} already exists") from exc
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM presets WHERE id = ?", (row_id,)).fetchone()
            return _preset_from_row(row)

    def list_presets(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM presets ORDER BY name").fetchall()
            return [_preset_from_row(r) for r in rows]

    def get_preset(self, preset_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
            return _preset_from_row(row) if row is not None else None

    def delete_preset(self, preset_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def update_preset(self, preset_id: str, name: str, config: dict) -> dict | None:
        """Rename a preset, replace its config, or both.

        The unique index cannot tell "this name is taken by someone else" from
        "this name is taken by the row I am updating", and the second is the
        common case — saving over a preset without renaming it. So the
        collision is checked explicitly rather than caught, and the two are
        distinguishable to the caller."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id FROM presets WHERE id = ?", (preset_id,)).fetchone()
            if row is None:
                return None
            clash = self._conn.execute(
                "SELECT id FROM presets WHERE name = ? AND id != ?",
                (name, preset_id)).fetchone()
            if clash is not None:
                raise ValueError(f"a preset named {name!r} already exists")
            self._conn.execute(
                "UPDATE presets SET name = ?, config = ? WHERE id = ?",
                (name, json.dumps(config), preset_id))
            updated = self._conn.execute(
                "SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
            return _preset_from_row(updated)

    # -- renders --------------------------------------------------------
    def add_render(self, song_id: str, config: dict, path: str, status: str) -> dict:
        with self._lock:
            row_id = _new_id()
            self._conn.execute(
                "INSERT INTO renders (id, song_id, config, path, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (row_id, song_id, json.dumps(config), path, status, _now()))
            self._conn.commit()
            return self.get_render(row_id)

    def get_render(self, render_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM renders WHERE id = ?", (render_id,)).fetchone()
            return _render_from_row(row)

    def list_renders(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM renders ORDER BY created_at DESC, rowid DESC").fetchall()
            return [_render_from_row(r) for r in rows]

    def delete_render(self, render_id: str) -> bool:
        """True if there was a row to delete. The file is the caller's problem;
        this object owns the database and nothing else."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM renders WHERE id = ?", (render_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def update_render(self, render_id: str, **fields: Any) -> dict | None:
        with self._lock:
            unknown = set(fields) - _RENDER_COLUMNS
            if unknown:
                raise ValueError(f"unknown render columns: {sorted(unknown)}")
            if self.get_render(render_id) is None:
                return None
            if fields:
                if "config" in fields and not isinstance(fields["config"], str):
                    fields["config"] = json.dumps(fields["config"])
                assignments = ", ".join(f"{k} = ?" for k in fields)
                self._conn.execute(
                    f"UPDATE renders SET {assignments} WHERE id = ?",
                    (*fields.values(), render_id))
                self._conn.commit()
            return self.get_render(render_id)


# -- row adapters -------------------------------------------------------
def _song_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["stems"] = json.loads(d["stems"]) if d["stems"] else None
    return d


def _preset_from_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["config"] = json.loads(d["config"])
    return d


def _render_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["config"] = json.loads(d["config"])
    return d
