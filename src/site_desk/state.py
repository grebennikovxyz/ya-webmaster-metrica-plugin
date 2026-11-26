import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def state_dir():
    root = Path(os.environ.get("SITE_DESK_STATE_DIR") or Path.home() / ".site-desk")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


@contextmanager
def transaction():
    db = sqlite3.connect(state_dir() / "state.sqlite3", timeout=60)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS watches (target TEXT PRIMARY KEY, snapshot TEXT NOT NULL)"
        )
        yield db
        db.commit()
    finally:
        db.close()
