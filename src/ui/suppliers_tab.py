import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date
from config.cache import query_db, clear_cache
from config.auth import log_action
from ui.shared_components import render_survey_viewer

# 🔤 Маппинг для отображения
RU_LABELS = {
    "supplier_name": "Наименование", "supplier_address": "Адрес",
    "supplier_email": "Email", "supplier_phone": "Телефон",
    "supplier_website": "Сайт", "supplier_manager": "Руководитель",
    "supplier_notes": "Примечание",
    "is_mandatory": "Поставщик ОПНД"
}

def render_suppliers_tab(session, user_role="user"):
    st.subheader("📁 Реестр поставщиков")
    is_readonly = (user_role == "user")
    
    # ==========================================
    # 🧠 1. УПРАВЛЕНИЕ СОСТОЯНИЕМ (STATE)
    # ==========================================
    
    # Проверяем, не пришли ли мы сюда по ссылке из другого раздела (Deep Link)
    # Если в session_state лежит 'filter_supplier_id', приоритет отдаем ему
    incoming_sup_id = st.session_state.get("filter_supplier_id")
    
    all_suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(all_suppliers["supplier_name"], all_suppliers["supplier_id"]))
    inv_sup_map = {v: k for k, v in sup_map.items()} # Обратный маппинг ID -> Name

    # Инициализация выбора в session_state, если его там нет
    if "selected_sup_id" not in st.session_state:
        st.session_state["selected_sup_id"] = None

    # Если есть входящий ID, принудительно устанавливаем его как выбранный
    if incoming_sup_id:
        st.session_state["selected_sup_id"] = incoming_sup_id
        # Очищаем входящий фильтр, чтобы он не срабатывал при следующем реране
        st.session_state["filter_supplier_id"] = None

    # Определяем индекс для selectbox на основе ID из сессии
    current_sup_name = inv_sup_map.get(st.session_state["selected_sup_id"], "")
    try:
        current_index = ([""] + list(sup_map.keys())).index(current_sup_name)
    except ValueError:
        current_index = 0

    # ==========================================
    # 🏢 2. ГЛОБАЛЬНЫЙ ВЫБОР ПОСТАВЩИКА
    # ==========================================
    
    def on_sup_change():
        # Сохраняем выбор в session_state при изменении
        new_name = st.session_state["sup_selector_widget"]
        st.session_state["selected_sup_id"] = sup_map.get(new_name)
        st.session_state["sup_edit_mode"] = False
        # Логируем выбор поставщика
        if st.session_state["selected_sup_id"]:
            log_action(st.session_state["auth"]["user_id"], "VIEW_SUPPLIER", 
                       "suppliers", st.session_state["selected_sup_id"])

    col_sel, col_add = st.columns([3, 1])
    with col_sel:
        selected_sup_name = st.selectbox(
            "🏢 Выберите поставщика", 
            [""] + list(sup_map.keys()), 
            index=current_index,
            key="sup_selector_widget",
            on_change=on_sup_change
        )
    
    selected_sup_id = st.session_state["selected_sup_id"]

    if not selected_sup_id:
        st.info("👈 Выберите поставщика в списке или добавьте нового.")
        if not is_readonly:
            with st.expander("➕ Добавить нового поставщика в базу"):
                render_supplier_form(session)
        return

    # ==========================================
    # 📑 3. ПОД-НАВИГАЦИЯ (SEGMENTED CONTROL)
    # ==========================================
    st.markdown(f"## {selected_sup_name}")
    
    # Используем segmented_control вместо tabs для сохранения состояния
    sub_nav = st.segmented_control(
        "Разделы",
        options=["🏠 Карточка", "👤 Контакты", "📦 Наборы", "📝 Опросники", "📋 Проекты"],
        default="🏠 Карточка",
        key="sup_sub_nav",
        label_visibility="collapsed"
    )
    st.markdown("---")

    if sub_nav == "🏠 Карточка":
        render_supplier_card(session, selected_sup_id, is_readonly)

    elif sub_nav == "👤 Контакты":
        render_contacts_manager(session, selected_sup_id, is_readonly)

    elif sub_nav == "📦 Наборы":
        render_datasets_subtab(session, selected_sup_id, is_readonly)

    elif sub_nav == "📝 Опросники":
        render_surveys_manager(session, selected_sup_id, is_readonly)

    elif sub_nav == "📋 Проекты":
        render_supplier_projects_grid(selected_sup_id)

# ==========================================
# 🛠️ НОВЫЕ И ОБНОВЛЕННЫЕ КОМПОНЕНТЫ
# ==========================================

def render_supplier_card(session, selected_sup_id, is_readonly):
    """Вынесено в отдельную функцию для чистоты основного рендера"""
    sup_data = query_db("SELECT * FROM suppliers WHERE supplier_id = :sid", {"sid": selected_sup_id}).iloc[0]
    
    if sup_data.get('is_mandatory'):
        st.warning("⭐ **Поставщик ОНПД**")
    
    col_info, col_edit = st.columns([2, 1])
    
    if "sup_edit_mode" not in st.session_state:
        st.session_state["sup_edit_mode"] = False
            
    with col_info:
        for col, label in RU_LABELS.items():
            if col in ["supplier_id", "supplier_name", "is_mandatory"]: continue
            if pd.notna(sup_data.get(col)) and str(sup_data[col]).strip() != "":
                st.write(f"**{label}:** {sup_data[col]}")
    
    with col_edit:
        if not is_readonly:
            if st.button("✏️ Редактировать реквизиты", width="stretch"):
                st.session_state["sup_edit_mode"] = not st.session_state["sup_edit_mode"]
                st.rerun()
    
    if st.session_state["sup_edit_mode"]:
        with st.expander("📝 Форма редактирования", expanded=True):
            render_supplier_form(session, sup_data)
            if st.button("❌ Отменить редактирование"):
                st.session_state["sup_edit_mode"] = False
                st.rerun()

def render_supplier_projects_grid(supplier_id):
    """
    Генерация сетки карточек проектов с механизмом перехода (Deep Link).
    Это решение нашего Side-Quest по UI.
    """
    st.markdown("#### 📋 Проекты поставщика")
    
    projects = query_db("""
        SELECT p.project_id, p.project_name, rs.status_name,
               (SELECT COUNT(*) FROM project_items WHERE project_id = p.project_id) as items_count
        FROM projects p
        LEFT JOIN ref_statuses rs ON p.status = rs.status_id
        WHERE p.supplier_id = :sid
        ORDER BY p.project_id DESC
    """, {"sid": supplier_id})
    
    if projects.empty:
        st.info("У этого поставщика пока нет созданных проектов.")
        return
    
    # дебаг: функция-коллбэк 
    def go_to_project_callback(sup_id, prj_id):
        st.session_state["main_nav"] = "📋 Проекты"
        st.session_state["filter_supplier_id"] = sup_id
        st.session_state["filter_project_id"] = prj_id
        # Логирование внутри коллбэка
        log_action(st.session_state["auth"]["user_id"], "NAVIGATE_TO_PROJECT", 
                   "projects", prj_id)

    # Рисуем карточки в 3 колонки
    cols = st.columns(3)
    for idx, row in projects.iterrows():
        with cols[idx % 3]:
            # Создаем стилизованный контейнер-карточку
            with st.container(border=True):
                st.markdown(f"**{row['project_name']}**")
                st.caption(f"Статус: {row['status_name'] or 'Не указан'}")
                st.write(f"📦 Объектов: {row['items_count']}")
                
                # Кнопка перехода
                if st.button(
                    "🔎 Перейти к проекту", 
                    key=f"goto_prj_{row['project_id']}", 
                    width=200,
                    on_click=go_to_project_callback,
                    args=(supplier_id, row['project_id'])
                ):
                    # 🚀 МЕХАНИЗМ ПЕРЕХОДА (Deep Link)
                    st.session_state["main_nav"] = "📋 Проекты" # Переключаем глобальный таб
                    st.session_state["filter_supplier_id"] = supplier_id
                    st.session_state["filter_project_id"] = row['project_id']
                    
                    # Логируем переход
                    log_action(st.session_state["auth"]["user_id"], "NAVIGATE_TO_PROJECT", 
                               "projects", row['project_id'])
                    st.rerun()


def render_datasets_subtab(session, selected_sup_id, is_readonly):
    """Улучшенное управление наборами (3 колонки): Проекты | Состав (Markdown) | Управление"""
    
    projs_df = query_db("""
        SELECT project_id, project_name FROM projects WHERE supplier_id = :sid ORDER BY project_name
    """, {"sid": selected_sup_id})

    col_projs, col_items, col_ctrl = st.columns([0.25, 0.4, 0.35])

    # --- КОЛОНКА 1: СПИСОК ПРОЕКТОВ ---
    current_proj_id = None
    with col_projs:
        st.markdown("##### 📁 Проекты")
        if projs_df.empty:
            st.info("Нет проектов.")
        else:
            selection = st.dataframe(
                projs_df[["project_name"]],
                width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key=f"sup_proj_list_{selected_sup_id}",
                column_config={"project_name": "Название проекта"}
            )
            selected_rows = selection.get("selection", {}).get("rows", [])
            if selected_rows:
                current_proj_id = int(projs_df.iloc[selected_rows[0]]["project_id"])
            else:
                st.caption("👈 Выберите проект")

    # --- КОЛОНКА 2: СОСТАВ ---
    with col_items:
        st.markdown("##### 📦 Состав наборов")
        if current_proj_id:
            items_df = query_db("""
                SELECT 
                    pi.item_id, d.dataset_name, i.info_name, i.info_id, d.dataset_id,
                    c.full_name as tech_contact, pi.provision_right, p.project_name
                FROM project_items pi
                JOIN projects p ON pi.project_id = p.project_id
                JOIN datasets d ON pi.dataset_id = d.dataset_id
                JOIN info_types i ON pi.info_id = i.info_id
                LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
                WHERE pi.project_id = :pid
                ORDER BY d.dataset_name, i.info_name
            """, {"pid": current_proj_id})

            if items_df.empty:
                st.info("В проекте нет наборов.")
            else:
                for _, row in items_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**{row['dataset_name']}**")
                        st.markdown(f"*{row['info_name']}*")
                        st.caption(f"⚖️ {row['provision_right']}")
                        
                        c_edit, c_del = st.columns(2)
                        with c_edit:
                            # 🟢 ПРИ НАЖАТИИ "ИЗМЕНИТЬ" - ЗАПОЛНЯЕМ SESSION_STATE
                            if st.button("✏️ Изменить", key=f"edit_item_{row['item_id']}", use_container_width=True):
                                st.session_state["editing_item_id"] = int(row['item_id'])
                                # Заполняем поля формы напрямую
                                st.session_state["ds_form_proj"] = row['project_name']
                                st.session_state["ds_form_ds"] = row['dataset_name']
                                st.session_state["ds_form_i"] = row['info_name']
                                st.session_state["ds_form_cont"] = row['tech_contact'] if pd.notna(row['tech_contact']) else "Не выбран"
                                st.session_state["ds_form_prov"] = row['provision_right']
                                st.rerun()
                        with c_del:
                            if not is_readonly:
                                if st.button("🗑", key=f"del_item_{row['item_id']}", use_container_width=True):
                                    has_stages = query_db("SELECT 1 FROM item_stages WHERE item_id = :id LIMIT 1", {"id": int(row['item_id'])})
                                    if not has_stages.empty:
                                        st.error("Удаление заблокировано: есть этапы технологии.")
                                    else:
                                        session.execute(text("DELETE FROM project_items WHERE item_id = :id"), {"id": int(row['item_id'])})
                                        session.commit(); clear_cache(); st.rerun()
        else:
            st.caption("Выберите проект слева")

    # --- КОЛОНКА 3: ФОРМА ---
    with col_ctrl:
        if not is_readonly:
            is_edit_mode = "editing_item_id" in st.session_state
            
            if is_edit_mode:
                st.markdown("##### ✏️ Редактирование")
                if st.button("⬅️ Отмена / Новая запись", use_container_width=True):
                    # Очищаем ключи формы при отмене
                    for k in ["editing_item_id", "ds_form_proj", "ds_form_ds", "ds_form_i", "ds_form_cont", "ds_form_prov"]:
                        st.session_state.pop(k, None)
                    st.rerun()
            else:
                st.markdown("##### ➕ Новая связь")

            _render_dataset_link_form(session, selected_sup_id, current_proj_id, projs_df, is_edit_mode)
        else:
            st.info("Режим просмотра")

# ==========================================
# 🛠️ ПОД-ФУНКЦИИ (КОМПОНЕНТЫ)
# ==========================================

def _render_dataset_link_form(session, supplier_id, current_proj_id, projs_df, is_edit):
    """Форма создания и редактирования (Разблокированная версия)"""
    
    # 1. Выбор проекта
    proj_names = ["(Новый проект)"] + projs_df["project_name"].tolist()
    st.selectbox("Проект *", proj_names, key="ds_form_proj", disabled=is_edit)
    
    if st.session_state.get("ds_form_proj") == "(Новый проект)":
        st.text_input("Название нового проекта", key="ds_form_new_p")
        st.checkbox("Проект Соглашения", key="ds_form_new_p_agr")

    st.divider()

    # 2. Набор и Вид (Теперь разблокированы)
    dss = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    ds_names = ["(Новый набор)"] + dss["dataset_name"].tolist()
    st.selectbox("Набор данных *", ds_names, key="ds_form_ds")
    
    current_ds_name = st.session_state.get("ds_form_ds")
    if current_ds_name == "(Новый набор)":
        st.text_input("Имя нового набора", key="ds_form_new_d")
        st.text_input("Имя нового вида", key="ds_form_new_i")
    else:
        d_id = int(dss[dss["dataset_name"] == current_ds_name]["dataset_id"].iloc[0])
        infos = query_db("SELECT info_id, info_name FROM info_types WHERE dataset_id = :did", {"did": d_id})
        i_names = ["(Новый вид)"] + infos["info_name"].tolist()
        st.selectbox("Вид сведений *", i_names, key="ds_form_i")
        if st.session_state.get("ds_form_i") == "(Новый вид)":
            st.text_input("Имя нового вида", key="ds_form_new_i_name")

    # 3. Доп. параметры
    conts = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid", {"sid": supplier_id})
    cont_names = ["Не выбран"] + conts["full_name"].tolist()
    st.selectbox("Тех. контакт", cont_names, key="ds_form_cont")
    
    prov_options = ['Протокол не заключён', 'Оператор и Поставщик', 'Только Поставщик', 'Не предоставляется']
    st.selectbox("Право предоставления", prov_options, key="ds_form_prov")

    if st.button("💾 Сохранить изменения" if is_edit else "🚀 Создать связь", type="primary", use_container_width=True):
        try:
            # А. Получаем ID проекта
            if not is_edit and st.session_state.ds_form_proj == "(Новый проект)":
                p_id = session.execute(text("INSERT INTO projects (supplier_id, project_name, status, is_agreement_project) VALUES (:sid, :pn, 1, :is_agr) RETURNING project_id"),
                                       {"sid": supplier_id, "pn": st.session_state.ds_form_new_p.strip(), "is_agr": st.session_state.ds_form_new_p_agr}).scalar()
            else:
                p_res = projs_df[projs_df["project_name"] == st.session_state.ds_form_proj]
                p_id = int(p_res.iloc[0]["project_id"]) if not p_res.empty else None

            # Б. Получаем ID набора
            if st.session_state.ds_form_ds == "(Новый набор)":
                d_id = session.execute(text("INSERT INTO datasets (dataset_name) VALUES (:n) RETURNING dataset_id"), {"n": st.session_state.ds_form_new_d.strip()}).scalar()
            else:
                d_id = int(dss[dss["dataset_name"] == st.session_state.ds_form_ds]["dataset_id"].iloc[0])

            # В. Получаем ID вида
            if st.session_state.ds_form_ds == "(Новый набор)" or st.session_state.ds_form_i == "(Новый вид)":
                # Если набор новый, то и вид новый (берем из ds_form_new_i), если набор старый, а вид новый - из ds_form_new_i_name
                i_name = st.session_state.get("ds_form_new_i") or st.session_state.get("ds_form_new_i_name")
                i_id = session.execute(text("INSERT INTO info_types (dataset_id, info_name) VALUES (:did, :n) RETURNING info_id"),
                                       {"did": d_id, "n": i_name.strip()}).scalar()
            else:
                i_id = int(infos[infos["info_name"] == st.session_state.ds_form_i]["info_id"].iloc[0])

            # Г. Параметры связи
            c_id = int(conts[conts["full_name"] == st.session_state.ds_form_cont]["contact_id"].iloc[0]) if st.session_state.ds_form_cont != "Не выбран" else None
            prov = st.session_state.ds_form_prov

            if is_edit:
                session.execute(text("""
                    UPDATE project_items SET dataset_id=:did, info_id=:iid, tech_contact_id=:cid, provision_right=CAST(:prov AS data_provision_type)
                    WHERE item_id=:id
                """), {"did": d_id, "iid": i_id, "cid": c_id, "prov": prov, "id": st.session_state.editing_item_id})
                for k in ["editing_item_id", "ds_form_proj", "ds_form_ds", "ds_form_i", "ds_form_cont", "ds_form_prov"]:
                    st.session_state.pop(k, None)
            else:
                session.execute(text("""
                    INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id, provision_right) 
                    VALUES (:pid, :did, :iid, :cid, CAST(:prov AS data_provision_type))
                """), {"pid": p_id, "did": d_id, "iid": i_id, "cid": c_id, "prov": prov})

            session.commit(); clear_cache(); st.success("Успешно!"); st.rerun()
        except Exception as e:
            st.error(f"Ошибка БД: {e}"); session.rollback()    


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
    """Улучшенное управление контактами: Список | Детали | CRUD"""
    contacts_df = query_db("""
        SELECT contact_id, full_name, position, email, phone, notes
        FROM contacts WHERE supplier_id = :sid ORDER BY full_name
    """, {"sid": supplier_id})
    
    if contacts_df.empty:
        st.info("📭 У этого поставщика пока нет контактов.")
        if not is_readonly:
            with st.expander("➕ Добавить первый контакт"):
                _render_contact_form_standalone(session, supplier_id)
        return

    # Создаем три колонки
    col_list, col_view, col_form = st.columns([0.25, 0.35, 0.4])

    with col_list:
        st.markdown("##### 👥 Список")
        # Выбор контакта через таблицу
        selection = st.dataframe(
            contacts_df[["full_name"]], 
            width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key=f"cont_list_{supplier_id}",
            column_config={"full_name": "ФИО"}
        )
        
        selected_rows = selection.get("selection", {}).get("rows", [])
        is_selected = len(selected_rows) > 0
        curr_contact = contacts_df.iloc[selected_rows[0]] if is_selected else None

    with col_view:
        st.markdown("##### 🔍 Детали")
        if is_selected:
            with st.container(border=True):
                st.markdown(f"### {curr_contact['full_name']}")
                st.write(f"**Должность:** {curr_contact['position'] or '—'}")
                st.write(f"**Email:** {curr_contact['email'] or '—'}")
                st.write(f"**Телефон:** {curr_contact['phone'] or '—'}")
                st.divider()
                st.caption("Примечание:")
                st.write(curr_contact['notes'] or "Нет данных")
        else:
            st.info("👈 Выберите контакт в списке слева")

    with col_form:
        if not is_readonly:
            st.markdown("##### ✏️ Редактирование")
            # Если выбран контакт - режим редактирования, если нет - кнопка "Создать новый"
            if is_selected:
                # Вспомогательная функция формы (код ниже)
                _render_contact_form_standalone(session, supplier_id, curr_contact)
                
                # Кнопка удаления в самом низу колонки
                st.write("<br>", unsafe_allow_html=True)
                if st.button("🗑 Удалить контакт", type="secondary", use_container_width=True, key="del_cont_btn"):
                    session.execute(text("DELETE FROM contacts WHERE contact_id = :id"), {"id": int(curr_contact['contact_id'])})
                    session.commit(); clear_cache(); st.rerun()
            else:
                with st.container(border=True):
                    st.write("Хотите добавить нового человека?")
                    if st.button("➕ Создать новый контакт", use_container_width=True):
                        st.session_state["force_new_contact"] = True # Временный флаг
                
                if st.session_state.get("force_new_contact"):
                    _render_contact_form_standalone(session, supplier_id)

def _render_contact_form_standalone(session, supplier_id, existing_data=None):
    """Вынесенная форма контакта для встраивания в колонку"""
    is_edit = existing_data is not None
    
    # Чтобы значения в полях обновлялись при смене контакта, используем ключи с ID
    cid = existing_data['contact_id'] if is_edit else "new"
    
    with st.container(border=True):
        fn = st.text_input("ФИО *", value=existing_data['full_name'] if is_edit else "", key=f"fn_{cid}")
        pos = st.text_input("Должность", value=existing_data['position'] if is_edit else "", key=f"pos_{cid}")
        em = st.text_input("Email", value=existing_data['email'] if is_edit else "", key=f"em_{cid}")
        ph = st.text_input("Телефон", value=existing_data['phone'] if is_edit else "", key=f"ph_{cid}")
        nt = st.text_area("Примечание", value=existing_data['notes'] if is_edit else "", key=f"nt_{cid}", height=100)
        
        if st.button("💾 Сохранить", type="primary", use_container_width=True, key=f"save_cont_{cid}"):
            if not fn:
                st.error("ФИО обязательно")
            else:
                try:
                    if is_edit:
                        session.execute(text("""
                            UPDATE contacts SET full_name=:n, position=:p, email=:e, phone=:ph, notes=:nt
                            WHERE contact_id=:id
                        """), {"n": fn, "p": pos, "e": em, "ph": ph, "nt": nt, "id": int(existing_data['contact_id'])})
                    else:
                        session.execute(text("""
                            INSERT INTO contacts (full_name, supplier_id, position, email, phone, notes)
                            VALUES (:n, :sid, :p, :e, :ph, :nt)
                        """), {"n": fn, "sid": int(supplier_id), "p": pos, "e": em, "ph": ph, "nt": nt})
                    session.commit(); clear_cache()
                    st.session_state.pop("force_new_contact", None)
                    st.success("Готово!"); st.rerun()
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