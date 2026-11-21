"""PS02 tables. Appended to db.SCHEMA so they are created (SQLite or Postgres) with everything else."""
PS02_SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, class_section TEXT, is_demo INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mastery (
    student_id INTEGER, concept_id TEXT, p_known REAL, attempts INTEGER DEFAULT 0, correct INTEGER DEFAULT 0,
    last_seen TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (student_id, concept_id)
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, question_json TEXT, concept_id TEXT, difficulty INTEGER,
    chosen_index INTEGER, correct INTEGER, reasoning_text TEXT, reasoning_mode TEXT, misconception_id TEXT,
    misconception_confidence REAL, is_careless INTEGER DEFAULT 0, phase TEXT DEFAULT 'practice', delta_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reviews (
    student_id INTEGER, concept_id TEXT, easiness REAL DEFAULT 2.5, interval_days REAL DEFAULT 0, repetitions INTEGER DEFAULT 0,
    due_at TEXT, PRIMARY KEY (student_id, concept_id)
);
CREATE TABLE IF NOT EXISTS student_misconceptions (
    student_id INTEGER, misconception_id TEXT, count INTEGER DEFAULT 0, last_seen TEXT, resolved INTEGER DEFAULT 0,
    last_quote TEXT, PRIMARY KEY (student_id, misconception_id)
);
CREATE TABLE IF NOT EXISTS dialogues (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, attempt_id INTEGER, concept_id TEXT, misconception_id TEXT, language TEXT,
    status TEXT DEFAULT 'open', student_turns INTEGER DEFAULT 0, transcript TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ps02_cache (
    cache_key TEXT PRIMARY KEY, payload TEXT, created_at REAL
);
"""
