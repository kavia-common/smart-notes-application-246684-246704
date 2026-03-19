#!/usr/bin/env python3
"""Initialize SQLite database schema for the notes application."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Dict

DEFAULT_DB_NAME = "myapp.db"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (note_id, tag_id),
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

/* Indexes for list/filter/sort and join performance */
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_updated_at ON notes(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_archived_updated ON notes(is_archived, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_note_tags_tag_id_note_id ON note_tags(tag_id, note_id);

/* Keep updated_at current on updates */
CREATE TRIGGER IF NOT EXISTS trg_notes_set_updated_at
AFTER UPDATE ON notes
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE notes
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;

/* FTS index for efficient note title/content search */
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
USING fts5(
    title,
    content,
    content='notes',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS trg_notes_ai
AFTER INSERT ON notes
BEGIN
    INSERT INTO notes_fts(rowid, title, content)
    VALUES (NEW.id, NEW.title, NEW.content);
END;

CREATE TRIGGER IF NOT EXISTS trg_notes_ad
AFTER DELETE ON notes
BEGIN
    DELETE FROM notes_fts
    WHERE rowid = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_notes_au
AFTER UPDATE OF title, content ON notes
BEGIN
    DELETE FROM notes_fts
    WHERE rowid = OLD.id;
    INSERT INTO notes_fts(rowid, title, content)
    VALUES (NEW.id, NEW.title, NEW.content);
END;
"""


# PUBLIC_INTERFACE
def initialize_database(db_path: Path) -> Dict[str, int]:
    """Initialize the notes database schema in a reproducible, idempotent way.

    Args:
        db_path: Absolute or relative path to the SQLite database file.

    Returns:
        A dictionary with basic database statistics after initialization.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_SQL)

        # Ensure deterministic app metadata for downstream services.
        conn.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            ("project_name", "notes_app_database"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            ("schema_version", "1.0.0"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            ("description", "SQLite schema for notes CRUD, listing, search, and optional tags"),
        )

        # Rebuild FTS index from canonical notes content to keep state reproducible.
        conn.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")

        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        index_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        trigger_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
        ).fetchone()[0]

    return {
        "tables": int(table_count),
        "indexes": int(index_count),
        "triggers": int(trigger_count),
    }


# PUBLIC_INTERFACE
def write_connection_files(db_path: Path) -> None:
    """Write local connection helper files used by backend tooling and DB visualizer.

    Args:
        db_path: Absolute path to the SQLite database file.
    """
    db_dir = db_path.parent
    connection_file = db_dir / "db_connection.txt"
    visualizer_dir = db_dir / "db_visualizer"
    visualizer_env_file = visualizer_dir / "sqlite.env"

    connection_string = f"sqlite:///{db_path}"

    connection_file.write_text(
        "# SQLite connection methods:\n"
        f"# Python: sqlite3.connect('{db_path}')\n"
        f"# Connection string: {connection_string}\n"
        f"# File path: {db_path}\n",
        encoding="utf-8",
    )

    visualizer_dir.mkdir(parents=True, exist_ok=True)
    visualizer_env_file.write_text(
        f'export SQLITE_DB="{db_path}"\n',
        encoding="utf-8",
    )


# PUBLIC_INTERFACE
def main() -> None:
    """Entrypoint for initializing SQLite schema and helper connection metadata."""
    configured_db_path = os.getenv("SQLITE_DB", DEFAULT_DB_NAME)
    db_path = Path(configured_db_path).expanduser().resolve()

    print("Starting SQLite schema initialization...")
    print(f"Target database: {db_path}")

    stats = initialize_database(db_path)
    write_connection_files(db_path)

    print("SQLite initialization complete.")
    print(f"Tables: {stats['tables']}")
    print(f"Indexes: {stats['indexes']}")
    print(f"Triggers: {stats['triggers']}")
    print("Connection metadata updated: db_connection.txt and db_visualizer/sqlite.env")


if __name__ == "__main__":
    main()
