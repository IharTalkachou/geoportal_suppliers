import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import time
from datetime import datetime, timedelta

# 🔐 Импорты авторизации и кэша
from config.auth import (
    authenticate_user, init_session, check_session_timeout, logout_user, log_action
)
from ui.suppliers_tab import render_suppliers_tab
from ui.analytics_tab import render_analytics_tab
from ui.datasets_tab import render_datasets_tab
from ui.project_dashboard import render_project_dashboard
from ui.admin_panel import render_admin_panel

from config.session_store import create_token, restore_session, destroy_session


# ==========================================
# 🌍 1. КОНФИГ СТРАНИЦЫ
# ==========================================
st.set_page_config(page_title="Поставщики Национального геопортала", layout="wide", page_icon="🌍")

load_dotenv()
DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
engine = create_engine(DB_URL, pool_pre_ping=True)

# ==========================================
# 🔐 2. БЛОК АВТОРИЗАЦИИ (СЕРВЕРНАЯ СЕССИЯ)
# ==========================================
if "auth" not in st.session_state:
    # 1. Проверяем, есть ли токен в URL (пришёл с Ctrl+R)
    token = st.query_params.get("session", None)
    if token:
        restored = restore_session(token)
        if restored:
            st.session_state["auth"] = restored
            st.query_params.pop("session", None)  # Очищаем токен из URL после успеха
            st.rerun()
        else:
            st.query_params.pop("session", None)  # Токен истёк/невалиден

    # 2. Если сессия не восстановлена → рендерим форму входа
    if "auth" not in st.session_state:
        st.title("🔐 Вход в систему")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown("### 🗺️ Геопортал")
            st.caption("Система управления поставщиками пространственных данных")
        
        with col2:
            with st.form("login_form"):
                username = st.text_input("👤 Имя пользователя")
                password = st.text_input("🔑 Пароль", type="password")
                submit = st.form_submit_button("🚪 Войти", type="primary", use_container_width=True)
                
                if submit:
                    if not username or not password:
                        st.error("❌ Введите имя и пароль")
                    else:
                        try:
                            with Session(engine) as session:
                                user = authenticate_user(username, password, session)
                            if user:
                                init_session(user)
                                # 🔹 Генерируем токен и кладём его в URL
                                new_token = create_token(st.session_state["auth"])
                                st.query_params["session"] = new_token
                                st.success("✅ Вход выполнен!")
                                st.rerun()
                            else:
                                st.error("❌ Неверное имя или пароль")
                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ Ошибка подключения: {e}")
        st.stop()

# ==========================================
# ✅ 3. ОСНОВНОЙ ИНТЕРФЕЙС
# ==========================================
check_session_timeout()

header_left, header_right = st.columns([0.7, 0.3])
with header_left:
    st.title("🗺️ Управление поставщиками пространственных данных")

with header_right:
    with st.container():
        st.markdown(f"👤 **{st.session_state['auth']['display_name']}**", unsafe_allow_html=True)
        if st.session_state["auth"]["role"] in ("admin", "editor"):
            st.caption(f"🔑 Роль: `{st.session_state['auth']['role_name']}`")
            
        if st.session_state.get("show_admin", False):
            if st.button("⬅️ Назад к проектам", use_container_width=True, type="secondary", key="btn_back"):
                st.session_state["show_admin"] = False
                st.rerun()
        elif st.session_state["auth"]["role"] == "admin":
            if st.button("⚙️ Админ-панель", use_container_width=True, type="secondary", key="btn_admin"):
                st.session_state["show_admin"] = True
                st.rerun()

        if st.button("🚪 Выйти", use_container_width=True, type="primary", key="btn_logout"):
            uid = st.session_state.get("auth", {}).get("user_id")
            token = st.query_params.get("session")
            if uid and token:
                try:
                    with Session(engine) as log_sess:
                        log_action(log_sess, uid, "LOGOUT", target_table="auth")
                except Exception:
                    pass
            destroy_session(token or "")
            st.query_params.pop("session", None)
            st.session_state.pop("auth", None)
            st.session_state.pop("show_admin", None)
            st.rerun()

st.markdown("---")

if st.session_state.get("show_admin", False):
    with Session(engine) as session:
        render_admin_panel(session)
else:
    tabs = st.tabs(["📁 Поставщики", "🗄️ Наборы", "📋 Проекты", "📊 Аналитика"])
    user_role = st.session_state["auth"]["role"]
    with tabs[0]:
        with Session(engine) as session: render_suppliers_tab(session, user_role=user_role)
    with tabs[1]: 
        with Session(engine) as session: render_datasets_tab(session, user_role=user_role)  
    with tabs[2]:
        with Session(engine) as session: render_project_dashboard(session, user_role=user_role)      
    with tabs[3]:
        render_analytics_tab(user_role=user_role)