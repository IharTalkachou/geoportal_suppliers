import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime, time
import time as time_module
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_requests_tab(session, user_role="user"):
    st.subheader("📩 Управление заявками на регистрацию")
    is_readonly = (user_role == "user")
    
    choice = st.segmented_control(
        "Навигация",
        options=["➕ Новая заявка", "📋 Реестр заявок"],
        default="➕ Новая заявка",
        key="req_sub_nav_main",
        label_visibility="collapsed"
    )
    st.markdown("---")

    if choice == "➕ Новая заявка":
        if is_readonly:
            st.warning("У вас недостаточно прав для создания заявок.")
        else:
            render_registration_form(session)
    else:
        render_requests_registry(session, user_role)

def render_registration_form(session):
    st.markdown("### 📝 Оформление новой заявки")
    
    with st.container(border=True):
        # --- БЛОК 1: КТО И КОГДА ---
        col_type, col_dates = st.columns([1, 1])
        
        with col_type:
            app_type = st.radio("Вид заявителя", ["Физическое лицо", "Юридическое лицо"], horizontal=True, key="f_app_type")
            applicant_phone = st.text_input("📞 Контактный номер телефона *", placeholder="+375 (XX) XXX-XX-XX")
        
        with col_dates:
            st.write("📅 **Дата и время поступления**")
            cd1, cd2 = st.columns(2)
            with cd1: d_in = st.date_input("Число", value=datetime.now().date(), label_visibility="collapsed")
            with cd2: t_in = st.time_input("Время", value=datetime.now().time(), label_visibility="collapsed")
            # Склеиваем в один объект datetime
            created_dt = datetime.combine(d_in, t_in)

        st.divider()

        # --- БЛОК 2: ДАННЫЕ ЗАЯВИТЕЛЯ ---
        user_list = [] # Список для сбора данных пользователей
        
        if app_type == "Физическое лицо":
            st.markdown("##### 👤 Данные физического лица")
            f_name = st.text_input("ФИО заявителя полностью *")
            f_email = st.text_input("Email для уведомлений *")
            f_login = st.text_input("Желаемый логин *")
            # Для физлица создаем список из 1 пользователя автоматически
            user_list.append({"fio": f_name, "email": f_email, "login": f_login, "is_admin": False})
            
            main_applicant_name = f_name
            org_target = None
            scan_link = None
        
        else:
            st.markdown("##### 🏢 Данные организации")
            c1, c2 = st.columns(2)
            with c1:
                main_applicant_name = st.text_input("Название организации *")
                org_target = st.selectbox("Тип организации", ["Пользователь", "Поставщик"], key="f_org_type")
            with c2:
                scan_link = st.text_input("🔗 Ссылка на скан заявки", placeholder="http://...")
            
            num_accs = st.number_input("Количество учётных записей в заявке", min_value=1, max_value=20, value=1)
            
            st.markdown("---")
            st.write("📝 **Список создаваемых пользователей:**")
            for i in range(int(num_accs)):
                with st.expander(f"Пользователь №{i+1}", expanded=True):
                    u1, u2, u3 = st.columns(3)
                    with u1: ufio = st.text_input(f"ФИО *", key=f"ufio_{i}")
                    with u2: umail = st.text_input(f"Email *", key=f"umail_{i}")
                    with u3: ulog = st.text_input(f"Логин *", key=f"ulog_{i}")
                    user_list.append({"fio": ufio, "email": umail, "login": ulog, "is_admin": False})

            # Выбор админа для Поставщика
            admin_fio = None
            if org_target == "Поставщик":
                st.markdown("##### 🔑 Назначение администратора")
                valid_names = [u['fio'] for u in user_list if u['fio'].strip()]
                if valid_names:
                    admin_fio = st.selectbox("Выберите администратора из списка выше", valid_names)
                    for u in user_list:
                        if u['fio'] == admin_fio: u['is_admin'] = True

        # --- БЛОК 3: СОХРАНЕНИЕ ---
        st.divider()
        if st.button("🚀 Создать заявку", type="primary", use_container_width=True):
            # Валидация
            if not main_applicant_name or not applicant_phone:
                st.error("❌ Заполните обязательные поля (Имя и Телефон)"); st.stop()
            
            if any(not u["fio"] or not u["login"] or not u["email"] for u in user_list):
                st.error("❌ Заполните данные по всем пользователям (ФИО, Email, Логин)"); st.stop()

            try:
                # 1. Вставка заголовка (с CAST для ENUM типов)
                res = session.execute(text("""
                    INSERT INTO reg_requests (
                        created_at, applicant_type, applicant_name, applicant_phone, 
                        scan_url, org_type, status
                    ) VALUES (
                        :ca, CAST(:at AS applicant_category), :an, :ph, 
                        :su, CAST(:ot AS org_target_type), 'Новая'
                    ) RETURNING req_id
                """), {
                    "ca": created_dt, "at": app_type, "an": main_applicant_name, 
                    "ph": applicant_phone, "su": scan_link, "ot": org_target
                })
                new_id = res.scalar()

                # 2. Вставка пользователей
                for u in user_list:
                    session.execute(text("""
                        INSERT INTO reg_request_users (req_id, full_name, email, login, is_admin)
                        VALUES (:rid, :fn, :em, :lg, :adm)
                    """), {
                        "rid": new_id, "fn": u["fio"], "em": u["email"], "lg": u["login"], "adm": u["is_admin"]
                    })

                session.commit()
                clear_cache()
                log_action(st.session_state.auth["user_id"], "CREATE_REG_REQUEST", "reg_requests", int(new_id))
                
                # 🟢 ВИЗУАЛЬНОЕ ПОДТВЕРЖДЕНИЕ
                st.toast(f"Заявка №{new_id} сохранена!")
                st.success(f"🎉 Заявка №{new_id} успешно зарегистрирована в системе.")
                time_module.sleep(1)
                st.rerun()

            except Exception as e:
                st.error(f"Ошибка при сохранении: {e}")
                session.rollback()

def render_requests_registry(session, user_role):
    st.markdown("### 📋 Реестр заявок")
    
    # Сортировка: новые сверху (req_id DESC)
    reqs = query_db("""
        SELECT req_id, created_at, processed_at, applicant_type, applicant_name, status, org_type 
        FROM reg_requests ORDER BY req_id DESC
    """)
    
    if reqs.empty:
        st.info("В базе нет зарегистрированных заявок."); return

    # Подготовка данных для таблицы (красивые даты)
    df_display = reqs.copy()
    df_display['created_at'] = df_display['created_at'].dt.strftime('%d.%m.%Y %H:%M')
    
    st.dataframe(
        df_display, width="stretch", hide_index=True,
        column_config={
            "req_id": "№", "created_at": "Дата поступления", 
            "processed_at": st.column_config.DatetimeColumn("Дата обработки", format="DD.MM.YYYY HH:mm"),
            "applicant_type": "Категория", "applicant_name": "Заявитель",
            "status": "Статус", "org_type": "Тип организации"
        }
    )

    st.divider()
    sel_id = st.selectbox("🎯 Выберите заявку для просмотра и обработки:", [""] + reqs["req_id"].tolist())
    
    if sel_id:
        # Загружаем полную инфо по одной заявке
        det = query_db("SELECT * FROM reg_requests WHERE req_id = :id", {"id": int(sel_id)}).iloc[0]
        users = query_db("SELECT full_name, email, login, is_admin FROM reg_request_users WHERE req_id = :id", {"id": int(sel_id)})
        
        with st.container(border=True):
            c1, c2 = st.columns(2)
            with c1:
                # 🟢 ЧЕЛОВЕЧЕСКИЙ ФОРМАТ ДАТЫ
                created_str = det['created_at'].strftime('%d.%m.%Y %H:%M')
                st.markdown(f"#### Заявка №{sel_id} от {created_str}")
                st.write(f"**Статус:** `{det['status']}`")
                st.write(f"**Заявитель:** {det['applicant_name']}")
                st.write(f"**Телефон:** {det['applicant_phone'] or 'не указан'}")
            
            with c2:
                if det['scan_url']:
                    st.link_button("📄 Открыть скан заявки", det['scan_url'], use_container_width=True)
                else:
                    st.caption("Скан документа не прикреплен")
                
                # Поле для ввода даты обработки (если нужно обновить)
                if not det['processed_at']:
                    new_proc_date = st.date_input("Установить дату обработки", value=datetime.now().date())
                    if st.button("✅ Отметить как обработанную"):
                        session.execute(text("UPDATE reg_requests SET processed_at=:p, status='Завершена' WHERE req_id=:id"),
                                        {"p": datetime.combine(new_proc_date, datetime.now().time()), "id": int(sel_id)})
                        session.commit(); clear_cache(); st.rerun()

            st.markdown("---")
            st.write("**👤 Список пользователей по заявке:**")
            # Маскируем True/False на красивые иконки
            users['is_admin'] = users['is_admin'].map({True: "🔑 Да", False: "—"})
            st.table(users.rename(columns={"full_name": "ФИО", "email": "Email", "login": "Логин", "is_admin": "Админ"}))