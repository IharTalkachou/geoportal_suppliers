import bcrypt
import json
import streamlit as st
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
from config.settings_handler import load_settings
# 🟢 Импортируем готовый engine
from config.database import engine
# Единый источник таймаута сессии (используется и здесь, и в session_store.py)
from config.session_store import get_session_timeout

ROLE_NAMES = {
    "admin": "Администратор",
    "editor": "Редактор",
    "user": "Пользователь"
}

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(12)).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def log_action(user_id: int, action: str, target_table: str = None,
               target_id: int = None, old: dict = None, new: dict = None):
    """
    Обновленная функция аудита: теперь использует системный пул соединений.
    """
    import sys
    # Пишем в консоль для Docker/Logs
    print(f"🔍 [AUDIT] user={user_id}, action={action}", file=sys.stderr, flush=True)

    try:
        with Session(engine) as sess:
            sess.execute(text("""
                INSERT INTO audit_log (user_id, action, target_table, target_id, old_value, new_value, created_at)
                VALUES (:uid, :act, :tbl, :tid, :old, :new, NOW())
            """), {
                "uid": user_id, "act": action, "tbl": target_table, "tid": target_id,
                "old": json.dumps(old, ensure_ascii=False, default=str) if old else None,
                "new": json.dumps(new, ensure_ascii=False, default=str) if new else None
            })
            sess.commit()
    except Exception as e:
        print(f"❌ [AUDIT] Ошибка записи: {e}", file=sys.stderr, flush=True)

def authenticate_user(username: str, password: str, session) -> dict | None:
    res = session.execute(text("""
        SELECT user_id, username, display_name, password_hash, role, is_active, last_login 
        FROM users WHERE username = :uname
    """), {"uname": username}).fetchone()
    
    if not res: return None
        
    user_data = dict(res._mapping)
    if not user_data["is_active"]:
        raise ValueError("🔒 Учётная запись заблокирована. Обратитесь к администратору.")
        
    if verify_password(password, user_data["password_hash"]):
        session.execute(text("UPDATE users SET last_login = :now WHERE user_id = :uid"),
                        {"now": datetime.now(), "uid": user_data["user_id"]})
        session.commit()
        log_action(user_data["user_id"], "LOGIN", target_table="auth")
        return user_data
    return None

def init_session(user_data: dict):
    st.session_state["auth"] = {
        "user_id": user_data["user_id"],
        "username": user_data["username"],
        "display_name": user_data["display_name"] or user_data["username"],
        "role": user_data["role"],
        "role_name": ROLE_NAMES.get(user_data["role"], user_data["role"]),
        "last_active": datetime.now()
    }

@st.cache_data(ttl=60)
def get_current_user_status(user_id: int):
    """Актуальные role/is_active пользователя из БД. Кэш 60с - чтобы отзыв прав
    администратором применялся к уже открытой сессии быстро, но без запроса к БД
    на каждый rerun."""
    try:
        with Session(engine) as session:
            res = session.execute(text(
                "SELECT role, is_active FROM users WHERE user_id = :uid"
            ), {"uid": user_id}).fetchone()
        return dict(res._mapping) if res else None
    except Exception:
        return None

def check_session_timeout(token: str = None):
    if "auth" in st.session_state:
        auth = st.session_state["auth"]
        last = auth["last_active"]

        # 🟢 ИСПРАВЛЕНО: Вызываем функцию для получения актуального таймаута
        timeout_limit = get_session_timeout()

        if datetime.now() - last > timedelta(minutes=timeout_limit):
            from config.session_store import destroy_session
            if token:
                destroy_session(token)
            logout_user()
            st.rerun()
            return

        # Отозванные права/блокировка учётной записи должны прервать уже
        # активную сессию, а не только заблокировать следующий вход
        current = get_current_user_status(auth["user_id"])
        if current is None or not current["is_active"]:
            from config.session_store import destroy_session
            if token:
                destroy_session(token)
            log_action(auth["user_id"], "SESSION_REVOKED", target_table="auth",
                       new={"reason": "account_deactivated"})
            logout_user()
            st.rerun()
            return

        if current["role"] != auth["role"]:
            auth["role"] = current["role"]
            auth["role_name"] = ROLE_NAMES.get(current["role"], current["role"])
            log_action(auth["user_id"], "SESSION_ROLE_UPDATED", target_table="auth",
                       new={"role": current["role"]})

        st.session_state["auth"]["last_active"] = datetime.now()
        if token:
            from config.session_store import sync_session_to_disk
            sync_session_to_disk(token, st.session_state["auth"])

def logout_user():
    st.session_state.pop("auth", None)
    st.session_state.pop("show_admin", None)
    st.rerun()

def require_role(min_role: str):
    hierarchy = {"user": 1, "editor": 2, "admin": 3}
    current_role = st.session_state.get("auth", {}).get("role")
    if not current_role or hierarchy.get(current_role, 0) < hierarchy.get(min_role, 0):
        st.error("🔒 Недостаточно прав для доступа к этому разделу.")
        st.stop()