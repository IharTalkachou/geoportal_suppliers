# ОБЩИЕ ИМПОРТЫ
print("[STARTUP] app.py: module start", flush=True)
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import time
from datetime import datetime, timedelta

# Импорты ядра
print("[STARTUP] app.py: before config.database import", flush=True)
from config.database import engine
print("[STARTUP] app.py: before config.settings_handler import", flush=True)
from config.settings_handler import load_settings
print("[STARTUP] app.py: before config.auth import", flush=True)
from config.auth import (
    authenticate_user, init_session, check_session_timeout, logout_user, log_action
)
print("[STARTUP] app.py: before config.session_store import", flush=True)
from config.session_store import create_token, restore_session, destroy_session
print("[STARTUP] app.py: all core config imports done", flush=True)

# Импорты интерфейса
from ui.suppliers_tab import render_suppliers_tab
from ui.analytics_tab import render_analytics_tab
from ui.datasets_tab import render_datasets_tab
from ui.project_dashboard import render_project_dashboard
from ui.admin_panel import render_admin_panel
from ui.requests_tab import render_requests_tab

# ==========================================
# 🌍 1. ИНИЦИАЛИЗАЦИЯ И КЭШИРОВАНИЕ
# ==========================================
st.set_page_config(page_title="Поставщики Национального геопортала", layout="wide", page_icon="🌍")
load_dotenv()

# Попытка загрузки настроек с обработкой ошибки БД
try:
    app_settings = load_settings()
except Exception as e:
    st.error("🔌 Ошибка подключения к базе данных. Пожалуйста, проверьте соединение.")
    st.stop()

# ==========================================
# 🛡️ 2. РЕЖИМ ОБСЛУЖИВАНИЯ И АВТОРИЗАЦИЯ
# ==========================================

# Глобальное предупреждение (если включено в настройках)
if app_settings.get("maintenance_warning", False):
    st.warning(f"⚠️ {app_settings.get('maintenance_message')}")

if "auth" not in st.session_state:
    # Проверка существующего токена в URL
    token = st.query_params.get("session")
    if token:
        restored = restore_session(token, strict_ip=True) 
        if restored:
            st.session_state["auth"] = restored
            st.rerun()
        else:
            st.query_params.pop("session", None)
            st.warning("⚠️ Сессия истекла или недействительна. Пожалуйста, войдите снова.")

    # Форма входа (если авторизации нет)
    if "auth" not in st.session_state:
        st.title("🔐 Вход в систему")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown("### 🗺️ Национальный геопортал")
            st.caption("Система управления поставщиками пространственных данных")
        
        with col2:
            with st.form("login_form"):
                username = st.text_input("👤 Имя пользователя")
                password = st.text_input("🔑 Пароль", type="password")
                submit = st.form_submit_button("🚪 Войти", type="primary", width="stretch")
                
                if submit:
                    if not username or not password:
                        st.error("❌ Введите имя и пароль")
                    else:
                        try:
                            with Session(engine) as session:
                                user = authenticate_user(username, password, session)
                            if user:
                                # Проверка режима обслуживания
                                if app_settings.get("maintenance_mode", False) and user["role"] != "admin":
                                    st.error(f"🏗️ {app_settings.get('lockout_message')}")
                                else:
                                    init_session(user)
                                    new_token = create_token(st.session_state["auth"])
                                    st.query_params["session"] = new_token
                                    st.success("✅ Вход выполнен!")
                                    st.rerun()
                            else:
                                st.error("❌ Неверное имя или пароль")
                        except Exception as e:
                            st.error(f"❌ Ошибка подключения: {e}")
        st.stop()

# Проверка режима обслуживания для уже вошедших пользователей (не админов)
if app_settings.get("maintenance_mode", False) and st.session_state["auth"]["role"] != "admin":
    st.error(f"🏗️ {app_settings.get('lockout_message')}")
    if st.button("🚪 Выйти"):
        logout_user()
    st.stop()

# Проверка таймаута сессии
check_session_timeout(st.query_params.get("session"))

# ==========================================
# 🎨 3. СТИЛИЗАЦИЯ И ШАПКА ИНТЕРФЕЙСА
# ==========================================
st.markdown("""
    <style>
        .block-container { padding-top: 3rem; padding-bottom: 0rem; }
        h3 { margin-top: -0.5rem; margin-bottom: 0rem; font-size: 1.4rem !important; }
        .user-info { font-size: 0.8rem; line-height: 1.1; margin-bottom: 0.4rem; text-align: right; color: #555; }
        .stButton button {
            height: 1.6rem !important;
            font-size: 0.75rem !important;
            padding: 0px 8px !important;
            border-radius: 4px !important;
            margin-top: 0px;
        }
        [data-testid="stHorizontalBlock"] { gap: 0.5rem !important; }
    </style>
""", unsafe_allow_html=True)

h_col1, h_col2 = st.columns([0.6, 0.4])
with h_col1:
    st.markdown("### 🗺️ Управление поставщиками Национального геопортала")

with h_col2:
    auth = st.session_state['auth']
    st.markdown(f'<div class="user-info"><b>{auth["display_name"]}</b> | {auth["role_name"]}</div>', unsafe_allow_html=True)

    btn_col1, btn_col2 = st.columns([0.5, 0.5])
    with btn_col1:
        if st.session_state.get("show_admin", False):
            if st.button("⬅️ Назад", width='stretch', key="btn_back"):
                st.session_state["show_admin"] = False
                st.rerun()
        elif auth["role"] == "admin":
            if st.button("⚙️ Админ-панель", width='stretch', key="btn_admin"):
                st.session_state["show_admin"] = True
                st.rerun()
    with btn_col2:
        if st.button("🚪 Выход", width='stretch', type="primary", key="btn_logout"):
            uid = st.session_state.get("auth", {}).get("user_id")
            token = st.query_params.get("session")
            if uid and token:
                try:
                    with Session(engine) as log_sess:
                        log_action(uid, "LOGOUT", target_table="auth")
                except: pass
            destroy_session(token or "")
            st.query_params.clear()
            st.session_state.clear()
            st.rerun()

st.markdown("---")

# ==========================================
# 🧭 4. РОУТИНГ И НАВИГАЦИЯ (СО СПИННЕРОМ)
# ==========================================

# Оборачиваем весь процесс построения контента в спиннер
with st.spinner("⏳ Синхронизация данных..."):
    if st.session_state.get("show_admin", False):
        with Session(engine) as session:
            render_admin_panel(session)
    else:
        nav_options = ["📁 Поставщики", "🗄️ Наборы", "📋 Проекты", "📩 Заявки", "📊 Аналитика"]
        
        if "main_nav" not in st.session_state:
            st.session_state["main_nav"] = nav_options[0]
        
        # Навигация
        choice = st.segmented_control(
            "Навигация",
            options=nav_options,
            key="main_nav",
            label_visibility="collapsed"
        )
        st.markdown("<br>", unsafe_allow_html=True)

        user_role = auth["role"]
        
        # Диспетчер вкладок
        if choice == "📁 Поставщики":
            with Session(engine) as session: render_suppliers_tab(session, user_role=user_role)
        elif choice == "🗄️ Наборы":
            with Session(engine) as session: render_datasets_tab(session, user_role=user_role)
        elif choice == "📋 Проекты":
            with Session(engine) as session: render_project_dashboard(session, user_role=user_role)
        elif choice == "📩 Заявки":
            with Session(engine) as session: render_requests_tab(session, user_role=user_role)
        elif choice == "📊 Аналитика":
            render_analytics_tab(user_role=user_role)