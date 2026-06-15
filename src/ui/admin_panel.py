import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache 
from config.auth import hash_password, ROLE_NAMES, require_role, log_action
from config.settings_handler import load_settings, save_settings
from datetime import datetime, timedelta

def render_admin_panel(session):
    require_role("admin")
    st.header("⚙️ Панель администратора")

    # Четыре основных раздела управления
    tab_users, tab_audit, tab_settings, tab_lifecycle = st.tabs([
        "👥 Пользователи", "📜 Журнал действий", "⚙️ Настройки", "🚀 Жизненный цикл"
    ])

    with tab_users:
        _render_users_management(session)

    with tab_audit:
        _render_audit_log_management(session)

    with tab_settings:
        _render_system_settings(session)

    with tab_lifecycle:
        _render_lifecycle_management(session)

# ==========================================
# 1. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ
# ==========================================
def _render_users_management(session):
    st.subheader("Учётные записи")
    users_df = query_db("""
        SELECT user_id, username, display_name, role, is_active, show_in_staff, last_login 
        FROM users ORDER BY user_id
    """)

    st.dataframe(users_df[["username", "display_name", "role", "is_active", "show_in_staff", "last_login"]],
                 width="stretch", hide_index=True,
                 column_config={
                     "username": "Логин", "display_name": "Имя", "role": "Роль",
                     "is_active": "Активен", "show_in_staff": "Сотрудник",
                     "last_login": st.column_config.DatetimeColumn("Последний вход", format="DD.MM.YYYY HH:mm")
                 })

    with st.expander("➕ Добавить / ✏️ Редактировать пользователя", expanded=True):
        if st.session_state.get("adm_user_deleted"):
            for k in ["adm_un_in", "adm_dn_in", "adm_role_in", "adm_act_in", "adm_staff_in", "adm_pwd_in", "adm_sel_user_prev"]:
                st.session_state.pop(k, None)
            st.session_state.pop("adm_user_deleted", None)

        user_options = ["(Новый пользователь)"] + users_df["username"].tolist()
        sel_user = st.selectbox("Выберите пользователя:", user_options, key="adm_sel_user")
        is_editing = sel_user != "(Новый пользователь)"

        if st.session_state.get("adm_sel_user_prev") != sel_user:
            if is_editing:
                curr = users_df[users_df["username"] == sel_user].iloc[0]
                st.session_state["adm_un_in"] = curr["username"]
                st.session_state["adm_dn_in"] = curr["display_name"] or curr["username"]
                st.session_state["adm_role_in"] = curr["role"]
                st.session_state["adm_act_in"] = bool(curr["is_active"])
                st.session_state["adm_staff_in"] = bool(curr["show_in_staff"])
                st.session_state["adm_pwd_in"] = ""
            else:
                st.session_state["adm_un_in"], st.session_state["adm_dn_in"] = "", ""
                st.session_state["adm_role_in"], st.session_state["adm_pwd_in"] = "user", ""
                st.session_state["adm_act_in"], st.session_state["adm_staff_in"] = True, False
            st.session_state["adm_sel_user_prev"] = sel_user

        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Логин", disabled=is_editing, key="adm_un_in")
            st.text_input("Отображаемое имя", key="adm_dn_in")
        with col2:
            st.selectbox("Роль", list(ROLE_NAMES.keys()), format_func=lambda x: ROLE_NAMES[x], key="adm_role_in")
            c_act, c_staff = st.columns(2)
            with c_act: st.checkbox("Активен", key="adm_act_in")
            with c_staff: st.checkbox("В списке сотрудников", key="adm_staff_in")

        st.text_input("Пароль" + (" (пусто = не менять)" if is_editing else ""), type="password", key="adm_pwd_in")

        col_btn, col_del = st.columns([3, 1])
        with col_btn:
            if st.button("💾 Сохранить пользователя", type="primary", key="adm_save"):
                u, d, r, a, s, p = st.session_state["adm_un_in"].strip(), st.session_state["adm_dn_in"].strip(), \
                                   st.session_state["adm_role_in"], st.session_state["adm_act_in"], \
                                   st.session_state["adm_staff_in"], st.session_state["adm_pwd_in"]
                try:
                    if is_editing:
                        curr = users_df[users_df["username"] == u].iloc[0]
                        log_action(st.session_state["auth"]["user_id"], "UPDATE_USER", "users", int(curr["user_id"]),
                                   old={"role": curr["role"], "active": bool(curr["is_active"])}, new={"role": r, "active": a})
                        if p:
                            session.execute(text("UPDATE users SET display_name=:d, role=:r, is_active=:a, show_in_staff=:s, password_hash=:h WHERE username=:u"),
                                            {"d": d or u, "r": r, "a": a, "s": s, "h": hash_password(p), "u": u})
                        else:
                            session.execute(text("UPDATE users SET display_name=:d, role=:r, is_active=:a, show_in_staff=:s WHERE username=:u"),
                                            {"d": d or u, "r": r, "a": a, "s": s, "u": u})
                    else:
                        if not u or not p: st.error("❌ Логин и пароль обязательны"); st.stop()
                        session.execute(text("INSERT INTO users (username, display_name, password_hash, role, is_active, show_in_staff) VALUES (:u, :d, :h, :r, :a, :s)"),
                                        {"u": u, "d": d or u, "h": hash_password(p), "r": r, "a": a, "s": s})
                        new_id = session.execute(text("SELECT currval(pg_get_serial_sequence('users', 'user_id'))")).scalar()
                        log_action(st.session_state["auth"]["user_id"], "CREATE_USER", "users", int(new_id), new={"username": u})
                    session.commit(); clear_cache(); st.success("✅ Сохранено!"); st.rerun()
                except Exception as e: st.error(f"❌ Ошибка БД: {e}"); session.rollback()

        with col_del:
            if is_editing and sel_user != "admin":
                if st.button("🗑 Удалить аккаунт", type="secondary", key="adm_del"):
                    try:
                        curr = users_df[users_df["username"] == sel_user].iloc[0]
                        log_action(st.session_state["auth"]["user_id"], "DELETE_USER", "users", int(curr["user_id"]), old={"username": sel_user})
                        session.execute(text("DELETE FROM users WHERE username = :u"), {"u": sel_user})
                        session.commit(); clear_cache(); st.session_state["adm_user_deleted"] = True; st.rerun()
                    except Exception as e: st.error(f"❌ Ошибка удаления: {e}"); session.rollback()

# ==========================================
# 2. ЖУРНАЛ ДЕЙСТВИЙ
# ==========================================
def _render_audit_log_management(session):
    st.subheader("📜 Журнал действий")
    
    with st.expander("🗑 Очистка журнала", expanded=False):
        c_clean1, c_clean2 = st.columns([2, 1])
        with c_clean1:
            days_to_keep = st.slider("Удалить записи старше (дней):", 7, 365, 30)
        with c_clean2:
            st.write("<br>", unsafe_allow_html=True)
            if st.button("🧹 Выполнить очистку", use_container_width=True):
                try:
                    # Выполняем SQL напрямую для надежности
                    cutoff = datetime.now() - timedelta(days=days_to_keep)
                    res = session.execute(text("DELETE FROM audit_log WHERE created_at < :c"), {"c": cutoff})
                    session.commit()
                    log_action(st.session_state["auth"]["user_id"], "CLEANUP_LOGS", "audit_log", None, new={"days_kept": days_to_keep})
                    st.success(f"🗑 Удалено записей: {res.rowcount}")
                    st.rerun()
                except Exception as e: st.error(f"Ошибка: {e}")

    if st.button("🔄 Обновить таблицу", type="secondary", width="stretch"):
        clear_cache(); st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1:
        acts_df = query_db("SELECT DISTINCT action FROM audit_log ORDER BY action")
        sel_act = st.selectbox("Действие", ["Все"] + (acts_df["action"].tolist() if not acts_df.empty else []), key="adm_audit_act")
    with c2: d_start = st.date_input("С", value=datetime.now().date() - timedelta(days=7))
    with c3: d_end = st.date_input("По", value=datetime.now().date() + timedelta(days=1))

    query = """
        SELECT l.created_at as "Дата", u.display_name as "Пользователь", l.action as "Действие", 
               l.target_table as "Таблица", l.ip_address as "IP"
        FROM audit_log l LEFT JOIN users u ON l.user_id = u.user_id
        WHERE l.created_at::date BETWEEN :ds AND :de
    """
    params = {"ds": d_start, "de": d_end}
    if sel_act != "Все":
        query += " AND l.action = :act"
        params["act"] = sel_act
    
    log_df = query_db(query + " ORDER BY l.created_at DESC LIMIT 500", params)
    if not log_df.empty:
        st.dataframe(log_df, width="stretch", hide_index=True)
    else: st.info("Записей не найдено.")

# ==========================================
# 3. СИСТЕМНЫЕ НАСТРОЙКИ
# ==========================================
def _render_system_settings(session):
    st.subheader("⚙️ Параметры приложения")
    current_cfg = load_settings()

    col_sys1, col_sys2 = st.columns(2)
    with col_sys1:
        new_timeout = st.number_input("⏱ Таймаут сессии (мин)", value=current_cfg.get("session_timeout_minutes", 30), step=5)
    with col_sys2:
        st.write("<br>", unsafe_allow_html=True)
        new_warn = st.toggle("📢 Показать плашку предупреждения", value=current_cfg.get("maintenance_warning", False))
    
    new_warn_msg = st.text_area("Текст предупреждения", value=current_cfg.get("maintenance_message", ""), height=68)
    
    st.divider()
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        new_maint = st.toggle("🚨 ВКЛЮЧИТЬ РЕЖИМ ОБСЛУЖИВАНИЯ", value=current_cfg.get("maintenance_mode", False))
    with col_m2:
        new_lock_msg = st.text_input("Текст при блокировке", value=current_cfg.get("lockout_message", "Техработы"))

    if st.button("💾 Сохранить системные настройки", type="primary", use_container_width=True):
        updated = {
            "session_timeout_minutes": new_timeout, "maintenance_mode": new_maint,
            "maintenance_warning": new_warn, "maintenance_message": new_warn_msg,
            "lockout_message": new_lock_msg
        }
        if save_settings(updated):
            st.success("✅ Настройки сохранены!"); clear_cache(); st.rerun()

# ==========================================
# 4. ЖИЗНЕННЫЙ ЦИКЛ (CRUD ЭТАПОВ)
# ==========================================
def _render_lifecycle_management(session):
    st.subheader("🚀 Конструктор бизнес-процессов")
    
    # Загружаем текущую структуру
    stages_df = query_db("SELECT * FROM stages ORDER BY track_category, stage_order")
    
    # Выбор трека
    tracks = sorted(stages_df['track_category'].unique().tolist()) if not stages_df.empty else []
    sel_track = st.selectbox("Выберите трек:", ["(Создать новый трек)"] + tracks, key="lc_sel_track")
    
    if sel_track == "(Создать новый трек)":
        current_track = st.text_input("Название нового трека:", placeholder="Пример: 3. Техподдержка")
        track_stages = pd.DataFrame()
    else:
        current_track = sel_track
        track_stages = stages_df[stages_df['track_category'] == current_track].copy()

    if not current_track:
        st.info("Выберите или создайте трек для управления этапами.")
        return

    # А. РЕДАКТИРОВАНИЕ СУЩЕСТВУЮЩИХ
    if not track_stages.empty:
        st.markdown(f"#### Редактирование этапов трека")
        edited_df = st.data_editor(
            track_stages,
            key=f"ed_st_{current_track}",
            hide_index=True,
            column_order=["stage_order", "stage_name", "stage_code", "duration_days", "stage_type", "stage_color"],
            column_config={
                "stage_id": None, "track_category": None,
                "stage_order": st.column_config.NumberColumn("№", width="small"),
                "stage_name": st.column_config.TextColumn("Наименование", width="large"),
                "stage_code": st.column_config.TextColumn("Код (для логики)", width="medium"),
                "duration_days": st.column_config.NumberColumn("Норматив", width="small"),
                "stage_type": st.column_config.SelectboxColumn("Тип", options=["Задача", "Веха"]),
                "stage_color": st.column_config.TextColumn("Цвет")
            },
            use_container_width=True
        )

        if st.button("💾 Применить изменения в списке", key="btn_save_stages"):
            try:
                for _, row in edited_df.iterrows():
                    session.execute(text("""
                        UPDATE stages SET stage_name=:n, stage_order=:o, duration_days=:d, 
                        stage_type=:t, stage_color=:c, stage_code=:code WHERE stage_id=:id
                    """), {"n": row['stage_name'], "o": int(row['stage_order']), "d": int(row['duration_days']), 
                           "t": row['stage_type'], "c": row['stage_color'], "code": row['stage_code'], "id": int(row['stage_id'])})
                session.commit(); clear_cache(); st.success("Данные обновлены!"); st.rerun()
            except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

    # Б. ДОБАВЛЕНИЕ НОВОГО
    with st.expander("➕ Добавить новый этап"):
        with st.form("new_stage_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_name = st.text_input("Название этапа *")
                n_order = st.number_input("Порядок", min_value=1, value=len(track_stages)+1)
                n_code = st.text_input("Код (ЛАТИННИЦА)", help="Напр. CONTRACT_WAIT")
            with c2:
                n_type = st.selectbox("Тип", ["Задача", "Веха"])
                n_days = st.number_input("Норматив (дней)", min_value=0, value=7)
                n_color = st.color_picker("Цвет", value="#3498DB")
            
            if st.form_submit_button("🚀 Создать"):
                if n_name:
                    try:
                        session.execute(text("""
                            INSERT INTO stages (stage_name, stage_order, duration_days, track_category, stage_type, stage_color, stage_code)
                            VALUES (:n, :o, :d, :t, :st, :c, :code)
                        """), {"n": n_name, "o": n_order, "d": n_days, "t": current_track, "st": n_type, "c": n_color, "code": n_code})
                        session.commit(); clear_cache(); st.success("Добавлено!"); st.rerun()
                    except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()
                else: st.error("Укажите название")

    # В. УДАЛЕНИЕ
    if not track_stages.empty:
        with st.expander("🗑 Удаление этапа"):
            to_del = st.selectbox("Выберите этап для удаления:", track_stages['stage_name'].tolist())
            if st.button("❌ Удалить безвозвратно", type="secondary"):
                sid = int(track_stages[track_stages['stage_name'] == to_del]['stage_id'].iloc[0])
                # Проверка использования в проектах
                in_use = session.execute(text("SELECT 1 FROM project_stages WHERE stage_id=:id UNION SELECT 1 FROM item_stages WHERE stage_id=:id"), {"id": sid}).scalar()
                if in_use: st.error("❌ Нельзя удалить: этап используется в проектах!")
                else:
                    session.execute(text("DELETE FROM stages WHERE stage_id=:id"), {"id": sid})
                    session.commit(); clear_cache(); st.success("Удалено!"); st.rerun()