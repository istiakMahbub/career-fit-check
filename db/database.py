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
    print(f"Database initialized at {DB_PATH}")


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
