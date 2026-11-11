"""
db_shared.py — Shared PostgreSQL database module
Used by both bot.py (Telegram bot) and app.py (Flask web app).
Connects via DATABASE_URL environment variable (set automatically by Railway).
"""
import os
import json
import secrets
import string
import psycopg
from psycopg.rows import dict_row
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_con():
    """Open a new PostgreSQL connection."""
    return psycopg.connect(DATABASE_URL)


# ═══════════════════════════════════════════════════════
#                   INIT ALL TABLES
# ═══════════════════════════════════════════════════════

def init_all():
    """Create all tables if they don't exist. Call once on startup."""
    con = get_con()
    cur = con.cursor()

    # users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     BIGINT PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            joined_at   TEXT,
            expires_at  TEXT,
            is_banned   INTEGER DEFAULT 0
        )
    """)

    # keys table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            key         TEXT PRIMARY KEY,
            days        INTEGER,
            created_at  TEXT,
            used_by     BIGINT DEFAULT NULL,
            used_at     TEXT DEFAULT NULL,
            sold_to     TEXT DEFAULT NULL
        )
    """)

    # hits_db table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hits_db (
            id          SERIAL PRIMARY KEY,
            cookie_json TEXT NOT NULL,
            email       TEXT,
            country     TEXT,
            quality     TEXT,
            saved_by    BIGINT,
            saved_at    TEXT
        )
    """)

    # nftoken_usage table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nftoken_usage (
            user_id     BIGINT,
            date        TEXT,
            count       INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )
    """)

    # free_user_cookies table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS free_user_cookies (
            user_id     BIGINT,
            date        TEXT,
            count       INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )
    """)

        # web_users table (for Flask web app login)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS web_users (
            id          SERIAL PRIMARY KEY,
            username    TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            role        TEXT DEFAULT 'user',
            created_at  TEXT,
            last_login  TEXT
        )
    """)

    # check_sessions table (for serverless Telegram bot checking)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS check_sessions (
            user_id        BIGINT PRIMARY KEY,
            chat_id        BIGINT,
            status_msg_id  BIGINT,
            bundles_json   TEXT,
            current_idx    INTEGER DEFAULT 0,
            total          INTEGER DEFAULT 0,
            active_count   INTEGER DEFAULT 0,
            inactive_count INTEGER DEFAULT 0,
            dead_count     INTEGER DEFAULT 0,
            hits_log_json  TEXT DEFAULT '[]',
            stop_flag      INTEGER DEFAULT 0,
            created_at     TEXT
        )
    """)

    con.commit()
    con.close()


# ═══════════════════════════════════════════════════════
#                   CHECK SESSIONS
# ═══════════════════════════════════════════════════════

def get_check_session(user_id: int):
    con = get_con()
    cur = con.cursor(row_factory=dict_row)
    cur.execute("SELECT * FROM check_sessions WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    con.close()
    return row

def create_check_session(user_id: int, chat_id: int, status_msg_id: int, bundles: list):
    con = get_con()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO check_sessions (
            user_id, chat_id, status_msg_id, bundles_json,
            current_idx, total, active_count, inactive_count, dead_count,
            hits_log_json, stop_flag, created_at
        ) VALUES (%s, %s, %s, %s, 0, %s, 0, 0, 0, '[]', 0, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            chat_id = EXCLUDED.chat_id,
            status_msg_id = EXCLUDED.status_msg_id,
            bundles_json = EXCLUDED.bundles_json,
            current_idx = 0,
            total = EXCLUDED.total,
            active_count = 0,
            inactive_count = 0,
            dead_count = 0,
            hits_log_json = '[]',
            stop_flag = 0,
            created_at = EXCLUDED.created_at
    """, (user_id, chat_id, status_msg_id, json.dumps(bundles), len(bundles), datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()

def update_check_session_progress(user_id: int, current_idx: int, active_count: int, inactive_count: int, dead_count: int, hits_log: list):
    con = get_con()
    cur = con.cursor()
    cur.execute("""
        UPDATE check_sessions
        SET current_idx = %s, active_count = %s, inactive_count = %s, dead_count = %s, hits_log_json = %s
        WHERE user_id = %s
    """, (current_idx, active_count, inactive_count, dead_count, json.dumps(hits_log), user_id))
    con.commit()
    con.close()

def set_check_session_stop(user_id: int) -> bool:
    con = get_con()
    cur = con.cursor()
    cur.execute("UPDATE check_sessions SET stop_flag = 1 WHERE user_id = %s RETURNING user_id", (user_id,))
    row = cur.fetchone()
    con.commit()
    con.close()
    return row is not None

def delete_check_session(user_id: int):
    con = get_con()
    cur = con.cursor()
    cur.execute("DELETE FROM check_sessions WHERE user_id = %s", (user_id,))
    con.commit()
    con.close()


# ═══════════════════════════════════════════════════════
#                   TELEGRAM USERS
# ═══════════════════════════════════════════════════════

def get_user(user_id: int):
    """Fetch user row. Returns tuple or None."""
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT user_id, username, first_name, joined_at, expires_at, is_banned FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    con.close()
    return row  # (user_id, username, first_name, joined_at, expires_at, is_banned)


def register_user(user, free_days: int):
    """Register a new Telegram user with free trial. No-op if already exists."""
    if get_user(user.id):
        return
    now = datetime.utcnow()
    expires = now + timedelta(days=free_days)
    con = get_con()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO users (user_id, username, first_name, joined_at, expires_at, is_banned) VALUES (%s,%s,%s,%s,%s,0) ON CONFLICT (user_id) DO NOTHING",
        (user.id, user.username or "", user.first_name or "",
         now.strftime("%Y-%m-%d %H:%M:%S"),
         expires.strftime("%Y-%m-%d %H:%M:%S"))
    )
    con.commit()
    con.close()


def set_ban(user_id: int, banned: bool):
    con = get_con()
    cur = con.cursor()
    cur.execute("UPDATE users SET is_banned = %s WHERE user_id = %s", (1 if banned else 0, user_id))
    con.commit()
    con.close()


def extend_access(user_id: int, days: int):
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT expires_at FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if row:
        try:
            base = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            if base < datetime.utcnow():
                base = datetime.utcnow()
        except Exception:
            base = datetime.utcnow()
        new_exp = base + timedelta(days=days)
        cur.execute("UPDATE users SET expires_at = %s WHERE user_id = %s",
                    (new_exp.strftime("%Y-%m-%d %H:%M:%S"), user_id))
    con.commit()
    con.close()


def expire_access(user_id: int):
    con = get_con()
    cur = con.cursor()
    past = (datetime.utcnow() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE users SET expires_at = %s WHERE user_id = %s", (past, user_id))
    con.commit()
    con.close()


def all_users():
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT user_id, username, first_name, joined_at, expires_at, is_banned FROM users")
    rows = cur.fetchall()
    con.close()
    return rows


def get_user_by_username(username: str):
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT user_id, username, first_name, joined_at, expires_at, is_banned FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
    row = cur.fetchone()
    con.close()
    return row


def get_user_tier(user_id: int, owner_id: int = None) -> str:
    """
    Returns tier: 'owner' | 'paid' | 'trial' | 'free_user' | 'banned'
    Pass owner_id to check ownership (or set OWNER_ID env var).
    """
    if owner_id is None:
        owner_id = int(os.environ.get("OWNER_ID", 0))
    if user_id == owner_id:
        return "owner"
    row = get_user(user_id)
    if not row:
        return "trial"
    _, _, _, _, expires_at, is_banned = row
    if is_banned:
        return "banned"
    try:
        exp = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return "free_user"
    if datetime.utcnow() <= exp:
        return "paid" if has_ever_redeemed_key(user_id) else "trial"
    return "free_user"


# ═══════════════════════════════════════════════════════
#                   KEYS SYSTEM
# ═══════════════════════════════════════════════════════

def create_key(days: int, sold_to: str = None) -> str:
    alphabet = string.ascii_uppercase + string.digits
    key = "NF-" + "".join(secrets.choice(alphabet) for _ in range(16))
    con = get_con()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO keys (key, days, created_at, used_by, used_at, sold_to) VALUES (%s, %s, %s, NULL, NULL, %s)",
        (key, days, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), sold_to)
    )
    con.commit()
    con.close()
    return key


def redeem_key(key: str, user_id: int):
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT days, used_by FROM keys WHERE key = %s", (key,))
    row = cur.fetchone()
    if not row:
        con.close()
        return False, "invalid"
    days, used_by = row
    if used_by is not None and used_by != 0:
        con.close()
        return False, "used"
    cur.execute(
        "UPDATE keys SET used_by = %s, used_at = %s WHERE key = %s",
        (user_id, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), key)
    )
    con.commit()
    con.close()
    extend_access(user_id, days)
    return True, days


def list_keys(used: bool = None):
    con = get_con()
    cur = con.cursor()
    if used is None:
        cur.execute("SELECT key, days, created_at, used_by, used_at, sold_to FROM keys")
    elif used:
        cur.execute("SELECT key, days, created_at, used_by, used_at, sold_to FROM keys WHERE used_by IS NOT NULL AND used_by != 0")
    else:
        cur.execute("SELECT key, days, created_at, used_by, used_at, sold_to FROM keys WHERE used_by IS NULL OR used_by = 0")
    rows = cur.fetchall()
    con.close()
    return rows


def has_ever_redeemed_key(user_id: int) -> bool:
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM keys WHERE used_by = %s LIMIT 1", (user_id,))
    row = cur.fetchone()
    con.close()
    return row is not None


# ═══════════════════════════════════════════════════════
#                   HITS DATABASE
# ═══════════════════════════════════════════════════════

def save_hit_to_db(bundle: dict, res: dict, user_id: int):
    con = get_con()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO hits_db (cookie_json, email, country, quality, saved_by, saved_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (json.dumps(bundle), res.get("email", "Unknown"), res.get("country", "Unknown"),
         res.get("quality", "HD"), user_id, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    )
    con.commit()
    con.close()


def get_random_hit():
    """Returns (id, bundle_dict) or (None, None)."""
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT id, cookie_json FROM hits_db ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    con.close()
    if row:
        try:
            return row[0], json.loads(row[1])
        except Exception:
            return None, None
    return None, None


def get_random_hit_full():
    """Returns dict with id, bundle, email, country, quality or None."""
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT id, cookie_json, email, country, quality FROM hits_db ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    con.close()
    if row:
        try:
            return {"id": row[0], "bundle": json.loads(row[1]),
                    "email": row[2], "country": row[3], "quality": row[4]}
        except Exception:
            return None
    return None


def delete_hit_from_db(hit_id: int):
    con = get_con()
    cur = con.cursor()
    cur.execute("DELETE FROM hits_db WHERE id = %s", (hit_id,))
    con.commit()
    con.close()


def count_hits_db() -> int:
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM hits_db")
    count = cur.fetchone()[0]
    con.close()
    return count


# ═══════════════════════════════════════════════════════
#                   NFTOKEN & FREE COOKIES
# ═══════════════════════════════════════════════════════

def get_nftoken_usage(user_id: int) -> int:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT count FROM nftoken_usage WHERE user_id=%s AND date=%s", (user_id, today))
    row = cur.fetchone()
    con.close()
    return row[0] if row else 0


def increment_nftoken_usage(user_id: int):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    con = get_con()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO nftoken_usage (user_id, date, count) VALUES (%s, %s, 1)
        ON CONFLICT (user_id, date) DO UPDATE SET count = nftoken_usage.count + 1
    """, (user_id, today))
    con.commit()
    con.close()


def get_free_user_cookies_today(user_id: int) -> int:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT count FROM free_user_cookies WHERE user_id=%s AND date=%s", (user_id, today))
    row = cur.fetchone()
    con.close()
    return row[0] if row else 0


def add_free_user_cookies(user_id: int, count: int):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    con = get_con()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO free_user_cookies (user_id, date, count) VALUES (%s, %s, %s)
        ON CONFLICT (user_id, date) DO UPDATE SET count = free_user_cookies.count + %s
    """, (user_id, today, count, count))
    con.commit()
    con.close()


# ═══════════════════════════════════════════════════════
#                   WEB USERS (Flask)
# ═══════════════════════════════════════════════════════

from werkzeug.security import generate_password_hash, check_password_hash


def init_web_admin(admin_username: str, admin_password: str):
    """Create default admin web user if not exists."""
    con = get_con()
    cur = con.cursor()
    cur.execute("SELECT id FROM web_users WHERE username = %s", (admin_username,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO web_users (username, password, role, created_at) VALUES (%s,%s,'admin',%s)",
            (admin_username, generate_password_hash(admin_password),
             datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        )
        con.commit()
    con.close()


def get_web_user_by_id(user_id: int):
    con = get_con()
    cur = con.cursor(row_factory=dict_row)
    cur.execute("SELECT * FROM web_users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    con.close()
    return row


def get_web_user_by_username(username: str):
    con = get_con()
    cur = con.cursor(row_factory=dict_row)
    cur.execute("SELECT * FROM web_users WHERE LOWER(username) = LOWER(%s)", (username,))
    row = cur.fetchone()
    con.close()
    return row


def get_all_web_users():
    con = get_con()
    cur = con.cursor(row_factory=dict_row)
    cur.execute("SELECT * FROM web_users ORDER BY id")
    rows = cur.fetchall()
    con.close()
    return rows


def add_web_user(username: str, password: str, role: str = "user"):
    if get_web_user_by_username(username):
        return False, "Username already exists."
    con = get_con()
    cur = con.cursor()
    try:
        cur.execute(
            "INSERT INTO web_users (username, password, role, created_at) VALUES (%s,%s,%s,%s)",
            (username, generate_password_hash(password), role,
             datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        )
        con.commit()
    except Exception as e:
        con.close()
        return False, str(e)
    con.close()
    return True, None


def delete_web_user(user_id: int):
    con = get_con()
    cur = con.cursor()
    cur.execute("DELETE FROM web_users WHERE id = %s", (user_id,))
    con.commit()
    con.close()


def update_last_login(user_id: int):
    con = get_con()
    cur = con.cursor()
    cur.execute("UPDATE web_users SET last_login = %s WHERE id = %s",
                (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), user_id))
    con.commit()
    con.close()


def verify_web_user(username: str, password: str):
    row = get_web_user_by_username(username)
    if not row:
        return None
    if check_password_hash(row["password"], password):
        return row
    return None


def change_web_password(user_id: int, new_password: str):
    con = get_con()
    cur = con.cursor()
    cur.execute("UPDATE web_users SET password = %s WHERE id = %s",
                (generate_password_hash(new_password), user_id))
    con.commit()
    con.close()
