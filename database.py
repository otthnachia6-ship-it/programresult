"""
Database layer for Kisauni Result System (SQLite).
"""
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

from config import (
    Config, CLASS_NAMES, LOWER_CLASS_SUBJECTS, UPPER_CLASS_SUBJECTS,
    LOWER_CLASSES, EXAM_TYPES, ROLE_HEADMASTER, ROLE_CLASS_TEACHER,
    DEFAULT_SCHOOL_NAME, DEFAULT_ACADEMIC_YEAR,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('headmaster','class_teacher')),
    class_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(class_id) REFERENCES classes(id)
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    teacher_id INTEGER,
    FOREIGN KEY(teacher_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS class_subjects (
    class_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    PRIMARY KEY (class_id, subject_id),
    FOREIGN KEY(class_id) REFERENCES classes(id),
    FOREIGN KEY(subject_id) REFERENCES subjects(id)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reg_no TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    gender TEXT NOT NULL DEFAULT 'Unknown',
    gender_confirmed INTEGER NOT NULL DEFAULT 0,
    class_id INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(class_id) REFERENCES classes(id)
);

CREATE TABLE IF NOT EXISTS examinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_type TEXT NOT NULL,
    academic_year TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(exam_type, academic_year)
);

CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    exam_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    score REAL,
    entered_by INTEGER,
    updated_at TEXT,
    UNIQUE(student_id, exam_id, subject_id),
    FOREIGN KEY(student_id) REFERENCES students(id),
    FOREIGN KEY(exam_id) REFERENCES examinations(id),
    FOREIGN KEY(subject_id) REFERENCES subjects(id)
);

-- Tracks the workflow status of a (class, exam) combination
CREATE TABLE IF NOT EXISTS exam_class_status (
    exam_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft','submitted','under_review','returned','approved')),
    remarks TEXT,
    submitted_by INTEGER,
    submitted_at TEXT,
    approved_by INTEGER,
    approved_at TEXT,
    PRIMARY KEY (exam_id, class_id),
    FOREIGN KEY(exam_id) REFERENCES examinations(id),
    FOREIGN KEY(class_id) REFERENCES classes(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);
"""


def get_db():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log_action(conn, user, action, details=""):
    conn.execute(
        "INSERT INTO audit_log (user_id, username, action, details, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            user["id"] if user else None,
            user["username"] if user else "system",
            action,
            details,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()

    # --- lightweight migration for DBs created before must_change_password ---
    try:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists

    # --- normalise the SUMI subject name (older DBs may have the long form) ---
    conn.execute("UPDATE subjects SET name='SUMI' WHERE name LIKE 'SUMI (%'")
    conn.commit()

    # --- seed classes -----------------------------------------------------
    cur = conn.execute("SELECT COUNT(*) c FROM classes")
    if cur.fetchone()["c"] == 0:
        for i, name in enumerate(CLASS_NAMES, start=1):
            conn.execute(
                "INSERT INTO classes (name, sort_order) VALUES (?, ?)", (name, i)
            )
        conn.commit()

    # --- seed subjects + class_subjects mapping ---------------------------
    cur = conn.execute("SELECT COUNT(*) c FROM subjects")
    if cur.fetchone()["c"] == 0:
        all_subject_names = list(dict.fromkeys(LOWER_CLASS_SUBJECTS + UPPER_CLASS_SUBJECTS))
        name_to_id = {}
        for sname in all_subject_names:
            cur2 = conn.execute("INSERT INTO subjects (name) VALUES (?)", (sname,))
            name_to_id[sname] = cur2.lastrowid
        conn.commit()

        classes = conn.execute("SELECT id, name FROM classes").fetchall()
        for cls in classes:
            subj_list = LOWER_CLASS_SUBJECTS if cls["name"] in LOWER_CLASSES else UPPER_CLASS_SUBJECTS
            for sname in subj_list:
                conn.execute(
                    "INSERT OR IGNORE INTO class_subjects (class_id, subject_id) VALUES (?, ?)",
                    (cls["id"], name_to_id[sname]),
                )
        conn.commit()

    # --- seed examination types (current academic year) -------------------
    cur = conn.execute("SELECT COUNT(*) c FROM examinations")
    if cur.fetchone()["c"] == 0:
        for etype in EXAM_TYPES:
            conn.execute(
                "INSERT OR IGNORE INTO examinations (exam_type, academic_year, created_at) "
                "VALUES (?, ?, ?)",
                (etype, DEFAULT_ACADEMIC_YEAR, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
        conn.commit()

    # --- seed default headmaster account -----------------------------------
    cur = conn.execute("SELECT COUNT(*) c FROM users WHERE role='headmaster'")
    if cur.fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (
                "headmaster",
                generate_password_hash("admin123"),
                "Head Master",
                ROLE_HEADMASTER,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()

    # --- seed default settings ---------------------------------------------
    defaults = {
        "school_name": DEFAULT_SCHOOL_NAME,
        "academic_year": DEFAULT_ACADEMIC_YEAR,
        "logo_path": "images/logo.png",
    }
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


if __name__ == "__main__":
    init_db()
    print("Database initialised ->", Config.DATABASE)
