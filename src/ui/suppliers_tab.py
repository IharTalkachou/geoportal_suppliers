import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date
from config.cache import query_db, clear_cache
from config.auth import log_action

# 🔤 Маппинг для отображения
RU_LABELS = {
    "supplier_name": "Наименование", "supplier_address": "Адрес",
    "supplier_email": "Email", "supplier_phone": "Телефон",
    "supplier_website": "Сайт", "supplier_manager": "Руководитель",
    "supplier_notes": "Примечание",
    "is_mandatory": "Поставщик ОПНД"
}

def render_suppliers_tab(session, user_role="user"):
    st.subheader("📁 Реестр поставщиков и опросные листы")
    is_readonly = (user_role == "user")
    
    # ==========================================
    # 🏢 ГЛОБАЛЬНЫЙ ВЫБОР ПОСТАВЩИКА
    # ==========================================
    all_suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(all_suppliers["supplier_name"], all_suppliers["supplier_id"]))
    
    # Функция сброса режима редактирования при смене поставщика
    def reset_edit_mode():
        st.session_state["sup_edit_mode"] = False

    # Привязываем коллбэк к селектору
    col_sel, col_add = st.columns([3, 1])
    with col_sel:
        selected_sup_name = st.selectbox(
            "🏢 Выберите поставщика", 
            [""] + list(sup_map.keys()), 
            key="sup_main_selector",
            on_change=reset_edit_mode  # <-- Сброс при смене
        )
    
    selected_sup_id = sup_map.get(selected_sup_name)

    if not selected_sup_id:
        st.info("👈 Выберите поставщика в списке или добавьте нового в блоке ниже.")
        # Блок добавления нового (только если никто не выбран)
        if not is_readonly:
            with st.expander("➕ Добавить нового поставщика в базу"):
                render_supplier_form(session)
        return

    # ==========================================
    # 📑 ТАБЫ ДЛЯ ВЫБРАННОГО ПОСТАВЩИКА
    # ==========================================
    st.markdown(f"## {selected_sup_name}")
    tab_card, tab_cont, tab_ds, tab_survey = st.tabs([
        "🏠 Карточка", "👤 Контакты", "📦 Наборы данных", "📝 Опросники"
    ])

    # --- ТАБ 1: КАРТОЧКА ---
    with tab_card:
        sup_data = query_db("SELECT * FROM suppliers WHERE supplier_id = :sid", {"sid": selected_sup_id}).iloc[0]
        
        # индикатор обязательности
        if sup_data.get('is_mandatory'):
            st.warning("⭐ **Поставщик ОНПД**")
        
        col_info, col_edit = st.columns([2, 1])
        
        # Управление режимом редактирования через единый ключ
        if "sup_edit_mode" not in st.session_state:
            st.session_state["sup_edit_mode"] = False
                
        with col_info:
            for col, label in RU_LABELS.items():
                if col in ["supplier_id", "supplier_name", "is_mandatory"]: 
                    continue
                
                if pd.notna(sup_data.get(col)) and str(sup_data[col]).strip() != "":
                    st.write(f"**{label}:** {sup_data[col]}")
        
        with col_edit:
            if not is_readonly:
                if st.button("✏️ Редактировать реквизиты", width="stretch"):
                    st.session_state["sup_edit_mode"] = not st.session_state["sup_edit_mode"]
        
        # Показываем форму только если флаг True
        if st.session_state["sup_edit_mode"]:
            with st.expander("📝 Форма редактирования", expanded=True):
                render_supplier_form(session, sup_data)
                # Кнопка отмены внутри формы (опционально)
                if st.button("❌ Отменить редактирование"):
                    st.session_state["sup_edit_mode"] = False
                    st.rerun()

    # --- ТАБ 2: КОНТАКТЫ ---
    with tab_cont:
        render_contacts_manager(session, selected_sup_id, is_readonly)

    # --- ТАБ 3: НАБОРЫ ДАННЫХ (Из проектов) ---
    with tab_ds:
        st.markdown("#### 📚 Наборы и виды сведений в проектах поставщика")
        
        # 1. Получаем текущие данные для таблицы и проверки связей
        items_df = query_db("""
            SELECT 
                pi.item_id, p.project_name, p.project_id,
                d.dataset_name, d.dataset_id,
                i.info_name, i.info_id,
                c.full_name as tech_contact,
                pi.provision_right
            FROM project_items pi
            JOIN projects p ON pi.project_id = p.project_id
            JOIN datasets d ON pi.dataset_id = d.dataset_id
            JOIN info_types i ON pi.info_id = i.info_id
            LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
            WHERE p.supplier_id = :sid
            ORDER BY p.project_name, d.dataset_name
        """, {"sid": selected_sup_id})
        
        if not items_df.empty:
            st.dataframe(items_df[["project_name", "dataset_name", "info_name", "tech_contact", "provision_right"]], 
                         width="stretch", hide_index=True,
                         column_config={"project_name": "Проект", "dataset_name": "Набор", "info_name": "Вид сведений", 
                                        "tech_contact": "Тех. контакт", "provision_right": "Право предоставления"})
        else:
            st.info("📭 Пока нет привязанных наборов.")

        if not is_readonly:
            with st.expander("➕ Добавить / 🗑 Удалить связь с набором"):
                # --- УДАЛЕНИЕ ---
                if not items_df.empty:
                    st.markdown("##### 🗑 Удаление связи")
                    to_delete = st.selectbox("Выберите связь для удаления", [""] + [f"{r['project_name']} | {r['dataset_name']} | {r['info_name']}" for _, r in items_df.iterrows()], key="ds_del_sel")
                    if to_delete:
                        # Ищем ID выбранной строки
                        idx = [f"{r['project_name']} | {r['dataset_name']} | {r['info_name']}" for _, r in items_df.iterrows()].index(to_delete)
                        item_to_del = items_df.iloc[idx]
                        
                        if st.button("❌ Удалить связь", type="secondary"):
                            # Проверка на наличие этапов технологии
                            has_stages = query_db("SELECT 1 FROM item_stages WHERE item_id = :id", {"id": int(item_to_del['item_id'])})
                            # Проверка на наличие опросников
                            has_surveys = query_db("SELECT 1 FROM surveys WHERE supplier_id = :sid AND info_type_id = :iid", 
                                                 {"sid": selected_sup_id, "iid": int(item_to_del['info_id'])})
                            
                            if not has_stages.empty or not has_surveys.empty:
                                st.error("❌ Нельзя удалить: по этому набору уже заведены этапы технологии или опросники!")
                            else:
                                try:
                                    session.execute(text("DELETE FROM project_items WHERE item_id = :id"), {"id": int(item_to_del['item_id'])})
                                    session.commit(); clear_cache(); st.success("Связь удалена"); st.rerun()
                                except Exception as e:
                                    st.error(f"Ошибка: {e}"); session.rollback()
                    st.divider()

                # --- ДОБАВЛЕНИЕ (Новая логика) ---
                st.markdown("##### ➕ Новая связь")
                
                # 1. ВЫБОР ПРОЕКТА
                projs = query_db("SELECT project_id, project_name FROM projects WHERE supplier_id = :sid", {"sid": selected_sup_id})
                proj_opt = ["(Новый проект)"] + projs["project_name"].tolist()
                sel_p = st.selectbox("Проект поставщика", proj_opt, key="ds_proj_sel")
                
                new_p_name = ""
                if sel_p == "(Новый проект)":
                    new_p_name = st.text_input("Название нового проекта *", key="ds_new_p_name")
                
                # 2. ВЫБОР НАБОРА (Глобальный)
                dss = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
                ds_opt = ["(Новый набор)"] + dss["dataset_name"].tolist()
                sel_d = st.selectbox("Набор данных", ds_opt, key="ds_ds_sel")
                
                new_d_name = ""
                if sel_d == "(Новый набор)":
                    new_d_name = st.text_input("Название нового глобального набора *", key="ds_new_d_name")

                # 3. ВЫБОР ВИДА (Зависимый)
                sel_i_id = None
                new_i_name = ""
                if sel_d != "(Новый набор)":
                    ds_id = dss[dss["dataset_name"] == sel_d]["dataset_id"].iloc[0]
                    infos = query_db("SELECT info_id, info_name FROM info_types WHERE dataset_id = :did", {"did": int(ds_id)})
                    info_opt = ["(Новый вид)"] + infos["info_name"].tolist()
                    sel_i = st.selectbox("Вид сведений", info_opt, key="ds_info_sel")
                    if sel_i == "(Новый вид)":
                        new_i_name = st.text_input("Название нового вида сведений *")
                    else:
                        sel_i_id = int(infos[infos["info_name"] == sel_i]["info_id"].iloc[0])
                else:
                    new_i_name = st.text_input("Название нового вида сведений *")

                # 4. ТЕХ. КОНТАКТ
                conts = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid", {"sid": selected_sup_id})
                cont_opt = ["Не выбран"] + conts["full_name"].tolist()
                sel_c = st.selectbox("Технический контакт", cont_opt, key="ds_cont_sel")
                prov_options = [
                    'Оператор и Поставщик',
                    'Только Поставщик',
                    'Не предоставляется',
                    'Протокол не заключён'
                ]
                sel_prov_new = st.selectbox("Право предоставления *", prov_options, key="ds_prov_new")

                if st.button("🚀 Создать связь", type="primary"):
                    try:
                        # 1. Получаем/Создаем ПРОЕКТ
                        p_id = None # Инициализируем
                        if sel_p == "(Новый проект)":
                            if not new_p_name:
                                st.error("❌ Укажите название нового проекта")
                                st.stop()
                            p_id = session.execute(text("""
                                INSERT INTO projects (supplier_id, project_name, status) 
                                VALUES (:sid, :pn, 1) RETURNING project_id
                            """), {"sid": int(selected_sup_id), "pn": new_p_name.strip()}).scalar()
                        else:
                            # Безопасный поиск ID существующего проекта
                            proj_row = projs[projs["project_name"] == sel_p]
                            if not proj_row.empty:
                                p_id = int(proj_row.iloc[0]["project_id"])
                            else:
                                st.error("❌ Проект не найден в базе")
                                st.stop()

                        # 2. Получаем/Создаем НАБОР
                        d_id = None
                        if sel_d == "(Новый набор)":
                            if not new_d_name:
                                st.error("❌ Укажите название нового набора")
                                st.stop()
                            d_id = session.execute(text("INSERT INTO datasets (dataset_name) VALUES (:n) RETURNING dataset_id"), 
                                                 {"n": new_d_name.strip()}).scalar()
                        else:
                            ds_row = dss[dss["dataset_name"] == sel_d]
                            if not ds_row.empty:
                                d_id = int(ds_row.iloc[0]["dataset_id"])
                            else:
                                st.error("❌ Набор данных не найден")
                                st.stop()

                        # 3. Получаем/Создаем ВИД СВЕДЕНИЙ
                        i_id = None
                        # Проверяем, выбрали ли мы существующий вид (sel_i_id был определен выше в коде при отрисовке)
                        if sel_d != "(Новый набор)" and sel_i != "(Новый вид)":
                            i_id = int(sel_i_id)
                        else:
                            if not new_i_name:
                                st.error("❌ Укажите название нового вида сведений")
                                st.stop()
                            i_id = session.execute(text("INSERT INTO info_types (dataset_id, info_name) VALUES (:did, :n) RETURNING info_id"), 
                                                 {"did": int(d_id), "n": new_i_name.strip()}).scalar()

                        # 4. Контакт (уже определен как sel_c)
                        c_id = None
                        if sel_c != "Не выбран":
                            c_id = int(conts[conts["full_name"] == sel_c]["contact_id"].iloc[0])

                        # 5. ФИНАЛЬНАЯ ПРОВЕРКА И ВСТАВКА
                        if p_id and d_id and i_id:
                            # Проверка на дубликат связи
                            dup_check = session.execute(text("""
                                SELECT 1 FROM project_items WHERE project_id = :pid AND info_id = :iid
                            """), {"pid": p_id, "iid": i_id}).scalar()
                            
                            if dup_check:
                                st.warning("⚠️ Такая связь (Проект + Вид сведений) уже существует!")
                            else:
                                session.execute(text("""
                                    INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id, provision_right) 
                                    VALUES (:pid, :did, :iid, :cid, CAST(:prov AS data_provision_type)) -- ⬅️ CAST ТУТ
                                """), {
                                    "pid": int(p_id), 
                                    "did": int(d_id), 
                                    "iid": int(i_id), 
                                    "cid": c_id, 
                                    "prov": sel_prov_new 
                                })
                                
                                session.commit()
                                st.cache_data.clear()
                                st.success("✅ Связь успешно создана!")
                                st.rerun()
                        else:
                            st.error("❌ Не удалось определить все необходимые ID для создания связи.")

                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}")
                        session.rollback()    

    # --- ТАБ 4: ОПРОСНИКИ (SURVEYS) ---
    with tab_survey:
        render_surveys_manager(session, selected_sup_id, is_readonly)

# ==========================================
# 🛠️ ПОД-ФУНКЦИИ (КОМПОНЕНТЫ)
# ==========================================

def render_supplier_form(session, existing_data=None):
    """Форма создания/редактирования поставщика"""
    is_editing = existing_data is not None
    prefix = "edit" if is_editing else "new"
    
    with st.form(f"{prefix}_supplier_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Наименование *", value=existing_data['supplier_name'] if is_editing else "")
            addr = st.text_input("Адрес", value=existing_data['supplier_address'] if is_editing else "")
            email = st.text_input("Email", value=existing_data['supplier_email'] if is_editing else "")
            is_mand = st.checkbox("Поставщик ОНПД", value=bool(existing_data['is_mandatory']) if is_editing else False)
        with col2:
            phone = st.text_input("Телефон", value=existing_data['supplier_phone'] if is_editing else "")
            mgr = st.text_input("Руководитель", value=existing_data['supplier_manager'] if is_editing else "")
            notes = st.text_area("Примечание", value=existing_data['supplier_notes'] if is_editing else "")

        if st.form_submit_button("💾 Сохранить"):
            if not name:
                st.error("Наименование обязательно"); return
            
            try:
                # Явно приводим ID к стандартному int
                target_id = int(existing_data['supplier_id']) if is_editing else None
                
                params = {
                    "n": name, "a": addr, "e": email, "p": phone, 
                    "m": mgr, "notes": notes, "is_m": is_mand, "id": target_id
                }
                
                if is_editing:
                    # Логируем изменение признака
                    log_action(st.session_state["auth"]["user_id"], "UPDATE_SUPPLIER", "suppliers", target_id,
                               old={"name": existing_data['supplier_name'], "mandatory": bool(existing_data['is_mandatory'])},
                               new={"name": name, "mandatory": is_mand})

                    session.execute(text("""
                        UPDATE suppliers SET 
                            supplier_name=:n, supplier_address=:a, supplier_email=:e,
                            supplier_phone=:p, supplier_manager=:m, supplier_notes=:notes,
                            is_mandatory=:is_m 
                        WHERE supplier_id=:id
                    """), params)
                else:
                    session.execute(text("""
                        INSERT INTO suppliers (supplier_name, supplier_address, supplier_email, supplier_phone, supplier_manager, supplier_notes, is_mandatory)
                        VALUES (:n, :a, :e, :p, :m, :notes, :is_m)
                    """), params)
                    
                    # Логируем создание
                    log_action(st.session_state["auth"]["user_id"], "CREATE_SUPPLIER", "suppliers", None, new={"name": name, "mandatory": is_mand})
                
                session.commit(); clear_cache()
                st.success("Данные поставщика обновлены!"); st.rerun()
            except Exception as e:
                st.error(f"Ошибка БД: {e}"); session.rollback()

def render_contacts_manager(session, supplier_id, is_readonly):
    """Управление контактами"""
    contacts_df = query_db("""
        SELECT contact_id, full_name, position, email, phone, notes
        FROM contacts WHERE supplier_id = :sid ORDER BY full_name
    """, {"sid": supplier_id})
    
    if not contacts_df.empty:
        st.dataframe(contacts_df[["full_name", "position", "email", "phone", "notes"]], 
                     width="stretch", hide_index=True)
    else:
        st.info("📭 У этого поставщика пока нет контактов.")
    
    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать контакт"):
            contact_options = ["(Новый контакт)"] + (contacts_df["full_name"].tolist() if not contacts_df.empty else [])
            sel_contact = st.selectbox("Выберите контакт:", contact_options, key="cont_sel")
            is_editing = sel_contact != "(Новый контакт)"

            if "cont_sel_prev" not in st.session_state or st.session_state["cont_sel_prev"] != sel_contact:
                if is_editing:
                    curr = contacts_df[contacts_df["full_name"] == sel_contact].iloc[0]
                    st.session_state["cont_fn_in"] = curr["full_name"]
                    st.session_state["cont_pos_in"] = curr["position"] or ""
                    st.session_state["cont_em_in"] = curr["email"] or ""
                    st.session_state["cont_ph_in"] = curr["phone"] or ""
                    st.session_state["cont_nt_in"] = curr["notes"] or ""
                else:
                    for k in ["cont_fn_in", "cont_pos_in", "cont_em_in", "cont_ph_in", "cont_nt_in"]:
                        st.session_state[k] = ""
                st.session_state["cont_sel_prev"] = sel_contact

            col1, col2 = st.columns(2)
            with col1:
                st.text_input("ФИО / Контакт *", key="cont_fn_in")
                st.text_input("Должность", key="cont_pos_in")
            with col2:
                st.text_input("Email", key="cont_em_in")
                st.text_input("Телефон", key="cont_ph_in")
            st.text_area("Примечание", height=60, key="cont_nt_in")

            col_btn, col_del = st.columns([3, 1])
            with col_btn:
                if st.button("💾 Сохранить контакт", type="primary"):
                    fn = st.session_state["cont_fn_in"].strip()
                    if not fn:
                        st.error("❌ Имя контакта обязательно")
                        st.stop()
                    try:
                        if is_editing:
                            curr = contacts_df[contacts_df["full_name"] == sel_contact].iloc[0]
                            cid = int(curr["contact_id"])
                            session.execute(text("""
                                UPDATE contacts SET full_name=:n, position=:p, email=:e, phone=:ph, notes=:nt
                                WHERE contact_id=:id
                            """), {"n": fn, "p": st.session_state["cont_pos_in"], "e": st.session_state["cont_em_in"],
                                   "ph": st.session_state["cont_ph_in"], "nt": st.session_state["cont_nt_in"], "id": cid})
                        else:
                            session.execute(text("""
                                INSERT INTO contacts (full_name, supplier_id, position, email, phone, notes)
                                VALUES (:n, :sid, :p, :e, :ph, :nt)
                            """), {"n": fn, "sid": supplier_id, "p": st.session_state["cont_pos_in"],
                                   "e": st.session_state["cont_em_in"], "ph": st.session_state["cont_ph_in"], 
                                   "nt": st.session_state["cont_nt_in"]})
                        session.commit()
                        st.cache_data.clear()
                        st.success("✅ Готово!"); st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {e}"); session.rollback()
            
            with col_del:
                if is_editing and st.button("🗑 Удалить", type="secondary"):
                    try:
                        curr = contacts_df[contacts_df["full_name"] == sel_contact].iloc[0]
                        session.execute(text("DELETE FROM contacts WHERE contact_id = :id"), {"id": int(curr["contact_id"])})
                        session.commit(); st.cache_data.clear(); st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {e}"); session.rollback()

def render_surveys_manager(session, supplier_id, is_readonly):
    """Управление опросниками: Реестр + кнопки действий"""
    st.write("### 📜 Реестр опросников")
    
    surveys_df = query_db("""
        SELECT 
            s.survey_id, 
            s.received_date, 
            COALESCE(STRING_AGG(d.dataset_name || ' | ' || i.info_name, ', '), 'Виды не выбраны') as info_list,
            s.it_regulations
        FROM surveys s
        LEFT JOIN survey_info_types sit ON s.survey_id = sit.survey_id
        LEFT JOIN info_types i ON sit.info_id = i.info_id
        LEFT JOIN datasets d ON i.dataset_id = d.dataset_id
        WHERE s.supplier_id = :sid 
        GROUP BY s.survey_id, s.received_date, s.it_regulations
        ORDER BY s.received_date DESC
    """, {"sid": supplier_id})

    if not surveys_df.empty:
        st.dataframe(surveys_df, width='stretch', hide_index=True)
        
        # 2. Добавляем str() и проверку на существование для безопасности
        survey_options = {}
        for _, r in surveys_df.iterrows():
            # Гарантируем, что info_list — это строка, даже если SQL вернул что-то странное
            info_text = str(r['info_list']) if r['info_list'] else "Нет видов сведений"
            label = f"{r['received_date']} | {info_text[:50]}... (ID: {r['survey_id']})"
            survey_options[label] = r['survey_id']
            
        sel_label = st.selectbox("🎯 Выберите опросник для действий:", [""] + list(survey_options.keys()), key="survey_action_sel")
        
        if sel_label:
            sid = survey_options[sel_label]  # <--- Переменная называется sid
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("👁 Просмотреть", width='stretch'):
                    st.session_state["survey_view_id"] = sid
                    st.session_state["survey_edit_id"] = None
            with c2:
                if not is_readonly and st.button("✏️ Редактировать", width='stretch'):
                    st.session_state["survey_edit_id"] = sid
                    st.session_state["survey_view_id"] = None
            with c3:
                # ✅ ИСПРАВЛЕНО: заменяем survey_id на sid
                if not is_readonly and st.button("🗑 Удалить", width='stretch', key=f"del_srv_{sid}"):
                    try:
                        session.execute(text("DELETE FROM surveys WHERE survey_id = :id"), {"id": sid})
                        session.commit()
                        st.cache_data.clear()
                        st.success("Удалено")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {e}")
                        session.rollback()

    # Отрисовка компонентов в зависимости от выбора
    if st.session_state.get("survey_view_id"):
        render_survey_viewer(session, st.session_state["survey_view_id"], is_readonly)
    
    if not is_readonly:
        st.divider()
        if st.button("➕ Заполнить новый опросник", type="primary"):
            st.session_state["survey_edit_id"] = "NEW"
            st.session_state["survey_view_id"] = None

        if st.session_state.get("survey_edit_id"):
            # Если "NEW" - создаем, если число - редактируем
            edit_id = st.session_state["survey_edit_id"]
            render_full_survey_form(session, supplier_id, None if edit_id == "NEW" else edit_id)

def render_survey_viewer(session, survey_id, is_readonly):
    """Детальный просмотр ВСЕХ полей опросника"""
    
    # 1. Загрузка данных
    res = query_db("SELECT * FROM surveys WHERE survey_id = :sid", {"sid": survey_id})
    
    # 🛡 ЗАЩИТА: Если опросник только что удалили, выходим из функции
    if res.empty:
        st.session_state["survey_view_id"] = None
        return

    data = res.iloc[0]
    data = query_db("SELECT * FROM surveys WHERE survey_id = :sid", {"sid": survey_id}).iloc[0]
    contacts = query_db("""
        SELECT c.full_name FROM survey_contacts sc 
        JOIN contacts c ON sc.contact_id = c.contact_id WHERE sc.survey_id = :sid
    """, {"sid": survey_id})
    links = query_db("SELECT survey_link FROM survey_links WHERE survey_id = :sid", {"sid": survey_id})
    
    # Исправление просмотра значений массива грифов
    current_regs = data['it_regulations']
    # Если это строка, чистим её (как выше), если список — просто присоединяем
    if isinstance(current_regs, str):
        display_regs = current_regs.strip('{}').replace('"', '').replace(',', ', ')
    else:
        display_regs = ", ".join(current_regs)
    
    st.success(f"📄 Опросный лист №{survey_id} от {data['received_date'].strftime('%d.%m.%Y')}")

    # --- СЕКЦИЯ 1: ПРАВО ---
    with st.expander("⚖️ Правовой статус и доступ", expanded=False):
        st.write(f"**Описание набора:** {data['it_description']}")
        st.write(f"**Назначение:** {data['it_purpose']}")
        st.write(f"**Правовой статус:** {data['it_legal_status']}")
        st.write(f"**НПА и ТНПА:** {data['it_statute']}")
        st.write(f"**Гриф(ы):** `{display_regs}`")
        st.write(f"**Иные ограничения:** {data['it_other_regulations']}")

    # --- СЕКЦИЯ 2: ТЕХНИКА ---
    with st.expander("⚙️ Технические характеристики", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Форма ведения:** {data['it_format']}")
            st.write(f"**Вид данных:** {data['it_type']}")
            st.write(f"**Формат хранения:** {data['it_digital_format']}")
            st.write(f"**Цифровая трансформация:** {'✅ Нужна' if data['it_digital_transform'] else '❌ Не требуется'}")
            st.write(f"**Каталоги метаданных:** {data['it_metadata_base']}")
            st.write(f"**Системы координат:** {data['it_coordinate_system']}")
        with c2:
            st.write(f"**Актуальность:** {data['it_actual_date']}")
            st.write(f"**Обновление:** {data['it_update']}")
            st.write(f"**Территория:** {data['it_spatial_extent']}")
            st.write(f"**Масштаб/Разрешение:** {data['it_spatial_scale']}")
            st.write(f"**Классификатор:** {data['it_classification']}")
            st.write(f"**Условные знаки:** {data['it_conventional_signs']}")
        
        st.divider()
        current_det = data['it_coordinate_determining']
        if isinstance(current_det, str):
            display_det = current_det.strip('{}').replace('"', '').replace(',', ', ')
        else:
            display_det = ", ".join(current_det)

        st.write(f"**Способ(ы) определения координат:** `{display_det}`")
        st.info(f"**Методика получения координат:**\n\n{data['it_coordinate_determining_text']}")
        st.write(f"**Использование у поставщика:** {data['it_use']}")

    # --- СЕКЦИЯ 3: ВЗАИМОДЕЙСТВИЕ ---
    with st.expander("🤝 Взаимодействие и публикация", expanded=False):
        # Загружаем из новой таблицы-связки взаимодействий
        ints_query = query_db("""
            SELECT ri.interaction_text FROM survey_interactions si
            JOIN ref_interactions ri ON si.interaction_id = ri.interaction_id
            WHERE si.survey_id = :sid
        """, {"sid": int(survey_id)})
        
        all_ints = ints_query["interaction_text"].tolist() if not ints_query.empty else ["Не указаны"]
        
        st.write(f"**Варианты взаимодействия:**")
        st.info(" • " + "\n • ".join(all_ints))
        
        st.write(f"**Форматы предоставления:** {data['it_distribution_format']}")
        st.write(f"**Способы предоставления:** {data['it_distribution_method']}")
        st.write(f"**Протоколы обмена:** {data['it_distribution_protocol']}")
        st.write(f"**Базовые сервисы НГ:** {data['it_base_services']}")
        st.write(f"**Публикация в СНГ:** {'✅ Допускается' if data['it_cis_publication'] else '❌ Запрещена'}")
        
        st.write("**👤 Ответственные контакты:**")
        if not contacts.empty:
            st.info(", ".join(contacts["full_name"].tolist()))
        
        st.write("**🔗 Ссылки на ресурсы/сервисы:**")
        if not links.empty:
            for l in links["survey_link"]:
                st.markdown(f"- {l}")
        else:
            st.write("Списка ссылок нет.")

    # Кнопка закрытия просмотра
    if st.button("⬅️ Закрыть просмотр"):
        st.session_state["survey_view_id"] = None
        st.rerun()

def render_full_survey_form(session, supplier_id, survey_id=None):
    """Универсальная форма: Создание (если survey_id=None) и Редактирование"""
    is_edit = survey_id is not None

    col_header, col_exit = st.columns([3, 1])
    with col_header:
        st.markdown(f"### {'✏️ Редактирование' if is_edit else '📝 Новый'} опросник")
    with col_exit:
        if st.button("🚪 Завершить редактирование", width='stretch'):
            st.session_state["survey_edit_id"] = None
            st.rerun()
    
    # 1. Загрузка данных при редактировании
    existing = None
    existing_contacts = []
    existing_links = ""
    processed_regs = [] 
    existing_interactions = []
    processed_det = []

    if is_edit: 
        existing = query_db("SELECT * FROM surveys WHERE survey_id = :id", {"id": survey_id}).iloc[0]
        
        # --- ИСПРАВЛЕНИЕ: Превращаем строку Postgres {a,b} в список Python [a,b] ---
        raw_regs = existing['it_regulations']
        if isinstance(raw_regs, str):
            processed_regs = raw_regs.strip('{}').replace('"', '').split(',')
            processed_regs = [r.strip() for r in processed_regs if r.strip()]
        elif isinstance(raw_regs, list):
            processed_regs = raw_regs
        
        # Загружаем список имен контактов
        c_data = query_db("""
            SELECT c.full_name FROM survey_contacts sc 
            JOIN contacts c ON sc.contact_id = c.contact_id WHERE sc.survey_id = :id
        """, {"id": survey_id})
        existing_contacts = c_data["full_name"].tolist() if not c_data.empty else []
        
        # Загружаем ссылки текстом
        l_data = query_db("SELECT survey_link FROM survey_links WHERE survey_id = :id", {"id": survey_id})
        existing_links = "\n".join(l_data["survey_link"].tolist()) if not l_data.empty else ""

        # Загружаем текущие варианты взаимодействия (текстовые названия для мультиселекта)
        int_data = query_db("""
            SELECT ri.interaction_text FROM survey_interactions si
            JOIN ref_interactions ri ON si.interaction_id = ri.interaction_id
            WHERE si.survey_id = :id
        """, {"id": int(survey_id)})
        existing_interactions = int_data["interaction_text"].tolist() if not int_data.empty else []

        # Загружаем способы определения координат
        raw_det = existing['it_coordinate_determining']
        if isinstance(raw_det, str):
            processed_det = raw_det.strip('{}').replace('"', '').split(',')
            processed_det = [r.strip() for r in processed_det if r.strip()]
        elif isinstance(raw_det, list):
            processed_det = raw_det

    # 2. Подготовка справочников
    items_data = query_db("""
        SELECT DISTINCT d.dataset_name, i.info_id, i.info_name
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        JOIN projects p ON pi.project_id = p.project_id
        WHERE p.supplier_id = :sid
    """, {"sid": supplier_id})

    # Справочники контактов и взаимодействий
    interactions = query_db("SELECT interaction_id, interaction_text FROM ref_interactions ORDER BY interaction_id")
    int_list = interactions["interaction_text"].tolist()
    # Создаем словарь: { 'Название': ID }
    int_map = dict(zip(interactions["interaction_text"], interactions["interaction_id"]))
    
    sup_contacts = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid", {"sid": supplier_id})
    contact_map = dict(zip(sup_contacts["full_name"], sup_contacts["contact_id"]))

    # Формируем список опций для мультиселекта: "Набор | Вид"
    options_map = {f"{r['dataset_name']} | {r['info_name']}": int(r['info_id']) for _, r in items_data.iterrows()}

    # Если мы в режиме редактирования, нужно достать текущие привязанные ID
    selected_info_ids = []
    if is_edit:
        curr_infos = query_db("SELECT info_id FROM survey_info_types WHERE survey_id = :id", {"id": survey_id})
        selected_info_ids = curr_infos["info_id"].tolist()

    # Вычисляем значения по умолчанию для мультиселекта
    default_options = [label for label, iid in options_map.items() if iid in selected_info_ids]

    # ВАЖНО: Мультиселект ставим НАД формой, чтобы он был реактивным
    sel_items_labels = st.multiselect(
        "📁 Выберите наборы и виды сведений, к которым относится опросник *",
        options=list(options_map.keys()),
        default=default_options,
        key="srv_multi_info"
    )

    with st.form("survey_combined_form"):
        # СЕКЦИЯ 1: Общее
        received_date = st.date_input("Дата получения", value=existing['received_date'] if is_edit else date.today())
        
        # СЕКЦИЯ 2: Право
        with st.expander("⚖️ Правовой статус", expanded=False):
            it_descr = st.text_area("Описание", value=existing['it_description'] if is_edit else "Нет")
            it_purp = st.text_area("Назначение", value=existing['it_purpose'] if is_edit else "Нет")
            it_leg = st.text_area("Правовой статус", value=existing['it_legal_status'] if is_edit else "Нет")
            it_stat = st.text_area("НПА/ТНПА", value=existing['it_statute'] if is_edit else "Нет")
            
            #existing_regs = existing['it_regulations'] if is_edit else []
            regs_options = ['Открытые данные', 'Для служебного использования', 'Коммерческая информация', 'Иное']
            it_reg = st.multiselect(
                "Ограничительный гриф(ы) *", 
                regs_options, 
                default=processed_regs if is_edit else ['Открытые данные'],
                key="srv_reg_multi"
            )
            it_oreg = st.text_area("Иные ограничения", value=existing['it_other_regulations'] if is_edit else "Нет")

        # СЕКЦИЯ 3: Техника
        with st.expander("⚙️ Технические характеристики", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                it_form = st.selectbox("Форма ведения", ["Цифровая", "Иная"], 
                                     index=0 if not is_edit or existing['it_format']=="Цифровая" else 1)
                it_type = st.text_input("Вид данных (растр, вектор, таблица, текст и др.)", value=existing['it_type'] if is_edit else "Нет")
                it_df = st.text_input("Формат хранения (shp, tiff, docs, mdb и др.)", value=existing['it_digital_format'] if is_edit else "Нет")
                it_trans = st.checkbox("Нужен перевод набора в цифровую форму?", value=existing['it_digital_transform'] if is_edit else False)
                it_meta = st.text_area("Наличие инф. каталогов для метаданных", value=existing['it_metadata_base'] if is_edit else "Нет", height=68)
                it_cs = st.text_input("Системы отсчёта координат и высот", value=existing['it_coordinate_system'] if is_edit else "Нет")
            with c2:
                it_ad = st.text_input("Актуальность (год состояния местности)", value=existing['it_actual_date'] if is_edit else "Нет")
                it_upd = st.text_input("Периодичность обновления", value=existing['it_update'] if is_edit else "Нет")
                it_ext = st.text_area("Территория (пространственный охват)", value=existing['it_spatial_extent'] if is_edit else "Нет", height=68)
                it_scale = st.text_area("Пространственное разрешение или масштаб", value=existing['it_spatial_scale'] if is_edit else "Нет", height=68)
                it_classif = st.text_input("Наличие специализированного классификатора", value=existing['it_classification'] if is_edit else "Нет")
                it_signs = st.text_input("Наличие каталога условных знаков", value=existing['it_conventional_signs'] if is_edit else "Нет")
            
            st.divider()
            det_options = ['Автоматический', 'Полуавтоматический', 'Ручной', 'Иное']
        
            it_det = st.multiselect(
                "Способ(ы) определения координат *", 
                options=det_options,
                default=processed_det if is_edit else ['Автоматический'],
                key="srv_det_multi"
            )
            it_det_txt = st.text_area("Методика, источник и инструмент получения координат", value=existing['it_coordinate_determining_text'] if is_edit else "Нет")
            it_use = st.text_area("Вариант использования набора у поставщика (ГИС, WEB)", value=existing['it_use'] if is_edit else "Нет")

        # СЕКЦИЯ 4: Взаимодействие
        with st.expander("🤝 Взаимодействие и контакты", expanded=False):
            it_dist_f = st.text_area("Возможные формы и форматы предоставления (бумага, цифра)", value=existing['it_distribution_format'] if is_edit else "Нет")
            it_dist_m = st.text_input("Способы предоставления (почта, сервис, носитель)", value=existing['it_distribution_method'] if is_edit else "Нет")
            it_dist_p = st.text_input("Протоколы обмена (HTTPS, WMS, REST...)", value=existing['it_distribution_protocol'] if is_edit else "Нет")
            it_base = st.text_input("Предполагаемые базовые сервисы (поиск, фильтрация...)", value=existing['it_base_services'] if is_edit else "Нет")
            
            sel_ints = st.multiselect(
                "Предпочтительные варианты взаимодействия *", 
                options=int_list, 
                default=existing_interactions if is_edit else [],
                key="srv_int_multi"
            )
            sel_conts = st.multiselect("Контактные лица по опроснику", list(contact_map.keys()), default=existing_contacts)
            links_raw = st.text_area("Ссылки (по одной на строку)", value=existing_links)
            it_cis = st.checkbox("Допускается публикация на Геопортале СНГ", value=existing['it_cis_publication'] if is_edit else False)

        if st.form_submit_button("💾 Сохранить опросник", type="primary"):
            try:
                params = {
                    "rd": received_date, "sid": int(supplier_id), 
                    "descr": it_descr, "purp": it_purp, "leg": it_leg, "stat": it_stat,
                    "reg": it_reg, "oreg": it_oreg, "form": it_form, "tp": it_type,
                    "df": it_df, "trans": it_trans, "meta": it_meta, "cs": it_cs, 
                    "ext": it_ext, "ad": it_ad, "upd": it_upd, "scale": it_scale, 
                    "classif": it_classif, "signs": it_signs, "det": it_det, 
                    "det_txt": it_det_txt, "use": it_use, "dist_f": it_dist_f, 
                    "dist_m": it_dist_m, "dist_p": it_dist_p, "base": it_base,
                    "cis": it_cis
                }

                if is_edit:
                    params["survey_id"] = int(survey_id)
                    session.execute(text("""
                        UPDATE surveys SET 
                            received_date=:rd, it_description=:descr, it_purpose=:purp,
                            it_legal_status=:leg, it_statute=:stat, it_regulations = CAST(:reg AS restrictions[]), it_other_regulations=:oreg,
                            it_format=:form, it_type=:tp, it_digital_format=:df, it_digital_transform=:trans,
                            it_metadata_base=:meta, it_coordinate_system=:cs, it_spatial_extent=:ext,
                            it_actual_date=:ad, it_update=:upd, it_spatial_scale=:scale, it_classification=:classif,
                            it_conventional_signs=:signs, it_coordinate_determining = CAST(:det AS definitions[]), it_coordinate_determining_text=:det_txt,
                            it_use=:use, it_distribution_format=:dist_f, it_distribution_method=:dist_m, 
                            it_distribution_protocol=:dist_p, it_base_services=:base, it_cis_publication=:cis
                        WHERE survey_id=:survey_id
                    """), params)

                    # Очищаем старые связи
                    session.execute(text("DELETE FROM survey_info_types WHERE survey_id = :id"), {"id": int(survey_id)})
                    session.execute(text("DELETE FROM survey_contacts WHERE survey_id = :id"), {"id": int(survey_id)})
                    session.execute(text("DELETE FROM survey_links WHERE survey_id = :id"), {"id": int(survey_id)})
                    session.execute(text("DELETE FROM survey_interactions WHERE survey_id = :id"), {"id": int(survey_id)})
                    final_id = int(survey_id)
                else:
                    # ПОЛНЫЙ INSERT (все поля)
                    final_id = session.execute(text("""
                        INSERT INTO surveys (
                            received_date, supplier_id, it_description, it_purpose, 
                            it_legal_status, it_statute, it_regulations, it_other_regulations,
                            it_format, it_type, it_digital_format, it_digital_transform, 
                            it_metadata_base, it_coordinate_system, it_spatial_extent, 
                            it_actual_date, it_update, it_spatial_scale, it_classification, 
                            it_conventional_signs, it_coordinate_determining, it_coordinate_determining_text,
                            it_use, it_distribution_format, it_distribution_method, it_distribution_protocol,
                            it_base_services, it_cis_publication
                        ) VALUES (
                            :rd, :sid, :descr, :purp, :leg, :stat, CAST(:reg AS restrictions[]), :oreg,
                            :form, :tp, :df, :trans, :meta, :cs, :ext,
                            :ad, :upd, :scale, :classif, :signs, CAST(:det AS definitions[]), :det_txt,
                            :use, :dist_f, :dist_m, :dist_p, :base, :cis
                        ) RETURNING survey_id
                    """), params).scalar()

                # Вставка всех выбранных видов сведений
                for label in sel_items_labels:
                    info_id = options_map[label]
                    session.execute(text("INSERT INTO survey_info_types (survey_id, info_id) VALUES (:sid, :iid)"),
                                    {"sid": int(final_id), "iid": int(info_id)})

                # Вставка контактов (приводим к int)
                for c_name in sel_conts:
                    session.execute(text("INSERT INTO survey_contacts (survey_id, contact_id) VALUES (:sid, :cid)"),
                                    {"sid": int(final_id), "cid": int(contact_map[c_name])})
                
                # Вставка ссылок
                links = [l.strip() for l in links_raw.split('\n') if l.strip()]
                for l in links:
                    session.execute(text("INSERT INTO survey_links (survey_id, survey_link) VALUES (:sid, :link)"),
                                    {"sid": int(final_id), "link": l})

                # Запись нескольких взаимодействий
                for int_text in sel_ints:
                    # Находим ID по тексту из нашего словаря
                    it_id = int(int_map[int_text]) 
                    
                    session.execute(text("""
                        INSERT INTO survey_interactions (survey_id, interaction_id) 
                        VALUES (:sid, :iid)
                    """), {"sid": int(final_id), "iid": it_id})

                session.commit()
                st.cache_data.clear()
                #st.session_state["survey_edit_id"] = None # Выходим из режима редактирования
                st.success("✅ Данные успешно сохранены!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка сохранения: {e}")
                session.rollback()