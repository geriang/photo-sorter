import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    sha256        TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    size          INTEGER,
    format        TEXT,
    exif_date     TEXT,
    mtime         TEXT,
    has_people    INTEGER,
    group_size    INTEGER,
    type          TEXT,
    value         TEXT,
    score         REAL,
    reason        TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    target     TEXT NOT NULL,
    dry_run    INTEGER NOT NULL,
    undone     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS manifest (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(run_id),
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    sidecar     TEXT,
    date_source TEXT NOT NULL,
    resolved    TEXT,
    reason      TEXT
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
