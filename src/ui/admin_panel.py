import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db
from config.auth import hash_password, ROLE_NAMES, require_role, log_action
from datetime import datetime, timedelta

def render_admin_panel(session):
    require_role("admin")
    st.header("⚙️ Панель администратора")

    tab_users, tab_audit, tab_settings = st.tabs(["👥 Пользователи", "📜 Журнал действий", "⚙️ Настройки"])

    # ==========================================
    # 1. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ 
    # ==========================================
    with tab_users:
        st.subheader("Учётные записи")
        users_df = query_db("""
            SELECT user_id, username, display_name, role, is_active, last_login 
            FROM users ORDER BY user_id
        """)

        st.dataframe(users_df[["username", "display_name", "role", "is_active", "last_login"]],
                     width="stretch", hide_index=True,
                     column_config={
                         "username": "Логин", "display_name": "Имя", "role": "Роль",
                         "is_active": "Активен", "last_login": "Последний вход"
                     })

        with st.expander("➕ Добавить / ✏️ Редактировать пользователя", expanded=True):
            # 🔹 FIX: Сброс состояния формы ПОСЛЕ удаления, но ДО рендера виджетов
            if st.session_state.get("adm_user_deleted"):
                for k in ["adm_un_in", "adm_dn_in", "adm_role_in", "adm_act_in", "adm_pwd_in", "adm_sel_user_prev"]:
                    st.session_state.pop(k, None)
                st.session_state.pop("adm_user_deleted", None)

            user_options = ["(Новый пользователь)"] + users_df["username"].tolist()
            sel_user = st.selectbox("Выберите пользователя:", user_options, key="adm_sel_user")
            is_editing = sel_user != "(Новый пользователь)"

            # Авто-подстановка ТОЛЬКО при смене выбора
            if "adm_sel_user_prev" not in st.session_state or st.session_state["adm_sel_user_prev"] != sel_user:
                if is_editing:
                    curr = users_df[users_df["username"] == sel_user].iloc[0]
                    st.session_state["adm_un_in"] = curr["username"]
                    st.session_state["adm_dn_in"] = curr["display_name"] or curr["username"]
                    st.session_state["adm_role_in"] = curr["role"]
                    st.session_state["adm_act_in"] = bool(curr["is_active"])
                    st.session_state["adm_pwd_in"] = ""
                else:
                    st.session_state["adm_un_in"] = ""
                    st.session_state["adm_dn_in"] = ""
                    st.session_state["adm_role_in"] = "user"
                    st.session_state["adm_act_in"] = True
                    st.session_state["adm_pwd_in"] = ""
                st.session_state["adm_sel_user_prev"] = sel_user

            col1, col2 = st.columns(2)
            with col1:
                st.text_input("Логин", value=st.session_state.get("adm_un_in", ""), disabled=is_editing, key="adm_un_in")
                st.text_input("Отображаемое имя", value=st.session_state.get("adm_dn_in", ""), key="adm_dn_in")
            with col2:
                role_keys = list(ROLE_NAMES.keys())
                curr_role = st.session_state.get("adm_role_in", "user")
                safe_idx = role_keys.index(curr_role) if curr_role in role_keys else 0
                st.selectbox("Роль", role_keys, format_func=lambda x: ROLE_NAMES[x], key="adm_role_in")
                st.checkbox("Активен", key="adm_act_in")

            st.text_input("Пароль" + (" (оставьте пустым, чтобы не менять)" if is_editing else ""), 
                          type="password", value=st.session_state.get("adm_pwd_in", ""), key="adm_pwd_in")

            col_btn, col_del = st.columns([3, 1])
            with col_btn:
                if st.button("💾 Сохранить", type="primary", key="adm_save"):
                    u = st.session_state["adm_un_in"].strip()
                    d = st.session_state["adm_dn_in"].strip()
                    r = st.session_state["adm_role_in"]
                    a = st.session_state["adm_act_in"]
                    p = st.session_state["adm_pwd_in"]

                    try:
                        if is_editing:
                            curr = users_df[users_df["username"] == u].iloc[0]
                            # 📝 Лог изменения
                            log_action(st.session_state["auth"]["user_id"], "UPDATE_USER", 
                                       "users", int(curr["user_id"]),
                                       old={"role": curr["role"], "active": bool(curr["is_active"])},
                                       new={"role": r, "active": a})
                                       
                            if p:
                                session.execute(text("UPDATE users SET display_name=:d, role=:r, is_active=:a, password_hash=:h WHERE username=:u"),
                                                {"d": d or u, "r": r, "a": a, "h": hash_password(p), "u": u})
                            else:
                                session.execute(text("UPDATE users SET display_name=:d, role=:r, is_active=:a WHERE username=:u"),
                                                {"d": d or u, "r": r, "a": a, "u": u})
                        else:
                            if not u or not p:
                                st.error("❌ Логин и пароль обязательны для создания")
                                st.stop()
                            
                            session.execute(text("INSERT INTO users (username, display_name, password_hash, role, is_active) VALUES (:u, :d, :h, :r, :a)"),
                                            {"u": u, "d": d or u, "h": hash_password(p), "r": r, "a": a})
                            
                            # 📝 Лог создания
                            new_id = session.execute(text("SELECT currval(pg_get_serial_sequence('users', 'user_id'))")).scalar()
                            log_action(st.session_state["auth"]["user_id"], "CREATE_USER", "users", int(new_id), new={"username": u, "role": r})
                        session.commit()
                        st.cache_data.clear()
                        st.success("✅ Пользователь сохранён!"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}"); session.rollback()

            with col_del:
                if is_editing and sel_user != "admin":
                    st.warning("⚠️ Удаление пользователя нельзя отменить.")
                    if st.button("🗑 Удалить навсегда", type="secondary", key="adm_del"):
                        try:
                            curr = users_df[users_df["username"] == sel_user].iloc[0]
                            # 📝 Лог удаления
                            log_action(st.session_state["auth"]["user_id"], "DELETE_USER", "users", int(curr["user_id"]), old={"username": sel_user})
                            
                            session.execute(text("DELETE FROM users WHERE username = :u"), {"u": sel_user})
                            session.commit()
                            st.cache_data.clear()
                            st.session_state["adm_user_deleted"] = True
                            st.success("🗑 Пользователь удалён"); st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка удаления: {e}"); session.rollback()

    # ==========================================
    # 2. ЖУРНАЛ ДЕЙСТВИЙ (с проверкой существования таблицы)
    # ==========================================
    with tab_audit:
  
        st.subheader("История изменений и входов")
        
        # 🔹 Кнопка принудительного сброса кэша
        if st.button("🔄 Обновить журнал", type="secondary", width="stretch", key="btn_refresh_audit"):
            from config.cache import clear_cache
            clear_cache()
            st.rerun()

        c1, c2, c3 = st.columns(3)
        with c1:
            # Запрос действий (без кэширования проблем не вызовет)
            acts_df = query_db("SELECT DISTINCT action FROM audit_log ORDER BY action")
            acts = acts_df["action"].tolist() if not acts_df.empty else []
            sel_act = st.selectbox("Действие", ["Все"] + acts, key="adm_audit_act")
        with c2:
            d_start = st.date_input("С", value=datetime.now().date() - timedelta(days=7), key="adm_audit_ds")
        with c3:
            # +1 день, чтобы захватить ВЕСЬ сегодня до 23:59:59
            d_end = st.date_input("По", value=datetime.now().date() + timedelta(days=1), key="adm_audit_de")

        # 🔹 Используем приведение к DATE для точного совпадения независимо от часового пояса
        query = """
            SELECT l.created_at as "Дата", u.display_name as "Пользователь", l.action as "Действие", 
                   l.target_table as "Таблица", l.ip_address as "IP"
            FROM audit_log l
            LEFT JOIN users u ON l.user_id = u.user_id
            WHERE l.created_at::date BETWEEN :ds AND :de
        """
        params = {"ds": d_start, "de": d_end}
        if sel_act != "Все":
            query += " AND l.action = :act"
            params["act"] = sel_act
        query += " ORDER BY l.created_at DESC LIMIT 500"

        log_df = query_db(query, params)
        
        if log_df.empty:
            st.info("📭 Записей за выбранный период не найдено. Нажмите `🔄 Обновить журнал` или измените даты.")
        else:
            st.dataframe(log_df, width="stretch", hide_index=True)
            st.download_button("📥 Экспорт в CSV", data=log_df.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"audit_log_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

    # ==========================================
    # 3. НАСТРОЙКИ СИСТЕМЫ (без изменений)
    # ==========================================
    with tab_settings:
        st.subheader("Параметры приложения")
        st.info("💡 Настройки сохраняются в сессии. Для персистентности подключите таблицу `app_settings`.")
        
        st.number_input("⏱ Таймаут сессии (мин)", value=30, step=5, key="adm_timeout")
        st.toggle("🚧 Режим обслуживания (только для админов)", value=False, key="adm_maint")
        
        if st.button("💾 Применить настройки", type="primary"):
            st.session_state["admin_timeout"] = st.session_state["adm_timeout"]
            st.success("✅ Настройки применены (актуальны до перезапуска сервера)")