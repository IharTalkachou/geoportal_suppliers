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
    token = st.query_params.get("session")
    if token:
        # Рекомендую поставить strict_ip=True для корпоративной среды
        restored = restore_session(token, strict_ip=True) 
        if restored:
            st.session_state["auth"] = restored
            st.rerun()
        else:
            # ✅ МЫ УБРАЛИ destroy_session(token)!
            # Если токен не подошел (чужой браузер), мы просто убираем 
            # его из URL этого браузера, чтобы показать форму входа.
            # Файл на диске остается целым для оригинального пользователя.
            st.query_params.pop("session", None)
            st.warning("⚠️ Невозможно использовать эту ссылку. Пожалуйста, авторизуйтесь.")

    # 2. Если сессия не восстановлена → рендерим форму входа
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

st.markdown("""
    <style>
        /* 1. Общий контейнер */
        .block-container {
            padding-top: 3rem;
            padding-bottom: 0rem;
        }
        
        /* 2. Заголовок Header 3 */
        h3 {
            margin-top: -0.5rem;
            margin-bottom: 0rem;
            font-size: 1.4rem !important;
        }

        /* 3. Информация о пользователе */
        .user-info {
            font-size: 0.8rem;
            line-height: 1.1;
            margin-bottom: 0.4rem;
            text-align: right;
            color: #555;
        }

        /* 4. КНОПКИ: Делаем их действительно маленькими */
        .stButton button {
            height: 1.6rem !important;   /* Очень маленькая высота */
            font-size: 0.75rem !important; /* Уменьшенный шрифт */
            padding: 0px 8px !important;   /* Компактные внутренние отступы */
            border-radius: 4px !important;
            margin-top: 0px;
        }
        
        /* Убираем лишние отступы между кнопками в колонках */
        [data-testid="stHorizontalBlock"] {
            gap: 0.5rem !important;
        }
    </style>
""", unsafe_allow_html=True)

# Ряд заголовка
h_col1, h_col2 = st.columns([0.6, 0.4])

with h_col1:
    st.markdown("### 🗺️ Управление поставщиками Национального геопортала") # Сократил для экономии места

with h_col2:
    auth = st.session_state['auth']
    role_str = f"{auth['role_name']}"
    
    # Имя и роль в одну компактную строку справа
    st.markdown(f"""
        <div class="user-info">
            <b>{auth['display_name']}</b> | {role_str}
        </div>
    """, unsafe_allow_html=True)

    # Кнопки управления (теперь они будут крошечными)
    btn_col1, btn_col2 = st.columns([0.5, 0.5])
    
    with btn_col1:
        if st.session_state.get("show_admin", False):
            if st.button("⬅️ Назад", width='stretch', key="btn_back"):
                st.session_state["show_admin"] = False
                st.rerun()
        elif st.session_state["auth"]["role"] == "admin":
            if st.button("⚙️ Админ-панель", width='stretch', key="btn_admin"):
                st.session_state["show_admin"] = True
                st.rerun()

    with btn_col2:
        if st.button("🚪 Выход", width='stretch', type="primary", key="btn_logout"):
            uid = st.session_state.get("auth", {}).get("user_id")
            token = st.query_params.get("session")
            if uid and token:
                try:
                    from sqlalchemy.orm import Session
                    with Session(engine) as log_sess:
                        log_action(log_sess, uid, "LOGOUT", target_table="auth")
                except: pass
            destroy_session(token or "")
            st.query_params.clear()
            st.session_state.clear()
            st.rerun()

st.markdown("---")

if st.session_state.get("show_admin", False):
    with Session(engine) as session:
        render_admin_panel(session)
else:
    # 🔹 Вкладки рендерятся ВСЕГДА — без условий по active_tab!
    tabs = st.tabs(["📁 Поставщики", "🗄️ Наборы", "📋 Проекты", "📊 Аналитика"])
    user_role = st.session_state["auth"]["role"]
    
    with tabs[0]:
        with Session(engine) as session: 
            render_suppliers_tab(session, user_role=user_role)
    with tabs[1]: 
        with Session(engine) as session: 
            render_datasets_tab(session, user_role=user_role)  
    with tabs[2]:
        with Session(engine) as session: 
            render_project_dashboard(session, user_role=user_role)      
    with tabs[3]:
        render_analytics_tab(user_role=user_role)