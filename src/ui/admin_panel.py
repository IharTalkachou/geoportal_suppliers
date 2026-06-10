import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache 
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
        # 🔹 ДОБАВЛЕНО: show_in_staff в запрос
        users_df = query_db("""
            SELECT user_id, username, display_name, role, is_active, show_in_staff, last_login 
            FROM users ORDER BY user_id
        """)

        # 🔹 ДОБАВЛЕНО: Колонка в таблицу для наглядности
        st.dataframe(users_df[["username", "display_name", "role", "is_active", "show_in_staff", "last_login"]],
                     width="stretch", hide_index=True,
                     column_config={
                         "username": "Логин", "display_name": "Имя", "role": "Роль",
                         "is_active": "Активен", 
                         "show_in_staff": "Сотрудник", # ⬅️ Показываем статус
                         "last_login": "Последний вход"
                     })

        with st.expander("➕ Добавить / ✏️ Редактировать пользователя", expanded=True):
            if st.session_state.get("adm_user_deleted"):
                for k in ["adm_un_in", "adm_dn_in", "adm_role_in", "adm_act_in", "adm_staff_in", "adm_pwd_in", "adm_sel_user_prev"]:
                    st.session_state.pop(k, None)
                st.session_state.pop("adm_user_deleted", None)

            user_options = ["(Новый пользователь)"] + users_df["username"].tolist()
            sel_user = st.selectbox("Выберите пользователя:", user_options, key="adm_sel_user")
            is_editing = sel_user != "(Новый пользователь)"

            # Авто-подстановка
            if "adm_sel_user_prev" not in st.session_state or st.session_state["adm_sel_user_prev"] != sel_user:
                if is_editing:
                    curr = users_df[users_df["username"] == sel_user].iloc[0]
                    st.session_state["adm_un_in"] = curr["username"]
                    st.session_state["adm_dn_in"] = curr["display_name"] or curr["username"]
                    st.session_state["adm_role_in"] = curr["role"]
                    st.session_state["adm_act_in"] = bool(curr["is_active"])
                    st.session_state["adm_staff_in"] = bool(curr["show_in_staff"]) # ⬅️ Подстановка нового поля
                    st.session_state["adm_pwd_in"] = ""
                else:
                    st.session_state["adm_un_in"] = ""
                    st.session_state["adm_dn_in"] = ""
                    st.session_state["adm_role_in"] = "user"
                    st.session_state["adm_act_in"] = True
                    st.session_state["adm_staff_in"] = False # ⬅️ Сброс
                    st.session_state["adm_pwd_in"] = ""
                st.session_state["adm_sel_user_prev"] = sel_user

            col1, col2 = st.columns(2)
            with col1:
                st.text_input("Логин", disabled=is_editing, key="adm_un_in")
                st.text_input("Отображаемое имя", key="adm_dn_in")
            with col2:
                role_keys = list(ROLE_NAMES.keys())
                st.selectbox("Роль", role_keys, format_func=lambda x: ROLE_NAMES[x], key="adm_role_in")
                
                # Чекбоксы признаков
                c_act, c_staff = st.columns(2)
                with c_act:
                    st.checkbox("Активен", key="adm_act_in")
                with c_staff:
                    st.checkbox("В списке сотрудников", key="adm_staff_in") # ⬅️ НОВЫЙ ЧЕКБОКС

            st.text_input("Пароль" + (" (оставьте пустым, чтобы не менять)" if is_editing else ""), 
                          type="password", key="adm_pwd_in")

            col_btn, col_del = st.columns([3, 1])
            with col_btn:
                if st.button("💾 Сохранить", type="primary", key="adm_save"):
                    u = st.session_state["adm_un_in"].strip()
                    d = st.session_state["adm_dn_in"].strip()
                    r = st.session_state["adm_role_in"]
                    a = st.session_state["adm_act_in"]
                    s = st.session_state["adm_staff_in"] # ⬅️ Значение из чекбокса
                    p = st.session_state["adm_pwd_in"]

                    try:
                        if is_editing:
                            curr = users_df[users_df["username"] == u].iloc[0]
                            log_action(st.session_state["auth"]["user_id"], "UPDATE_USER", 
                                       "users", int(curr["user_id"]),
                                       old={"role": curr["role"], "active": bool(curr["is_active"]), "staff": bool(curr["show_in_staff"])},
                                       new={"role": r, "active": a, "staff": s})
                                       
                            # 🔹 ДОБАВЛЕНО: show_in_staff=:s в оба запроса UPDATE
                            if p:
                                session.execute(text("""
                                    UPDATE users SET display_name=:d, role=:r, is_active=:a, show_in_staff=:s, password_hash=:h 
                                    WHERE username=:u
                                """), {"d": d or u, "r": r, "a": a, "s": s, "h": hash_password(p), "u": u})
                            else:
                                session.execute(text("""
                                    UPDATE users SET display_name=:d, role=:r, is_active=:a, show_in_staff=:s 
                                    WHERE username=:u
                                """), {"d": d or u, "r": r, "a": a, "s": s, "u": u})
                        else:
                            if not u or not p:
                                st.error("❌ Логин и пароль обязательны")
                                st.stop()
                            
                            # 🔹 ДОБАВЛЕНО: show_in_staff (:s) в INSERT
                            session.execute(text("""
                                INSERT INTO users (username, display_name, password_hash, role, is_active, show_in_staff) 
                                VALUES (:u, :d, :h, :r, :a, :s)
                            """), {"u": u, "d": d or u, "h": hash_password(p), "r": r, "a": a, "s": s})
                            
                            new_id = session.execute(text("SELECT currval(pg_get_serial_sequence('users', 'user_id'))")).scalar()
                            log_action(st.session_state["auth"]["user_id"], "CREATE_USER", "users", int(new_id), new={"username": u, "staff": s})
                        
                        session.commit()
                        st.cache_data.clear()
                        st.success("✅ Сохранено!"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}"); session.rollback()

            with col_del:
                if is_editing and sel_user != "admin":
                    if st.button("🗑 Удалить навсегда", type="secondary", key="adm_del"):
                        try:
                            curr = users_df[users_df["username"] == sel_user].iloc[0]
                            log_action(st.session_state["auth"]["user_id"], "DELETE_USER", "users", int(curr["user_id"]), old={"username": sel_user})
                            session.execute(text("DELETE FROM users WHERE username = :u"), {"u": sel_user})
                            session.commit()
                            st.cache_data.clear()
                            st.session_state["adm_user_deleted"] = True
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка удаления: {e}"); session.rollback()

    # ==========================================
    # 2. ЖУРНАЛ ДЕЙСТВИЙ (с проверкой существования таблицы)
    # ==========================================
    with tab_audit:
  
        st.subheader("История изменений и входов")
        
        # 🔹 Кнопка принудительного сброса кэша
        if st.button("🔄 Обновить журнал", type="secondary", width="stretch", key="btn_refresh_audit"):
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
    # 3. НАСТРОЙКИ СИСТЕМЫ И НОРМАТИВОВ
    # ==========================================
    with tab_settings:
        st.subheader("⚙️ Параметры приложения и нормативы")
        
        # --- Блок А: Системные параметры (Session State) ---
        st.markdown("#### 🖥️ Системные параметры")
        col_sys1, col_sys2 = st.columns(2)
        with col_sys1:
            st.number_input("⏱ Таймаут сессии (мин)", value=st.session_state.get("admin_timeout", 30), step=5, key="adm_timeout")
        with col_sys2:
            st.write("<br>", unsafe_allow_html=True)
            st.toggle("🚧 Режим обслуживания (только для админов)", value=st.session_state.get("adm_maint", False), key="adm_maint")
        
        st.markdown("---")
        
        # --- Блок Б: Нормативы длительности (База данных) ---
        st.markdown("#### ⏳ Нормативы длительности этапов")
        st.caption("Данные используются для авторасчета плановых дат завершения при старте задачи.")

        # Загружаем текущие значения из БД
        stages_norm_df = query_db("""
            SELECT stage_id, stage_name, track_category, duration_days 
            FROM stages 
            ORDER BY track_category, stage_order
        """)

        # Редактируемая таблица
        edited_df = st.data_editor(
            stages_norm_df,
            column_config={
                "stage_id": None, # Скрываем ID
                "stage_name": st.column_config.TextColumn("Наименование этапа", disabled=True),
                "track_category": st.column_config.TextColumn("Трек", disabled=True),
                "duration_days": st.column_config.NumberColumn(
                    "Норматив (дней)",
                    min_value=0, max_value=365, step=1, format="%d дн."
                ),
            },
            hide_index=True,
            width="stretch",
            key="stages_editor"
        )

        st.write("<br>", unsafe_allow_html=True)
        
        # --- ЕДИНАЯ КНОПКА СОХРАНЕНИЯ ---
        if st.button("💾 Сохранить все настройки", type="primary", width="stretch"):
            try:
                from sqlalchemy.orm import Session
                from config.database import engine
                
                # 1. Сохраняем системные настройки в Session State
                st.session_state["admin_timeout"] = st.session_state["adm_timeout"]
                # (Примечание: adm_maint уже лежит в session_state по ключу)

                # 2. Сохраняем нормативы в Базу Данных
                with Session(engine) as sess:
                    for index, row in edited_df.iterrows():
                        # Проверяем, изменилось ли значение по сравнению с исходным
                        original_val = stages_norm_df.iloc[index]['duration_days']
                        if row['duration_days'] != original_val:
                            sess.execute(
                                text("UPDATE stages SET duration_days = :d WHERE stage_id = :id"),
                                {"d": int(row['duration_days']), "id": int(row['stage_id'])}
                            )
                    sess.commit()
                
                # 3. Очищаем кэш и уведомляем пользователя
                clear_cache()
                st.success("✅ Все изменения (системные и нормативы) успешно применены!")
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Ошибка при сохранении: {e}")