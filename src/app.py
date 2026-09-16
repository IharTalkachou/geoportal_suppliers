# ОБЩИЕ ИМПОРТЫ
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import time
from datetime import datetime, timedelta

# Импорты ядра
from config.database import engine
from config.settings_handler import load_settings
from config.auth import (
    authenticate_user, init_session, check_session_timeout, logout_user, log_action
)
from config.session_store import create_token, restore_session, destroy_session, cleanup_expired_sessions

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

# Верхняя полоса Streamlit скрыта целиком (меню "три точки" с переключателем темы,
# печатью и "Made with Streamlit", кнопка Deploy, индикатор "Running"). Тема при этом
# закреплена светлой в .streamlit/config.toml - переключать её больше нечем.
#
# Взамен штатного индикатора - оверлей на весь экран, который ловит ЛЮБУЮ перерисовку:
# Streamlit держит состояние выполнения скрипта в атрибуте data-test-script-state
# корневого [data-testid="stApp"] (значения running / rerunRequested). Реализация
# чисто на CSS: во время rerun Python выполняется заново и нарисовать что-либо из
# Python физически некому - старый DOM заморожен, новый ещё не построен.
#
# Оверлей появляется с задержкой 500ms (animation-delay + начальная opacity: 0), поэтому
# быстрые reruns - переключение вкладок, чекбоксы - его вообще не показывают, а экран
# не мигает вуалью на каждое действие. pointer-events: all блокирует клики: во время
# перерисовки они всё равно теряются.
#
# ВНИМАНИЕ: data-testid и data-test-script-state - внутреннее API фронтенда Streamlit,
# не публичный контракт. Проверено на 1.57.0; после мажорного обновления убедиться,
# что атрибуты на месте (иначе оверлей просто перестанет показываться, интерфейс цел).
_GLOBAL_CSS = """
<style>
    /* --- Скрытие верхней полосы и её содержимого --- */
    [data-testid="stHeader"] { display: none !important; }
    [data-testid="stMainMenu"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stAppDeployButton"] { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }
    footer { visibility: hidden !important; }

    /* Верхний отступ задаётся ниже, в блоке стилизации шапки (.block-container),
       здесь намеренно не дублируется - иначе два правила спорят за одно значение */

    /* --- Оверлей загрузки поверх интерфейса --- */
    [data-testid="stApp"]::before {
        content: "";
        position: fixed;
        inset: 0;
        z-index: 999990;
        background: rgba(255, 255, 255, 0.55);
        backdrop-filter: blur(1.5px);
        opacity: 0;
        pointer-events: none;
    }
    [data-testid="stApp"]::after {
        content: "";
        position: fixed;
        top: 50%;
        left: 50%;
        width: 48px;
        height: 48px;
        margin: -24px 0 0 -24px;
        z-index: 999991;
        border: 4px solid rgba(49, 51, 63, 0.15);
        border-top-color: #ff4b4b;      /* акцентный цвет Streamlit */
        border-radius: 50%;
        opacity: 0;
        pointer-events: none;
    }

    /* Оверлей включается только пока скрипт выполняется */
    [data-testid="stApp"][data-test-script-state="running"]::before,
    [data-testid="stApp"][data-test-script-state="rerunRequested"]::before {
        pointer-events: all;
        animation: geo-overlay-in 120ms linear 500ms forwards;
    }
    [data-testid="stApp"][data-test-script-state="running"]::after,
    [data-testid="stApp"][data-test-script-state="rerunRequested"]::after {
        pointer-events: all;
        animation: geo-overlay-in 120ms linear 500ms forwards,
                   geo-spin 700ms linear 500ms infinite;
    }

    @keyframes geo-overlay-in { to { opacity: 1; } }
    @keyframes geo-spin { to { transform: rotate(360deg); } }

    /* Уважаем системную настройку "уменьшить движение": вуаль остаётся, вращение - нет */
    @media (prefers-reduced-motion: reduce) {
        [data-testid="stApp"][data-test-script-state="running"]::after,
        [data-testid="stApp"][data-test-script-state="rerunRequested"]::after {
            animation: geo-overlay-in 120ms linear 500ms forwards;
        }
    }
</style>
"""
st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)

load_dotenv()

# Попытка загрузки настроек с обработкой ошибки БД
try:
    app_settings = load_settings()
except Exception as e:
    st.error("🔌 Ошибка подключения к базе данных. Пожалуйста, проверьте соединение.")
    st.stop()

@st.cache_resource
def _startup_session_cleanup():
    # Выполняется один раз за время жизни процесса (не на каждый rerun) -
    # удаляет файлы сессий, накопившиеся в SESSION_DIR с истёкшим таймаутом
    return cleanup_expired_sessions()

_startup_session_cleanup()

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
        # strict_ip=False: IP легитимно меняется на мобильном интернете/VPN/роуминге,
        # защиту от угона токена обеспечивает fp_key (браузер/ОС/язык), IP-совпадение
        # больше не обязательно - при несовпадении IP попытка всё равно логируется
        # как SESSION_HIJACK_ATTEMPT внутри restore_session()
        restored = restore_session(token, strict_ip=False)
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
        .block-container { padding-top: 1.2rem; padding-bottom: 0rem; }
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

        /* --- Раскладка шапки ---
           Колонки объявлены в порядке "кнопки -> заголовок -> навигация": именно в этом
           порядке Streamlit складывает их друг под друга на узком экране. На широком
           экране порядок разворачивается через order в "заголовок -> навигация -> кнопки".

           Якорь - класс st-key-geo-header, который Streamlit вешает на контейнер,
           созданный через st.container(key="geo-header"). Через <div> из st.markdown
           это НЕ работает: незакрытый тег Streamlit закрывает сам, div схлопывается
           в пустой элемент, и колонки становятся его соседом, а не потомком. */
        .st-key-geo-header [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) { order: 3; }  /* кнопки  */
        .st-key-geo-header [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) { order: 1; }  /* заголовок */
        .st-key-geo-header [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) { order: 2; }  /* навигация */

        /* Ниже точки, где Streamlit складывает колонки в столбик, order сбрасывается -
           иначе кнопки уехали бы вниз, а нужен порядок из объявления (кнопки сверху). */
        @media (max-width: 640px) {
            .st-key-geo-header [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { order: 0 !important; }
            .user-info { text-align: left; }
        }

        /* Навигация в шапке: убираем отступ, который segmented_control держит под себя */
        .st-key-geo-header [data-testid="stElementContainer"]:has([data-testid="stSegmentedControl"]) { margin-bottom: 0; }

        /* --- Закрепление шапки при прокрутке ---
           Фактическая иерархия (снята из DevTools на 1.57):

             section[stMain]                  <- прокручивается именно он (overflow: scroll)
               div[stMainBlockContainer]
                 div[stVerticalBlock]         <- растянут по высоте контента
                   div[stElementContainer]    <- <style> с этими правилами
                   div[stLayoutWrapper]       <- height: auto, обжат по высоте шапки
                     div.st-key-geo-header    <- сама шапка

           sticky прилипает в пределах высоты РОДИТЕЛЯ. Повесить его на .st-key-geo-header
           недостаточно: её родитель stLayoutWrapper обжат ровно по ней, прилипать
           некуда - шапка уезжает вверх вместе с обёрткой. Поэтому sticky ставится на
           сам stLayoutWrapper, чей родитель stVerticalBlock растянут на всю высоту
           контента. :has() адресует именно ту обёртку, внутри которой лежит шапка.

           Фон вешается на обёртку вместе с sticky: непрозрачный фон обязателен,
           иначе контент просвечивает сквозь закреплённую шапку. Отрицательные поля
           с равной им подложкой растягивают фон на всю ширину. */
        [data-testid="stLayoutWrapper"]:has(> .st-key-geo-header) {
            position: sticky;
            top: 0;
            z-index: 999;
            background: #ffffff;
            padding: 0.6rem 1rem 0.2rem 1rem;
            margin: -0.6rem -1rem 0 -1rem;
        }

        /* Запасной вариант: stLayoutWrapper Streamlit рисует не всегда (только когда у
           блока есть своё оформление). Если обёртки не окажется, sticky ложится на сам
           блок - его родителем тогда будет растянутый stVerticalBlock, и прилипание
           сработает. Когда обёртка есть, это правило безвредно: sticky внутри уже
           закреплённого родителя ничего не меняет, а фон нужен в обоих случаях. */
        [data-testid="stVerticalBlock"] > .st-key-geo-header {
            position: sticky;
            top: 0;
            z-index: 999;
            background: #ffffff;
        }
    </style>
""", unsafe_allow_html=True)

auth = st.session_state['auth']

# Шапка: кнопки объявлены первыми (порядок при сужении), на широком экране
# переставляются вправо через CSS order - см. .st-key-geo-header выше.
# Контейнер с key= нужен именно как якорь для этого CSS.
_header = st.container(key="geo-header")
h_btns, h_title, h_nav = _header.columns([0.24, 0.30, 0.46], vertical_alignment="bottom")

with h_btns:
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

with h_title:
    st.markdown("### 🗺️ Управление поставщиками Национального геопортала")

# Навигация живёт в шапке, но в админ-панели не показывается: там её роль
# выполняет кнопка "⬅️ Назад" (см. h_btns выше)
_show_admin = st.session_state.get("show_admin", False)
nav_options = ["📁 Поставщики", "🗄️ Наборы", "📋 Проекты", "📩 Заявки", "📊 Аналитика"]
if "main_nav" not in st.session_state:
    st.session_state["main_nav"] = nav_options[0]

with h_nav:
    if not _show_admin:
        choice = st.segmented_control(
            "Навигация",
            options=nav_options,
            key="main_nav",
            label_visibility="collapsed"
        )
    else:
        choice = st.session_state["main_nav"]

st.markdown("---")

# ==========================================
# 🧭 4. РОУТИНГ И НАВИГАЦИЯ (СО СПИННЕРОМ)
# ==========================================

# Оборачиваем весь процесс построения контента в спиннер
with st.spinner("⏳ Синхронизация данных..."):
    if _show_admin:
        with Session(engine) as session:
            render_admin_panel(session)
    else:
        # Навигация отрисована выше, в шапке; здесь только диспетчеризация
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