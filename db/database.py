import sqlite3
import os
import json
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "./career_fit.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """Context manager that yields a connection and closes it on exit."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    schema = SCHEMA_PATH.read_text()
    with get_connection() as conn:
        conn.executescript(schema)
        _seed_user_profile(conn)
        _run_migrations(conn)
    print(f"Database initialized at {DB_PATH}")


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply additive schema migrations that are safe to run repeatedly."""
    migrations = [
        "ALTER TABLE jobs ADD COLUMN job_category TEXT DEFAULT NULL",
        "ALTER TABLE user_profile ADD COLUMN target_role TEXT DEFAULT NULL",
        """CREATE TABLE IF NOT EXISTS skill_learning_tips (
            company_id INTEGER NOT NULL DEFAULT -1,
            category TEXT NOT NULL DEFAULT '',
            skill TEXT NOT NULL,
            tip TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (company_id, category, skill)
        )""",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists


def _seed_user_profile(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id FROM user_profile WHERE id = 1").fetchone()
    if existing:
        return

    default_skills = json.dumps([
        {"name": "Python", "level": 85},
        {"name": "SQL", "level": 75},
        {"name": "Machine Learning", "level": 70},
        {"name": "Data Analysis", "level": 80},
        {"name": "Pandas", "level": 80},
        {"name": "Scikit-learn", "level": 65},
    ])

    conn.execute(
        "INSERT INTO user_profile (id, name, role, skills) VALUES (1, 'Istiak', 'Data Science Candidate', ?)",
        (default_skills,),
    )
