import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime
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
        if is_readonly: st.warning("Недостаточно прав."); return
        render_registration_form(session)
    else:
        render_requests_registry(session, user_role)

def render_registration_form(session):
    st.markdown("### 📝 Оформление новой заявки")
    
    with st.container(border=True):
        # --- БЛОК 1: ТИП И КОНТАКТЫ ---
        col_type, col_dates = st.columns([1, 1])
        with col_type:
            app_type = st.radio("Вид заявителя", ["Физическое лицо", "Юридическое лицо"], horizontal=True, key="f_app_type")
            applicant_phone = st.text_input("📞 Контактный номер телефона *", placeholder="+375...")
        
        with col_dates:
            st.write("📅 **Дата и время поступления**")
            cd1, cd2 = st.columns(2)
            with cd1: d_in = st.date_input("Число", value=datetime.now().date(), key="req_d_widget")
            with cd2: t_in = st.time_input("Время", value=datetime.now().time(), key="req_t_widget")
            created_dt = datetime.combine(d_in, t_in)

        st.divider()

        # --- БЛОК 2: ДАННЫЕ ЗАЯВИТЕЛЯ ---
        user_list = []
        linked_supplier_id = None # Для связи с существующим поставщиком
        
        if app_type == "Физическое лицо":
            st.markdown("##### 👤 Данные физического лица")
            f_name = st.text_input("ФИО заявителя полностью *")
            f_email = st.text_input("Email для уведомлений *")
            f_login = st.text_input("Желаемый логин *")
            user_list.append({"fio": f_name, "email": f_email, "login": f_login, "is_admin": False})
            main_applicant_name = f_name
            org_target, scan_link = None, None
        
        else:
            st.markdown("##### 🏢 Данные организации")
            # 🟢 1. ТИП ОРГАНИЗАЦИИ ТЕПЕРЬ ПЕРВЫМ
            org_target = st.selectbox("Тип организации", ["Пользователь", "Поставщик"], key="f_org_type")
            
            c1, c2 = st.columns(2)
            with c1:
                # 🟢 2. ВЫБОР ИЛИ ВВОД ИМЕНИ
                if org_target == "Поставщик":
                    # Подтягиваем список существующих
                    sups_df = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
                    sup_map_local = dict(zip(sups_df["supplier_name"], sups_df["supplier_id"]))
                    selected_sup_name = st.selectbox("Выберите организацию из реестра *", sups_df["supplier_name"].tolist())
                    main_applicant_name = selected_sup_name
                    linked_supplier_id = int(sup_map_local[selected_sup_name])
                else:
                    main_applicant_name = st.text_input("Название организации *")
                    linked_supplier_id = None
            
            with c2:
                scan_link = st.text_input("🔗 Ссылка на скан заявки")
            
            num_accs = st.number_input("Количество учётных записей", min_value=1, max_value=20, value=1)
            
            st.markdown("---")
            for i in range(int(num_accs)):
                with st.expander(f"Пользователь №{i+1}", expanded=True):
                    u1, u2, u3 = st.columns(3)
                    with u1: ufio = st.text_input(f"ФИО *", key=f"ufio_{i}")
                    with u2: umail = st.text_input(f"Email *", key=f"umail_{i}")
                    with u3: ulog = st.text_input(f"Логин *", key=f"ulog_{i}")
                    user_list.append({"fio": ufio, "email": umail, "login": ulog, "is_admin": False})

            admin_fio = None
            if org_target == "Поставщик":
                st.markdown("##### 🔑 Администратор пользователей")
                valid_names = [u['fio'] for u in user_list if u['fio'].strip()]
                if valid_names:
                    admin_fio = st.selectbox("Выберите администратора", valid_names)
                    for u in user_list:
                        if u['fio'] == admin_fio: u['is_admin'] = True

        st.divider()
        if st.button("🚀 Создать заявку", type="primary", width='stretch'):
            if not main_applicant_name: st.error("Заполните имя заявителя"); st.stop()
            try:
                res = session.execute(text("""
                    INSERT INTO reg_requests (created_at, applicant_type, applicant_name, applicant_phone, scan_url, org_type, status, result_supplier_id)
                    VALUES (:ca, CAST(:at AS applicant_category), :an, :ph, :su, CAST(:ot AS org_target_type), 'Новая', :rsid) 
                    RETURNING req_id
                """), {"ca": created_dt, "at": app_type, "an": main_applicant_name, "ph": applicant_phone, "su": scan_link, "ot": org_target, "rsid": linked_supplier_id})
                new_id = res.scalar()

                for u in user_list:
                    session.execute(text("""
                        INSERT INTO reg_request_users (req_id, full_name, email, login, is_admin)
                        VALUES (:rid, :fn, :em, :lg, :adm)
                    """), {"rid": new_id, "fn": u["fio"], "em": u["email"], "lg": u["login"], "adm": u["is_admin"]})

                session.commit(); clear_cache()
                log_action(st.session_state.auth["user_id"], "CREATE_REG_REQUEST", "reg_requests", int(new_id))
                st.toast(f"Заявка №{new_id} сохранена!")
                st.success(f"🎉 Заявка №{new_id} зарегистрирована."); time_module.sleep(1); st.rerun()
            except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

def render_requests_registry(session, user_role):
    st.markdown("### 📋 Реестр заявок")
    reqs = query_db("SELECT * FROM reg_requests ORDER BY req_id DESC")
    
    if reqs.empty: 
        st.info("Заявок в базе данных пока нет.")
        return

    # Подготовка таблицы для отображения
    df_viz = reqs.copy()
    df_viz['created_at_str'] = df_viz['created_at'].dt.strftime('%d.%m.%Y %H:%M')
    
    # УМНЫЙ РАСЧЕТ ВЫСОТЫ ТАБЛИЦЫ
    # 35px на строку + 45px на заголовок. Ограничиваем от 150 до 600 пикселей.
    calc_h = (len(df_viz) * 35) + 45
    final_h = min(600, max(150, calc_h))

    # 🟢 3. РЕЕСТР В ЭКСПАНДЕРЕ
    with st.expander("🔍 Показать/скрыть таблицу реестра", expanded=False):
        st.dataframe(
            df_viz[["req_id", "created_at_str", "applicant_name", "applicant_type", "status", "org_type"]], 
            width="stretch", 
            hide_index=True,
            height=final_h, # Применяем расчетную высоту
            column_config={
                "req_id": "№", 
                "created_at_str": "Дата поступления", 
                "applicant_name": "Заявитель", 
                "applicant_type": "Категория",
                "status": "Статус", 
                "org_type": "Тип организации"
            }
        )

    st.divider()
    
    # Формируем список для выбора
    req_options = {
        f"№{r['req_id']} | {r['created_at'].strftime('%d.%m.%Y %H:%M')} | {r['applicant_name']}": r['req_id'] 
        for _, r in reqs.iterrows()
    }
    
    sel_label = st.selectbox("🎯 Выберите заявку для просмотра и обработки:", [""] + list(req_options.keys()))
    
    if sel_label:
        sel_id = req_options[sel_label]
        # Берем данные конкретной заявки
        det = reqs[reqs["req_id"] == sel_id].iloc[0]
        users = query_db("SELECT * FROM reg_request_users WHERE req_id = :id", {"id": int(sel_id)})
        
        with st.container(border=True):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"#### Заявка №{sel_id}")
                st.write(f"🚦 **Статус:** `{det['status']}`")
                st.write(f"👤 **Заявитель:** {det['applicant_name']} ({det['applicant_type']})")
                st.write(f"📞 **Телефон:** {det['applicant_phone'] or 'не указан'}")
                
                # 🟢 ИСПРАВЛЕНИЕ ОШИБКИ NaN: Проверяем наличие ID перед кнопкой перехода
                if pd.notna(det['result_supplier_id']):
                    def go_to_sup_cb(sid):
                        st.session_state["main_nav"] = "📁 Поставщики"
                        st.session_state["filter_supplier_id"] = int(sid)

                    st.button("🔎 Перейти к карточке поставщика", 
                              on_click=go_to_sup_cb, 
                              args=(det['result_supplier_id'],), 
                              type="secondary",
                              width='stretch')
            
            with c2:
                # 🟢 ИСПРАВЛЕНИЕ: Индикация скана
                if det['applicant_type'] == "Юридическое лицо":
                    if det['scan_url'] and str(det['scan_url']).strip() != "":
                        st.link_button("📄 Открыть скан заявки", det['scan_url'], width='stretch')
                    else:
                        st.warning("⚠️ Заявка не приложена (ссылка отсутствует)")
                
                # Механизм повышения для организаций-пользователей
                if det['org_type'] == "Пользователь" and pd.isna(det['result_supplier_id']):
                    st.info("💡 Эту организацию можно внести в реестр Поставщиков")
                    if st.button("🏗 Создать запись Поставщика", type="primary", width='stretch'):
                        try:
                            new_sup = session.execute(text("""
                                INSERT INTO suppliers (supplier_name, supplier_phone, supplier_notes) 
                                VALUES (:n, :p, :notes) RETURNING supplier_id
                            """), {"n": det['applicant_name'], "p": det['applicant_phone'], "notes": f"Создан на базе заявки №{sel_id}"}).scalar()
                            
                            session.execute(text("UPDATE reg_requests SET result_supplier_id = :sid WHERE req_id = :rid"),
                                            {"sid": int(new_sup), "rid": int(sel_id)})
                            
                            session.commit(); clear_cache()
                            log_action(st.session_state.auth["user_id"], "PROMOTE_REQUEST_TO_SUPPLIER", "suppliers", int(new_sup))
                            st.success("Организация добавлена в реестр!"); st.rerun()
                        except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

                # Блок завершения обработки
                if not det['processed_at'] or pd.isna(det['processed_at']):
                    st.write("🛠 **Завершение обработки**")
                    cp1, cp2 = st.columns(2)
                    with cp1: d_proc = st.date_input("Дата", value=datetime.now().date(), key=f"dp_{sel_id}")
                    with cp2: t_proc = st.time_input("Время", value=datetime.now().time(), key=f"tp_{sel_id}")
                    if st.button("✅ Завершить заявку", width='stretch', key=f"btn_finish_{sel_id}"):
                        proc_dt = datetime.combine(d_proc, t_proc)
                        session.execute(text("UPDATE reg_requests SET processed_at=:p, status='Завершена' WHERE req_id=:id"),
                                        {"p": proc_dt, "id": int(sel_id)})
                        session.commit(); clear_cache(); st.toast("Заявка завершена"); st.rerun()
                else:
                    st.success(f"✅ Обработана: {det['processed_at'].strftime('%d.%m.%Y %H:%M')}")

            st.markdown("---")
            st.write("**👤 Список пользователей по заявке:**")
            # Безопасное маскирование админа
            users_disp = users.copy()
            users_disp['is_admin'] = users_disp['is_admin'].apply(lambda x: "🔑 Да" if x else "—")
            st.table(users_disp[["full_name", "email", "login", "is_admin"]].rename(columns={"full_name": "ФИО", "is_admin": "Админ"}))