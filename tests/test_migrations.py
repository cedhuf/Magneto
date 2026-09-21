"""The schema, and the only upgrade path left.

The fifteen migrations that grew it were squashed while the project was shared
with nobody. What must hold from now on: a fresh database reaches the right
schema, and a database left at the end of the old chain is stamped instead of
replayed.
"""
import hashlib
import os
import sqlite3
import sys
import tempfile

SCHEMA_DIR = tempfile.mkdtemp()
os.environ["MAGNETO_DB"] = os.path.join(SCHEMA_DIR, "fresh.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import db  # noqa: E402

fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


def shape(path):
    conn = sqlite3.connect(path)
    tables = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        tables[name] = {(r[1], r[2].upper(), r[3], str(r[4]), r[5])
                        for r in conn.execute(f"PRAGMA table_info({name})")}
    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    return tables, indexes, version


tables, indexes, version = shape(os.environ["MAGNETO_DB"])
check("a fresh database reaches the end of the list", version == len(db.MIGRATIONS))
check("the six tables are there",
      set(tables) == {"entries", "channels", "follows", "settings", "seen", "shares"})
check("and the two indexes", indexes == {"entries_owner", "shares_job"})

# A database left at the end of the old chain: same schema, version 15.
old = os.path.join(SCHEMA_DIR, "v15.db")
conn = sqlite3.connect(old)
conn.executescript(db.MIGRATIONS[0])
conn.execute(f"PRAGMA user_version = {db.SQUASHED_AT}")
conn.execute("INSERT INTO entries (job_id, owner, url, status, created_at) "
             "VALUES ('keepme0001', 'cedric', 'https://e.com/a', 'done', 1)")
conn.commit()
conn.close()

os.environ["MAGNETO_DB"] = old
import config  # noqa: E402
config.DB_PATH = old
db.migrate()
after, after_index, after_version = shape(old)
check("it is stamped, not replayed", after_version == len(db.MIGRATIONS))
check("its schema did not move", (after, after_index) == (tables, indexes))
with sqlite3.connect(old) as conn:
    kept = conn.execute("SELECT count(*) FROM entries").fetchone()[0]
check("and nothing was lost", kept == 1)

# Guard rail: append only, and the first one never moves.
PUBLISHED = ["e4a32e099ab1b55b"]
digests = [hashlib.sha256(" ".join(m.split()).encode()).hexdigest()[:16]
           for m in db.MIGRATIONS]
check("the published schema changed neither content nor place",
      digests[:len(PUBLISHED)] == PUBLISHED)
check("the list only grows", len(digests) >= len(PUBLISHED))

# And every possible version must still upgrade to the end.
for start in range(len(db.MIGRATIONS) + 1):
    path = os.path.join(SCHEMA_DIR, f"v{start}.db")
    conn = sqlite3.connect(path)
    for i, script in enumerate(db.MIGRATIONS[:start]):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {i + 1}")
    conn.commit()
    try:
        for i, script in enumerate(db.MIGRATIONS[start:], start=start):
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {i + 1}")
    except sqlite3.OperationalError as e:
        check(f"a database at version {start} can no longer upgrade: {e}", False)
    conn.close()
check(f"all {len(db.MIGRATIONS) + 1} possible versions upgrade", True)

if fails:
    sys.exit(1)
print(f"ok: one schema, v{len(db.MIGRATIONS)}, and the old chain stamped")
