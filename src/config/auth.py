import bcrypt
import json
import streamlit as st
from datetime import datetime, timedelta
from sqlalchemy import text

ROLE_NAMES = {
    "admin": "Администратор",
    "editor": "Редактор",
    "user": "Пользователь"
}
SESSION_TIMEOUT_MINUTES = 30

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(12)).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def log_action(user_id: int, action: str, target_table: str = None,
               target_id: int = None, old: dict = None, new: dict = None):
    import sys, os, json
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    # 🔹 Пишем в stderr + flush=True для мгновенного вывода в Docker
    print(f"🔍 [AUDIT] Вызов: user={user_id}, action={action}", file=sys.stderr, flush=True)

    try:
        # В Docker переменные уже в окружении, load_dotenv не нужен
        db_user = os.getenv('DB_USER')
        db_pass = os.getenv('DB_PASS')
        db_host = os.getenv('DB_HOST')
        db_port = os.getenv('DB_PORT')
        db_name = os.getenv('DB_NAME')

        if not all([db_user, db_pass, db_host, db_port, db_name]):
            print(f"❌ [AUDIT] Отсутствуют ENV переменные БД!", file=sys.stderr, flush=True)
            return

        engine = create_engine(f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}", pool_pre_ping=True)
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
            print(f"✅ [AUDIT] Записано в БД успешно", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"❌ [AUDIT] Ошибка: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    finally:
        if 'engine' in locals(): engine.dispose()

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
        # ✅ ИСПРАВЛЕНО: Первый аргумент (session) удалён
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

def check_session_timeout():
    if "auth" in st.session_state:
        last = st.session_state["auth"]["last_active"]
        # Если время вышло - выходим
        if datetime.now() - last > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
            logout_user()
            # st.warning здесь не сработает, так как logout_user делает st.rerun(),
            # лучше передать флаг в session_state, если нужно показать сообщение
            st.rerun()
        else:
            # ✅ ПРОДЛЕНИЕ СЕССИИ: При любом действии пользователя в интерфейсе
            # обновляем таймер, чтобы 30 минут отсчитывались заново
            st.session_state["auth"]["last_active"] = datetime.now()

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