"""The SQLite file: how to open it, how it grew, and the entries in it."""

import sqlite3
import time
import config


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL so the sweep thread and request threads do not block each other.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Append only. A version number is a position in this list, so inserting one in
# the middle rewrites the past of every database already migrated: it replays a
# different script under a number they have already recorded. Adding settings
# above subscriptions did exactly that and crashed the container on import.
MIGRATIONS = [
    """
    CREATE TABLE entries (
        job_id     TEXT PRIMARY KEY,
        owner      TEXT NOT NULL,
        url        TEXT NOT NULL,
        title      TEXT,
        thumbnail  TEXT,
        format     TEXT,
        format_id  TEXT,
        filename   TEXT,
        path       TEXT,
        status     TEXT NOT NULL,
        error      TEXT,
        created_at REAL NOT NULL
    );
    CREATE INDEX entries_owner ON entries (owner, created_at DESC);
    """,
    """
    ALTER TABLE entries ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE entries ADD COLUMN formats TEXT;
    """,
    """
    ALTER TABLE entries ADD COLUMN uploader TEXT;
    ALTER TABLE entries ADD COLUMN duration REAL;
    """,
    """
    ALTER TABLE entries ADD COLUMN description TEXT;
    ALTER TABLE entries ADD COLUMN upload_date TEXT;
    """,
    """
    CREATE TABLE subscriptions (
        owner        TEXT NOT NULL,
        channel_id   TEXT NOT NULL,
        channel_url  TEXT NOT NULL,
        title        TEXT,
        thumbnail    TEXT,
        videos       TEXT NOT NULL DEFAULT '[]',
        refreshed_at REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (owner, channel_id)
    );
    """,
    """
    CREATE TABLE settings (
        owner        TEXT PRIMARY KEY,
        feed_videos  INTEGER NOT NULL,
        feed_quality INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE channels (
        channel_id   TEXT PRIMARY KEY,
        channel_url  TEXT NOT NULL,
        title        TEXT,
        thumbnail    TEXT,
        videos       TEXT NOT NULL DEFAULT '[]',
        refreshed_at REAL NOT NULL DEFAULT 0
    );
    INSERT OR IGNORE INTO channels
        (channel_id, channel_url, title, thumbnail, videos, refreshed_at)
        SELECT channel_id, channel_url, title, thumbnail, videos, refreshed_at
        FROM subscriptions;
    CREATE TABLE follows (
        owner      TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        PRIMARY KEY (owner, channel_id)
    );
    INSERT OR IGNORE INTO follows (owner, channel_id)
        SELECT owner, channel_id FROM subscriptions;
    DROP TABLE subscriptions;
    """,
    """
    ALTER TABLE entries ADD COLUMN variant TEXT;
    """,
    """
    ALTER TABLE channels ADD COLUMN shorts TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE channels ADD COLUMN shorts_refreshed_at REAL NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE entries ADD COLUMN kind TEXT NOT NULL DEFAULT 'video';
    """,
    """
    ALTER TABLE channels ADD COLUMN platform TEXT NOT NULL DEFAULT 'youtube';
    """,
    """
    CREATE TABLE shares (
        token      TEXT PRIMARY KEY,
        job_id     TEXT NOT NULL,
        owner      TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL
    );
    CREATE INDEX shares_job ON shares (job_id);
    """,
    """
    ALTER TABLE channels ADD COLUMN has_videos INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE channels ADD COLUMN has_shorts INTEGER NOT NULL DEFAULT 1;
    """,
    """
    CREATE TABLE seen (
        owner TEXT NOT NULL,
        url   TEXT NOT NULL,
        at    REAL NOT NULL,
        PRIMARY KEY (owner, url)
    );
    """,
]


def migrate():
    with connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version):
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {i + 1}")


def recover_interrupted():
    with connect() as conn:
        conn.execute("UPDATE entries SET status = 'error', error = ? "
                     "WHERE status = 'downloading'",
                     ("Interrupted by a server restart",))


def get_entry(job_id, owner=None):
    with connect() as conn:
        row = conn.execute("SELECT * FROM entries WHERE job_id = ?", (job_id,)).fetchone()
    if row is None or (owner is not None and row["owner"] != owner):
        return None
    return row


def update_entry(job_id, **fields):
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE entries SET {assignments} WHERE job_id = ?",
                     (*fields.values(), job_id))


def live_shares():
    """job_id -> the last moment a link to it is still meant to work."""
    if not config.SHARE_ENABLED:
        return {}
    with connect() as conn:
        return {r["job_id"]: r["until"] for r in conn.execute(
            "SELECT job_id, max(expires_at) AS until FROM shares "
            "WHERE expires_at > ? GROUP BY job_id", (time.time(),))}


# The file is opened by importing this module, so it is migrated and cleaned
# before anything else can read it.
migrate()
recover_interrupted()
