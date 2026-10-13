import sqlite3
import os
import json
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

from app.core.config import DATA_DIR, MASTER_DATA_DIR
from app.core.security import hash_password, verify_password

load_dotenv()

DB_PATH = DATA_DIR / "users.db"


def _get_supabase_config():
    url = (os.getenv("SUPABASE_URL", "") or "https://viflznbwqrunivhfoavq.supabase.co").rstrip("/")
    key = (
        os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    )
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    return url, key, headers


def init_user_db():
    """Initializes local SQLite cache table for resilience in case of network outages."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Product Intelligence Lead',
            avatar_url TEXT,
            timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            notifications_enabled INTEGER NOT NULL DEFAULT 1,
            theme TEXT NOT NULL DEFAULT 'light',
            has_master_excel INTEGER NOT NULL DEFAULT 1,
            master_excel_filename TEXT,
            master_excel_path TEXT,
            master_excel_records INTEGER DEFAULT 3513,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            session_token TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_user_db()


class UserService:
    """
    User & Employee Management Service.
    Primary store: Supabase (PostgREST table 'app_users' and 'user_sessions').
    Secondary fallback: Local SQLite cache ('data/users.db').
    """

    @staticmethod
    def _get_connection():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def _save_local_cache(cls, user_data: Dict[str, Any]):
        """Caches user data in local SQLite for ultra-fast reads and offline resilience."""
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO app_users (
                    username, password_hash, display_name, role, avatar_url,
                    timezone, notifications_enabled, theme, has_master_excel,
                    master_excel_filename, master_excel_records
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    display_name = EXCLUDED.display_name,
                    role = EXCLUDED.role,
                    avatar_url = EXCLUDED.avatar_url,
                    timezone = EXCLUDED.timezone,
                    notifications_enabled = EXCLUDED.notifications_enabled,
                    theme = EXCLUDED.theme,
                    has_master_excel = EXCLUDED.has_master_excel,
                    master_excel_filename = EXCLUDED.master_excel_filename,
                    master_excel_records = EXCLUDED.master_excel_records,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                user_data["username"].strip().lower(),
                user_data["password_hash"],
                user_data.get("display_name") or user_data["username"],
                user_data.get("role") or "Product Intelligence Lead",
                user_data.get("avatar_url"),
                user_data.get("timezone", "Asia/Kolkata"),
                1 if user_data.get("notifications_enabled", True) else 0,
                user_data.get("theme", "light"),
                1 if user_data.get("has_master_excel", True) else 0,
                user_data.get("master_excel_filename") or "Master_Catalog_Columbia.xlsx",
                user_data.get("master_excel_records", 3513)
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[USER_SERVICE] ⚠️ Local cache write error: {e}", flush=True)

    @classmethod
    def _get_local_user(cls, username: str) -> Optional[Dict[str, Any]]:
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM app_users WHERE username = ?", (username.strip().lower(),))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return None
            d = dict(row)
            d["has_master_excel"] = bool(d.get("has_master_excel", 1))
            return d
        except Exception:
            return None

    @classmethod
    def get_user(cls, username: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves user profile from Supabase 'app_users' table.
        Falls back to local cache if Supabase is unreachable or table not yet initialized.
        """
        clean_user = username.strip().lower()
        url, key, headers = _get_supabase_config()

        if url and key:
            try:
                with httpx.Client(timeout=4.0) as client:
                    res = client.get(
                        f"{url}/rest/v1/app_users?username=eq.{clean_user}&select=*",
                        headers=headers
                    )
                    if res.status_code == 200:
                        rows = res.json()
                        if rows:
                            u_data = rows[0]
                            cls._save_local_cache(u_data)
                            return u_data
            except Exception as e:
                print(f"[USER_SERVICE] ⚠️ Supabase get_user connection error: {e}", flush=True)

        # Fallback to local SQLite cache
        return cls._get_local_user(clean_user)

    @classmethod
    def authenticate(cls, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Authenticates user against Supabase-stored password hash.
        """
        clean_user = username.strip().lower()
        user = cls.get_user(clean_user)
        if not user:
            return None

        # Verify hashed password
        stored_hash = user.get("password_hash", "")
        if verify_password(password, stored_hash):
            return user

        return None

    @classmethod
    def record_session(
        cls,
        username: str,
        session_token: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """Records active JWT authentication session into Supabase 'user_sessions' table."""
        url, key, headers = _get_supabase_config()
        clean_user = username.strip().lower()

        # Try Supabase session insert
        if url and key:
            try:
                with httpx.Client(timeout=4.0) as client:
                    client.post(
                        f"{url}/rest/v1/user_sessions",
                        headers=headers,
                        json={
                            "username": clean_user,
                            "session_token": session_token[:40] + "..." if len(session_token) > 40 else session_token,
                            "ip_address": ip_address,
                            "user_agent": user_agent,
                        }
                    )
            except Exception:
                pass

        # Also log to local session table
        try:
            import uuid
            conn = cls._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_sessions (id, username, session_token, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), clean_user, session_token[:40], ip_address, user_agent))
            conn.commit()
            conn.close()
        except Exception:
            pass

    @classmethod
    def reset_password(cls, username: str, new_password: str) -> bool:
        """
        Updates user password hash directly in Supabase 'app_users' and local cache.
        """
        clean_user = username.strip().lower()
        new_hash = hash_password(new_password)
        url, key, headers = _get_supabase_config()
        updated_remote = False

        if url and key:
            try:
                with httpx.Client(timeout=5.0) as client:
                    r = client.patch(
                        f"{url}/rest/v1/app_users?username=eq.{clean_user}",
                        headers=headers,
                        json={
                            "password_hash": new_hash,
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }
                    )
                    if r.status_code in (200, 204):
                        updated_remote = True
                        print(f"[USER_SERVICE] [SUPABASE] Updated password hash for @{clean_user} in Supabase.", flush=True)
            except Exception as e:
                print(f"[USER_SERVICE] ⚠️ Failed updating password in Supabase: {e}", flush=True)

        # Update local SQLite cache
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE app_users
                SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
                WHERE username = ?
            """, (new_hash, clean_user))
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            return affected > 0 or updated_remote
        except Exception:
            return updated_remote

    @classmethod
    def update_profile(
        cls,
        username: str,
        display_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        timezone_val: Optional[str] = None,
        notifications_enabled: Optional[bool] = None,
        theme: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Updates user profile data in Supabase 'app_users' and local cache.
        """
        clean_user = username.strip().lower()
        payload = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if display_name is not None:
            payload["display_name"] = display_name.strip()
        if avatar_url is not None:
            payload["avatar_url"] = avatar_url.strip()
        if timezone_val is not None:
            payload["timezone"] = timezone_val.strip()
        if notifications_enabled is not None:
            payload["notifications_enabled"] = bool(notifications_enabled)
        if theme is not None:
            payload["theme"] = theme.strip()

        url, key, headers = _get_supabase_config()
        if url and key:
            try:
                with httpx.Client(timeout=5.0) as client:
                    client.patch(
                        f"{url}/rest/v1/app_users?username=eq.{clean_user}",
                        headers=headers,
                        json=payload
                    )
                    print(f"[USER_SERVICE] [SUPABASE] Synchronized profile update for @{clean_user} to Supabase.", flush=True)
            except Exception as e:
                print(f"[USER_SERVICE] ⚠️ Supabase update_profile error: {e}", flush=True)

        # Update local cache
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()
            fields = []
            params = []
            if display_name is not None:
                fields.append("display_name = ?")
                params.append(display_name.strip())
            if avatar_url is not None:
                fields.append("avatar_url = ?")
                params.append(avatar_url.strip())
            if timezone_val is not None:
                fields.append("timezone = ?")
                params.append(timezone_val.strip())
            if notifications_enabled is not None:
                fields.append("notifications_enabled = ?")
                params.append(1 if notifications_enabled else 0)
            if theme is not None:
                fields.append("theme = ?")
                params.append(theme.strip())

            if fields:
                fields.append("updated_at = CURRENT_TIMESTAMP")
                params.append(clean_user)
                query = f"UPDATE app_users SET {', '.join(fields)} WHERE username = ?"
                cursor.execute(query, tuple(params))
                conn.commit()
            conn.close()
        except Exception:
            pass

        return cls.get_user(clean_user)

    @classmethod
    def set_user_master_excel(
        cls,
        username: str,
        filename: str,
        file_path: str,
        record_count: int
    ) -> bool:
        """Saves user Master Excel status to Supabase 'app_users'."""
        clean_user = username.strip().lower()
        url, key, headers = _get_supabase_config()
        if url and key:
            try:
                with httpx.Client(timeout=5.0) as client:
                    client.patch(
                        f"{url}/rest/v1/app_users?username=eq.{clean_user}",
                        headers=headers,
                        json={
                            "has_master_excel": True,
                            "master_excel_filename": filename,
                            "master_excel_records": record_count,
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }
                    )
            except Exception:
                pass

        try:
            conn = cls._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE app_users
                SET has_master_excel = 1,
                    master_excel_filename = ?,
                    master_excel_path = ?,
                    master_excel_records = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE username = ?
            """, (filename, file_path, record_count, clean_user))
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            return affected > 0
        except Exception:
            return True

    @classmethod
    def get_user_master_excel_status(cls, username: str) -> Dict[str, Any]:
        u = cls.get_user(username)
        if not u:
            return {"has_master_excel": True}
        return {
            "has_master_excel": bool(u.get("has_master_excel", True)),
            "filename": u.get("master_excel_filename") or "Master_Catalog_Columbia.xlsx",
            "file_path": u.get("master_excel_path"),
            "record_count": u.get("master_excel_records", 3513)
        }


user_service = UserService()
