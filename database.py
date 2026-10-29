"""
Database and Authentication Service for Collaborative Coding Platform.
Provides SQLite persistence, PBKDF2 password hashing, session management,
email verification, and password reset handling.
"""

import sqlite3
import os
import hashlib
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collab_platform.db")


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database tables."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            is_verified INTEGER DEFAULT 0,
            bio TEXT DEFAULT '',
            avatar_url TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            room_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT NOT NULL,
            files_json TEXT NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS dev_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            content TEXT NOT NULL,
            action_url TEXT NOT NULL,
            action_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_by TEXT NOT NULL,
            avatar_color TEXT DEFAULT '#3B82F6',
            invite_code TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            joined_at TEXT NOT NULL,
            UNIQUE(team_id, user_id),
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            room_id TEXT NOT NULL,
            language TEXT DEFAULT 'python',
            status TEXT DEFAULT 'in_progress',
            created_at TEXT NOT NULL,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            assigned_to TEXT DEFAULT '',
            status TEXT DEFAULT 'todo',
            priority TEXT DEFAULT 'medium',
            due_date TEXT DEFAULT '',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            submitted_by TEXT NOT NULL,
            submission_title TEXT NOT NULL,
            repository_notes TEXT DEFAULT '',
            files_snapshot_json TEXT DEFAULT '{}',
            grade_score INTEGER DEFAULT NULL,
            feedback TEXT DEFAULT '',
            graded_by TEXT DEFAULT '',
            submitted_at TEXT NOT NULL,
            graded_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            team_id TEXT,
            current_streak INTEGER DEFAULT 1,
            longest_streak INTEGER DEFAULT 1,
            last_activity_date TEXT NOT NULL,
            total_sprints INTEGER DEFAULT 1,
            trees_count INTEGER DEFAULT 1,
            UNIQUE(user_id, team_id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_metadata (
            room_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            language TEXT DEFAULT 'python',
            owner_id TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
            is_private INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mentor_annotations (
            id TEXT PRIMARY KEY,
            room_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            comment TEXT NOT NULL,
            problematic_level TEXT DEFAULT 'warning',
            author_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            link TEXT DEFAULT '',
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """)
        
        conn.commit()


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000
    ).hex()
    return hashed, salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    hashed, _ = hash_password(password, salt)
    return secrets.compare_digest(hashed, password_hash)


def create_user(username: str, email: str, password: str) -> Dict[str, Any]:
    username = username.strip()
    email = email.strip().lower()
    
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters long.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    if "@" not in email or "." not in email:
        raise ValueError("Invalid email format.")

    user_id = f"usr_{secrets.token_hex(6)}"
    hashed, salt = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()
    
    # Generate default avatar based on username
    avatar_url = f"https://api.dicebear.com/7.x/bottts/svg?seed={username}"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO users (id, username, email, password_hash, salt, is_verified, bio, avatar_url, created_at)
                VALUES (?, ?, ?, ?, ?, 0, '', ?, ?)
                """,
                (user_id, username, email, hashed, salt, avatar_url, now)
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if "username" in msg:
                raise ValueError("Username is already taken.")
            elif "email" in msg:
                raise ValueError("Email is already registered.")
            else:
                raise ValueError("User with this username or email already exists.")

    # Generate email verification token
    verification_token = create_verification_token(user_id, email)
    return {
        "id": user_id,
        "username": username,
        "email": email,
        "is_verified": False,
        "avatar_url": avatar_url,
        "verification_token": verification_token
    }


def authenticate_user(identifier: str, password: str) -> Optional[Dict[str, Any]]:
    identifier = identifier.strip().lower()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, email, password_hash, salt, is_verified, bio, avatar_url, created_at
            FROM users
            WHERE lower(username) = ? OR lower(email) = ?
            """,
            (identifier, identifier)
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        if verify_password(password, row["password_hash"], row["salt"]):
            return {
                "id": row["id"],
                "username": row["username"],
                "email": row["email"],
                "is_verified": bool(row["is_verified"]),
                "bio": row["bio"],
                "avatar_url": row["avatar_url"],
                "created_at": row["created_at"]
            }
        return None


def create_session(user_id: str, days: int = 7) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=days)).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires_at)
        )
        conn.commit()
    return token


def get_user_by_session(token: str) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.id, u.username, u.email, u.is_verified, u.bio, u.avatar_url, u.created_at
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "is_verified": bool(row["is_verified"]),
            "bio": row["bio"],
            "avatar_url": row["avatar_url"],
            "created_at": row["created_at"]
        }


def delete_session(token: str) -> None:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email, is_verified, bio, avatar_url, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "is_verified": bool(row["is_verified"]),
            "bio": row["bio"],
            "avatar_url": row["avatar_url"],
            "created_at": row["created_at"]
        }


def update_user_profile(user_id: str, bio: Optional[str] = None, avatar_url: Optional[str] = None, username: Optional[str] = None) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if bio is not None:
            updates.append("bio = ?")
            params.append(bio.strip())
        if avatar_url is not None:
            updates.append("avatar_url = ?")
            params.append(avatar_url.strip())
        if username is not None:
            new_u = username.strip()
            if len(new_u) < 3:
                raise ValueError("Username must be at least 3 characters.")
            updates.append("username = ?")
            params.append(new_u)
            
        if not updates:
            u = get_user_by_id(user_id)
            if not u:
                raise ValueError("User not found.")
            return u
        
        params.append(user_id)
        try:
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("Username is already taken.")
            
    u = get_user_by_id(user_id)
    if not u:
        raise ValueError("User not found.")
    return u


def create_verification_token(user_id: str, email: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=24)).isoformat()
    action_url = f"/verify-email?token={token}"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO email_verification_tokens (token, user_id, email, created_at, expires_at, used)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (token, user_id, email, now.isoformat(), expires_at)
        )
        cursor.execute(
            """
            INSERT INTO dev_outbox (recipient_email, subject, content, action_url, action_type, created_at)
            VALUES (?, ?, ?, ?, 'email_verification', ?)
            """,
            (email, "Verify Your Email - CollabCode Platform", "Please verify your email address to complete your registration.", action_url, now.isoformat())
        )
        conn.commit()
    return token


def verify_email_with_token(token: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_id FROM email_verification_tokens
            WHERE token = ? AND expires_at > ? AND used = 0
            """,
            (token, now)
        )
        row = cursor.fetchone()
        if not row:
            return False
        
        user_id = row["user_id"]
        cursor.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        cursor.execute("UPDATE email_verification_tokens SET used = 1 WHERE token = ?", (token,))
        conn.commit()
        return True


def request_password_reset(email: str) -> Optional[str]:
    email = email.strip().lower()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE lower(email) = ?", (email,))
        row = cursor.fetchone()
        if not row:
            return None
        
        user_id = row["id"]
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=2)).isoformat()
        action_url = f"/reset-password?token={token}"
        
        cursor.execute(
            """
            INSERT INTO password_reset_tokens (token, user_id, created_at, expires_at, used)
            VALUES (?, ?, ?, ?, 0)
            """,
            (token, user_id, now.isoformat(), expires_at)
        )
        cursor.execute(
            """
            INSERT INTO dev_outbox (recipient_email, subject, content, action_url, action_type, created_at)
            VALUES (?, ?, ?, ?, 'password_reset', ?)
            """,
            (email, "Reset Your Password - CollabCode Platform", "Click the link to reset your account password.", action_url, now.isoformat())
        )
        conn.commit()
        return token


def reset_password_with_token(token: str, new_password: str) -> bool:
    if len(new_password) < 6:
        raise ValueError("New password must be at least 6 characters.")
        
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_id FROM password_reset_tokens
            WHERE token = ? AND expires_at > ? AND used = 0
            """,
            (token, now)
        )
        row = cursor.fetchone()
        if not row:
            return False
        
        user_id = row["user_id"]
        hashed, salt = hash_password(new_password)
        cursor.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (hashed, salt, user_id)
        )
        cursor.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,))
        # Invalidate existing sessions for security
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return True


def get_latest_dev_outbox(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve simulated outgoing emails for easy local testing."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, recipient_email, subject, content, action_url, action_type, created_at
            FROM dev_outbox ORDER BY id DESC LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


# =========================================================================
# Teams & Project Collaboration System
# =========================================================================

TEAM_COLORS = ["#3B82F6", "#10B981", "#8B5CF6", "#F59E0B", "#EC4899", "#06B6D4"]

def create_team(name: str, description: str, creator_id: str, avatar_color: Optional[str] = None) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Team name is required.")
    
    team_id = f"team_{secrets.token_hex(5)}"
    invite_code = secrets.token_hex(4).upper()
    now = datetime.now(timezone.utc).isoformat()
    color = avatar_color or secrets.choice(TEAM_COLORS)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO teams (id, name, description, created_by, avatar_color, invite_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (team_id, name, description, creator_id, color, invite_code, now)
        )
        # Add creator as 'leader'
        cursor.execute(
            """
            INSERT INTO team_members (team_id, user_id, role, joined_at)
            VALUES (?, ?, 'leader', ?)
            """,
            (team_id, creator_id, now)
        )
        conn.commit()

    return {
        "id": team_id,
        "name": name,
        "description": description,
        "created_by": creator_id,
        "avatar_color": color,
        "invite_code": invite_code,
        "created_at": now
    }


def get_user_teams(user_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.id, t.name, t.description, t.created_by, t.avatar_color, t.invite_code, t.created_at,
                   tm.role as my_role,
                   (SELECT COUNT(*) FROM team_members WHERE team_id = t.id) as member_count,
                   (SELECT COUNT(*) FROM projects WHERE team_id = t.id) as project_count
            FROM teams t
            JOIN team_members tm ON t.id = tm.team_id
            WHERE tm.user_id = ?
            ORDER BY t.created_at DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_team_details(team_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        team_row = cursor.fetchone()
        if not team_row:
            return None
        team = dict(team_row)

        cursor.execute(
            """
            SELECT tm.role, tm.joined_at, u.id as user_id, u.username, u.email, u.avatar_url
            FROM team_members tm
            JOIN users u ON tm.user_id = u.id
            WHERE tm.team_id = ?
            ORDER BY tm.role DESC, tm.joined_at ASC
            """,
            (team_id,)
        )
        team["members"] = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT * FROM projects WHERE team_id = ? ORDER BY created_at DESC
            """,
            (team_id,)
        )
        team["projects"] = [dict(row) for row in cursor.fetchall()]
        return team


def add_team_member(team_id: str, user_id: str, role: str = "member") -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO team_members (team_id, user_id, role, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (team_id, user_id, role, now)
            )
            conn.commit()
            return True
        except Exception:
            return False


def join_team_by_code(invite_code: str, user_id: str) -> Optional[Dict[str, Any]]:
    invite_code = invite_code.strip().upper()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teams WHERE invite_code = ?", (invite_code,))
        team = cursor.fetchone()
        if not team:
            return None
        team_id = team["id"]
        add_team_member(team_id, user_id, "member")
        return dict(team)


def create_project(team_id: str, name: str, description: str, room_id: Optional[str] = None, language: str = "python") -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Project name is required.")
    project_id = f"proj_{secrets.token_hex(5)}"
    assigned_room = room_id or f"room_{secrets.token_hex(4)}"
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO projects (id, team_id, name, description, room_id, language, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?)
            """,
            (project_id, team_id, name, description, assigned_room, language, now)
        )
        # Create initial default task
        task_id = f"task_{secrets.token_hex(5)}"
        cursor.execute(
            """
            INSERT INTO tasks (id, project_id, title, description, assigned_to, status, priority, due_date, created_by, created_at)
            VALUES (?, ?, 'Setup project architecture and initial files', 'Initialize collaborative repository and setup main files.', '', 'todo', 'high', '', 'system', ?)
            """,
            (task_id, project_id, now)
        )
        conn.commit()

    return {
        "id": project_id,
        "team_id": team_id,
        "name": name,
        "description": description,
        "room_id": assigned_room,
        "language": language,
        "status": "in_progress",
        "created_at": now
    }


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.*, t.name as team_name, t.created_by as team_owner
            FROM projects p
            JOIN teams t ON p.team_id = t.id
            WHERE p.id = ?
            """,
            (project_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        project = dict(row)
        project["tasks"] = get_project_tasks(project_id)
        project["submissions"] = get_project_submissions(project_id)
        return project


def get_team_projects(team_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE team_id = ? ORDER BY created_at DESC", (team_id,))
        return [dict(r) for r in cursor.fetchall()]


# =========================================================================
# Project Tasks (Kanban)
# =========================================================================

def create_task(project_id: str, title: str, description: str = "", assigned_to: str = "", priority: str = "medium", due_date: str = "", created_by: str = "") -> Dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("Task title is required.")
    task_id = f"task_{secrets.token_hex(5)}"
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tasks (id, project_id, title, description, assigned_to, status, priority, due_date, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, 'todo', ?, ?, ?, ?)
            """,
            (task_id, project_id, title, description, assigned_to, priority, due_date, created_by, now)
        )
        conn.commit()
    return {
        "id": task_id,
        "project_id": project_id,
        "title": title,
        "description": description,
        "assigned_to": assigned_to,
        "status": "todo",
        "priority": priority,
        "due_date": due_date,
        "created_by": created_by,
        "created_at": now
    }


def get_project_tasks(project_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at ASC", (project_id,))
        return [dict(r) for r in cursor.fetchall()]


def update_task(task_id: str, status: Optional[str] = None, assigned_to: Optional[str] = None, title: Optional[str] = None, priority: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        new_status = status if status is not None else row["status"]
        new_assigned = assigned_to if assigned_to is not None else row["assigned_to"]
        new_title = title if title is not None else row["title"]
        new_priority = priority if priority is not None else row["priority"]

        cursor.execute(
            """
            UPDATE tasks SET status = ?, assigned_to = ?, title = ?, priority = ?
            WHERE id = ?
            """,
            (new_status, new_assigned, new_title, new_priority, task_id)
        )
        conn.commit()

        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return dict(cursor.fetchone())


def delete_task(task_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0


# =========================================================================
# Submissions & Grading (Teacher / Mentor Review)
# =========================================================================

def submit_project(project_id: str, team_id: str, submitted_by: str, submission_title: str, repository_notes: str, files_snapshot_json: str = "{}") -> Dict[str, Any]:
    submission_id = f"sub_{secrets.token_hex(5)}"
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO submissions (id, project_id, team_id, submitted_by, submission_title, repository_notes, files_snapshot_json, grade_score, feedback, graded_by, submitted_at, graded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '', '', ?, '')
            """,
            (submission_id, project_id, team_id, submitted_by, submission_title, repository_notes, files_snapshot_json, now)
        )
        cursor.execute("UPDATE projects SET status = 'submitted' WHERE id = ?", (project_id,))
        conn.commit()

    return {
        "id": submission_id,
        "project_id": project_id,
        "team_id": team_id,
        "submitted_by": submitted_by,
        "submission_title": submission_title,
        "repository_notes": repository_notes,
        "files_snapshot_json": files_snapshot_json,
        "submitted_at": now,
        "status": "submitted"
    }


def get_project_submissions(project_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM submissions WHERE project_id = ? ORDER BY submitted_at DESC", (project_id,))
        return [dict(r) for r in cursor.fetchall()]


def grade_submission(submission_id: str, grade_score: int, feedback: str, graded_by: str) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,))
        sub = cursor.fetchone()
        if not sub:
            return None
        project_id = sub["project_id"]

        cursor.execute(
            """
            UPDATE submissions
            SET grade_score = ?, feedback = ?, graded_by = ?, graded_at = ?
            WHERE id = ?
            """,
            (grade_score, feedback, graded_by, now, submission_id)
        )
        cursor.execute("UPDATE projects SET status = 'graded' WHERE id = ?", (project_id,))
        conn.commit()

        cursor.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,))
        return dict(cursor.fetchone())


# =========================================================================
# Maintaining Streak Feature (Forest Visualizer)
# =========================================================================

def get_streak(user_id: Optional[str] = None, team_id: Optional[str] = None) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if user_id and team_id:
            cursor.execute("SELECT * FROM streaks WHERE user_id = ? AND team_id = ?", (user_id, team_id))
        elif user_id:
            cursor.execute("SELECT * FROM streaks WHERE user_id = ? AND (team_id IS NULL OR team_id = '')", (user_id,))
        elif team_id:
            cursor.execute("SELECT * FROM streaks WHERE team_id = ? AND (user_id IS NULL OR user_id = '')", (team_id,))
        else:
            return {
                "current_streak": 1,
                "longest_streak": 1,
                "trees_count": 1,
                "total_sprints": 1,
                "tier": "Sprout",
                "last_activity_date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
            }
        row = cursor.fetchone()
        if not row:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return {
                "current_streak": 1,
                "longest_streak": 1,
                "trees_count": 1,
                "total_sprints": 1,
                "tier": "Sprout",
                "last_activity_date": today_str
            }
        data = dict(row)
        trees = data["trees_count"]
        # Calculate tier
        if trees >= 30:
            tier = "Ancient Sanctuary"
        elif trees >= 15:
            tier = "Lush Forest"
        elif trees >= 7:
            tier = "Thriving Woodland"
        elif trees >= 3:
            tier = "Young Grove"
        else:
            tier = "Seedling Sprout"
        data["tier"] = tier
        return data


def record_activity(user_id: Optional[str] = None, team_id: Optional[str] = None) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    today_str = today.strftime("%Y-%m-%d")
    u_key = user_id or ""
    t_key = team_id or ""

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM streaks WHERE (user_id = ? OR (user_id IS NULL AND ? = ''))
                                     AND (team_id = ? OR (team_id IS NULL AND ? = ''))
            """,
            (u_key, u_key, t_key, t_key)
        )
        row = cursor.fetchone()

        if not row:
            streak_id = f"strk_{secrets.token_hex(5)}"
            cursor.execute(
                """
                INSERT INTO streaks (id, user_id, team_id, current_streak, longest_streak, last_activity_date, total_sprints, trees_count)
                VALUES (?, ?, ?, 1, 1, ?, 1, 1)
                """,
                (streak_id, u_key, t_key, today_str)
            )
            conn.commit()
            return {
                "current_streak": 1,
                "longest_streak": 1,
                "trees_count": 1,
                "total_sprints": 1,
                "last_activity_date": today_str,
                "streak_increased": True,
                "message": "First tree planted in your forest! 🌳"
            }

        data = dict(row)
        last_date = datetime.strptime(data["last_activity_date"], "%Y-%m-%d").date()
        diff_days = (today - last_date).days

        cur_streak = data["current_streak"]
        long_streak = data["longest_streak"]
        total_sprints = data["total_sprints"] + 1
        trees_count = data["trees_count"]
        streak_increased = False

        if diff_days == 0:
            # Same day activity, maintain streak, increment sprints
            pass
        elif diff_days == 1:
            # Consecutive day! Maintain and advance streak
            cur_streak += 1
            trees_count = cur_streak
            long_streak = max(long_streak, cur_streak)
            streak_increased = True
        else:
            # Missed a day or more, reset streak to 1
            cur_streak = 1
            trees_count = max(trees_count, 1)

        cursor.execute(
            """
            UPDATE streaks
            SET current_streak = ?, longest_streak = ?, last_activity_date = ?, total_sprints = ?, trees_count = ?
            WHERE id = ?
            """,
            (cur_streak, long_streak, today_str, total_sprints, trees_count, data["id"])
        )
        conn.commit()

        msg = f"Streak active: {cur_streak} day(s)! Forest size: {trees_count} tree(s)."
        if streak_increased:
            msg = f"Consecutive streak preserved! 🌳 +1 Tree added to your forest (Total: {trees_count})."

        return {
            "current_streak": cur_streak,
            "longest_streak": long_streak,
            "trees_count": trees_count,
            "total_sprints": total_sprints,
            "last_activity_date": today_str,
            "streak_increased": streak_increased,
            "message": msg
        }


# =========================================================================
# Room Metadata & Password Protection (Teacher / Mentor Access)
# =========================================================================

def upsert_room_metadata(room_id: str, name: str, language: str = "python", owner_id: str = "", password: str = "", is_private: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    pwd_hash = ""
    if password:
        pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM room_metadata WHERE room_id = ?", (room_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE room_metadata
                SET name = ?, language = ?, password_hash = COALESCE(NULLIF(?, ''), password_hash), is_private = ?
                WHERE room_id = ?
                """,
                (name, language, pwd_hash, 1 if is_private else 0, room_id)
            )
        else:
            cursor.execute(
                """
                INSERT INTO room_metadata (room_id, name, language, owner_id, password_hash, is_private, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (room_id, name, language, owner_id, pwd_hash, 1 if is_private else 0, now)
            )
        conn.commit()

    return {
        "room_id": room_id,
        "name": name,
        "language": language,
        "owner_id": owner_id,
        "has_password": bool(pwd_hash or (row and row["password_hash"])),
        "is_private": bool(is_private)
    }


def get_room_metadata(room_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT room_id, name, language, owner_id, (password_hash != '') as has_password, is_private, created_at FROM room_metadata WHERE room_id = ?", (room_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def verify_room_password(room_id: str, password: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM room_metadata WHERE room_id = ?", (room_id,))
        row = cursor.fetchone()
        if not row or not row["password_hash"]:
            return True  # No password set, freely accessible
        given_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return secrets.compare_digest(given_hash, row["password_hash"])


def delete_room_record(room_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM room_metadata WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM mentor_annotations WHERE room_id = ?", (room_id,))
        conn.commit()
        return True


# =========================================================================
# Mentor Problematic Line Annotations & Comments
# =========================================================================

def add_mentor_annotation(room_id: str, filename: str, line_number: int, comment: str, problematic_level: str = "warning", author_name: str = "Mentor") -> Dict[str, Any]:
    annotation_id = f"ann_{secrets.token_hex(5)}"
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO mentor_annotations (id, room_id, filename, line_number, comment, problematic_level, author_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (annotation_id, room_id, filename, line_number, comment, problematic_level, author_name, now)
        )
        conn.commit()
    return {
        "id": annotation_id,
        "room_id": room_id,
        "filename": filename,
        "line_number": line_number,
        "comment": comment,
        "problematic_level": problematic_level,
        "author_name": author_name,
        "created_at": now
    }


def get_mentor_annotations(room_id: str, filename: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if filename:
            cursor.execute("SELECT * FROM mentor_annotations WHERE room_id = ? AND filename = ? ORDER BY line_number ASC", (room_id, filename))
        else:
            cursor.execute("SELECT * FROM mentor_annotations WHERE room_id = ? ORDER BY filename, line_number ASC", (room_id,))
        return [dict(r) for r in cursor.fetchall()]


def delete_mentor_annotation(annotation_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mentor_annotations WHERE id = ?", (annotation_id,))
        conn.commit()
        return cursor.rowcount > 0


# =========================================================================
# Notifications Center
# =========================================================================

def create_notification(user_id: str, title: str, message: str, notif_type: str = "info", link: str = "") -> Dict[str, Any]:
    notif_id = f"notif_{secrets.token_hex(5)}"
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO notifications (id, user_id, title, message, type, link, is_read, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (notif_id, user_id, title, message, notif_type, link, now)
        )
        conn.commit()
    return {
        "id": notif_id,
        "user_id": user_id,
        "title": title,
        "message": message,
        "type": notif_type,
        "link": link,
        "is_read": 0,
        "created_at": now
    }


def get_user_notifications(user_id: str, limit: int = 25) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit)
        )
        return [dict(r) for r in cursor.fetchall()]


def mark_notification_read(notif_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notif_id,))
        conn.commit()
        return cursor.rowcount > 0


# Auto initialize when imported
init_db()
