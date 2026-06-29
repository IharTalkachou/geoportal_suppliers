import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache
from config.auth import log_action

from ui.shared_components import render_survey_viewer

# 🔤 Маппинг для отображения
RU_LABELS = {
    "supplier_name": "Наименование", "supplier_address": "Адрес",
    "supplier_email": "Email", "supplier_phone": "Телефон",
    "supplier_website": "Сайт", "supplier_manager": "Руководитель",
    "supplier_notes": "Примечание",
    "is_mandatory": "Поставщик ОПНД",
    "is_gov_agency": "Государственный орган" # 👈 Добавлено
}

def render_suppliers_tab(session, user_role="user"):
    st.subheader("📁 Реестр поставщиков")
    is_readonly = (user_role == "user")
    
    # --- 1. УПРАВЛЕНИЕ СОСТОЯНИЕМ ---
    incoming_sup_id = st.session_state.get("filter_supplier_id")
    all_suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(all_suppliers["supplier_name"], all_suppliers["supplier_id"]))
    inv_sup_map = {v: k for k, v in sup_map.items()}

    if "selected_sup_id" not in st.session_state:
        st.session_state["selected_sup_id"] = None

    if incoming_sup_id:
        st.session_state["selected_sup_id"] = incoming_sup_id
        st.session_state["filter_supplier_id"] = None

    current_sup_name = inv_sup_map.get(st.session_state["selected_sup_id"], "")
    try:
        current_index = ([""] + list(sup_map.keys())).index(current_sup_name)
    except ValueError:
        current_index = 0

    # --- 2. ВЫБОР ПОСТАВЩИКА ---
    def on_sup_change():
        new_name = st.session_state["sup_selector_widget"]
        st.session_state["selected_sup_id"] = sup_map.get(new_name)
        st.session_state["sup_edit_mode"] = False
        if st.session_state["selected_sup_id"]:
            log_action(st.session_state["auth"]["user_id"], "VIEW_SUPPLIER", "suppliers", st.session_state["selected_sup_id"])

    selected_sup_name = st.selectbox(
        "🏢 Выберите поставщика", [""] + list(sup_map.keys()), 
        index=current_index, key="sup_selector_widget", on_change=on_sup_change
    )
    
    selected_sup_id = st.session_state["selected_sup_id"]

    if not selected_sup_id:
        st.info("👈 Выберите поставщика в списке.")
        if not is_readonly:
            with st.expander("➕ Добавить нового поставщика"):
                render_supplier_form(session)
        return

    # --- 3. ПОД-НАВИГАЦИЯ ---
    st.markdown(f"## {selected_sup_name}")
    sub_nav = st.segmented_control(
        "Разделы",
        options=["🏠 Карточка", "👤 Контакты", "📋 Проекты", "📝 Опросники"],
        default="🏠 Карточка",
        key="sup_sub_nav",
        label_visibility="collapsed"
    )
    st.markdown("---")

    if sub_nav == "🏠 Карточка":
        render_supplier_card(session, selected_sup_id, is_readonly)
    elif sub_nav == "👤 Контакты":
        render_contacts_manager(session, selected_sup_id, is_readonly)
    elif sub_nav == "📋 Проекты":
        render_datasets_subtab(session, selected_sup_id, is_readonly)
    elif sub_nav == "📝 Опросники":
        render_surveys_manager(session, selected_sup_id, is_readonly)

# ==========================================
# 🏠 КАРТОЧКА И ФОРМА
# ==========================================

def render_supplier_card(session, selected_sup_id, is_readonly):
    sup_data = query_db("SELECT * FROM suppliers WHERE supplier_id = :sid", {"sid": selected_sup_id}).iloc[0]
    
    # 🟢 Визуальная индикация статусов
    c_stat1, c_stat2 = st.columns(2)
    with c_stat1:
        if sup_data.get('is_mandatory'): 
            st.warning("⭐ **Поставщик ОНПД**")
    with c_stat2:
        if sup_data.get('is_gov_agency'): 
            st.info("🏛 **Государственный орган**")
    
    col_info, col_edit = st.columns([2, 1])
    if "sup_edit_mode" not in st.session_state: st.session_state["sup_edit_mode"] = False
            
    with col_info:
        for col, label in RU_LABELS.items():
            if col in ["supplier_id", "supplier_name", "is_mandatory", "is_gov_agency"]: continue
            if pd.notna(sup_data.get(col)) and str(sup_data[col]).strip() != "":
                st.write(f"**{label}:** {sup_data[col]}")
    
    with col_edit:
        if not is_readonly:
            if st.button("✏️ Редактировать реквизиты", width='stretch'):
                st.session_state["sup_edit_mode"] = not st.session_state["sup_edit_mode"]; st.rerun()
    
    if st.session_state["sup_edit_mode"]:
        with st.expander("📝 Форма редактирования", expanded=True):
            render_supplier_form(session, sup_data)

def render_supplier_form(session, existing_data=None):
    is_editing = existing_data is not None
    with st.form("supplier_form_main"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Наименование *", value=existing_data['supplier_name'] if is_editing else "")
            addr = st.text_input("Адрес", value=existing_data['supplier_address'] if is_editing else "")
            is_mand = st.checkbox("Поставщик ОНПД", value=bool(existing_data['is_mandatory']) if is_editing else False)
            # 🟢 Новое поле в форме
            is_gov = st.checkbox("Государственный орган", value=bool(existing_data.get('is_gov_agency', False)) if is_editing else False)
        with col2:
            phone = st.text_input("Телефон", value=existing_data['supplier_phone'] if is_editing else "")
            mgr = st.text_input("Руководитель", value=existing_data['supplier_manager'] if is_editing else "")
            email = st.text_input("Email", value=existing_data['supplier_email'] if is_editing else "")
            site = st.text_input("Сайт", value=existing_data['supplier_website'] if is_editing else "")
        
        notes = st.text_area("Примечание", value=existing_data['supplier_notes'] if is_editing else "")

        if st.form_submit_button("💾 Сохранить"):
            if not name: 
                st.error("Наименование обязательно")
                return
            try:
                target_id = int(existing_data['supplier_id']) if is_editing else None
                params = {
                    "n": name, "a": addr, "p": phone, "m": mgr, "em": email, "w": site, 
                    "nt": notes, "is_m": is_mand, "is_g": is_gov, "id": target_id
                }
                
                if is_editing:
                    log_action(st.session_state["auth"]["user_id"], "UPDATE_SUPPLIER_REQS", "suppliers", target_id, 
                               old={"name": existing_data['supplier_name']}, new={"name": name})
                    
                    session.execute(text("""
                        UPDATE suppliers SET 
                            supplier_name=:n, supplier_address=:a, 
                            supplier_phone=:p, supplier_manager=:m, 
                            supplier_email=:em, supplier_website=:w, supplier_notes=:nt,
                            is_mandatory=:is_m, is_gov_agency=:is_g 
                        WHERE supplier_id=:id
                    """), params)
                else:
                    res = session.execute(text("""
                        INSERT INTO suppliers (
                            supplier_name, supplier_address, supplier_phone, supplier_manager, 
                            supplier_email, supplier_website, supplier_notes, is_mandatory, is_gov_agency
                        ) VALUES (:n, :a, :p, :m, :em, :w, :nt, :is_m, :is_g) RETURNING supplier_id
                    """), params)
                    new_id = res.scalar()
                    log_action(st.session_state["auth"]["user_id"], "CREATE_SUPPLIER", "suppliers", int(new_id), new={"name": name})

                session.commit()
                clear_cache()
                st.session_state["sup_edit_mode"] = False
                st.toast("✅ Реквизиты сохранены!")
                import time
                time.sleep(0.5)
                st.rerun()

            except Exception as e:
                st.error(f"Ошибка БД: {e}")
                session.rollback()

# ==========================================
# ГЕНЕРАТОР СЕТКИ КАРТОЧЕК ПРОЕКТОВ
# ==========================================

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


# ==========================================
# 📋 ПРОЕКТЫ И СОСТАВ (3 КОЛОНКИ)
# ==========================================

def render_datasets_subtab(session, selected_sup_id, is_readonly):
    """Улучшенное управление проектами (3 колонки): Проекты | Состав | Управление"""
    
    # 1. Загружаем проекты поставщика
    projs_df = query_db("""
        SELECT project_id, project_name FROM projects WHERE supplier_id = :sid ORDER BY project_name
    """, {"sid": selected_sup_id})

    col_projs, col_items, col_ctrl = st.columns([0.25, 0.4, 0.35])

    # --- КОЛОНКА 1: СПИСОК ПРОЕКТОВ ---
    current_proj_id = None
    with col_projs:
        st.markdown("##### 📁 Проекты")
        if projs_df.empty:
            st.info("Нет проектов")
        else:
            selection = st.dataframe(
                projs_df[["project_name"]], width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key=f"sup_proj_list_df_{selected_sup_id}"
            )
            selected_rows = selection.get("selection", {}).get("rows", [])
            
            # Проверяем не только наличие выбора, но и физическое наличие строки в DF
            if selected_rows and len(projs_df) > selected_rows[0]:
                row = projs_df.iloc[selected_rows[0]]
                current_proj_id = int(row["project_id"])
                
                # Синхронизация при смене проекта
                if st.session_state.get("last_active_proj_id") != current_proj_id:
                    for k in ["tech_action_mode", "editing_item_id", "show_np_form"]:
                        st.session_state.pop(k, None)
                    st.session_state["last_active_proj_id"] = current_proj_id
            else:
                current_proj_id = None
                # Если проект только что удалили, очищаем состояние
                if "last_active_proj_id" in st.session_state:
                    st.session_state.pop("last_active_proj_id", None)
                st.caption("👈 Выберите проект")

    # --- КОЛОНКА 2: СОСТАВ (ТОЛЬКО ПРОСМОТР) ---
    items_df = pd.DataFrame()
    with col_items:
        st.markdown("##### 📦 Состав наборов")
        if current_proj_id:
            items_df = query_db("""
                SELECT pi.item_id, d.dataset_name, i.info_name, i.info_id, 
                       c.full_name as tech_contact, pi.provision_right, p.project_name
                FROM project_items pi
                JOIN projects p ON pi.project_id = p.project_id
                JOIN datasets d ON pi.dataset_id = d.dataset_id
                JOIN info_types i ON pi.info_id = i.info_id
                LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
                WHERE pi.project_id = :pid ORDER BY d.dataset_name, i.info_name
            """, {"pid": current_proj_id})
            
            if items_df.empty: st.info("В проекте нет наборов")
            else:
                for _, row in items_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**{row['dataset_name']}**")
                        st.markdown(f"_{row['info_name']}_")
                        st.caption(f"⚖️ {row['provision_right']}")
        else:
            st.caption("Выберите проект слева")

    # --- КОЛОНКА 3: ЦЕНТР УПРАВЛЕНИЯ ---
    with col_ctrl:
        st.markdown("##### ⚙️ Управление")
        if not is_readonly:
            if not current_proj_id:
                # 🟢 1а. НОВЫЙ ПРОЕКТ (АВТО-РЕЖИМ)
                if not st.session_state.get("show_np_form"):
                    with st.container(border=True):
                        st.write("Добавить новый проект?")
                        if st.button("➕ Создать новый проект", width='stretch'):
                            st.session_state["show_np_form"] = True; st.rerun()
                else:
                    if st.button("⬅️ Отмена"):
                        st.session_state["show_np_form"] = False; st.rerun()
                    _render_dataset_link_form(session, selected_sup_id, None, projs_df)
            
            else:
                # 🟢 1б. СУЩЕСТВУЮЩИЙ ПРОЕКТ
                action = st.session_state.get("tech_action_mode")
                if not action:
                    with st.container(border=True):
                        if st.button("➕ Добавить новую связь", width='stretch'):
                            st.session_state["tech_action_mode"] = "ADD"; st.rerun()
                        if not items_df.empty:
                            if st.button("✏️ Изменить связь", width='stretch'):
                                st.session_state["tech_action_mode"] = "EDIT"; st.rerun()
                            if st.button("🗑 Удалить связь", width='stretch'):
                                st.session_state["tech_action_mode"] = "DEL"; st.rerun()
                        st.divider()
                        
                        def go_to_full_project_cb(pid):
                            st.session_state["main_nav"] = "📋 Проекты"
                            st.session_state["filter_project_id"] = pid

                        st.button("🔎 Перейти к карточке проекта", width='stretch', type="secondary",
                                  on_click=go_to_full_project_cb, args=(current_proj_id,))
                        
                        # 3. УДАЛЕНИЕ ПРОЕКТА
                        if current_proj_id and not is_readonly:
                            st.divider()
                            if st.button("🗑 Удалить проект", width='stretch', help="Проект должен быть пустым"):
                                # Проверяем, можно ли удалять
                                has_content = session.execute(text("""
                                    SELECT 1 FROM project_items WHERE project_id = :pid 
                                    UNION ALL SELECT 1 FROM project_stages WHERE project_id = :pid LIMIT 1
                                """), {"pid": current_proj_id}).scalar()
                                
                                if has_content:
                                    st.error("❌ Нельзя удалить проект, в котором есть этапы или состав.")
                                else:
                                    try:
                                        p_name = projs_df[projs_df['project_id'] == current_proj_id]['project_name'].iloc[0]
                                        log_action(st.session_state["auth"]["user_id"], "DELETE_PROJECT", "projects", current_proj_id, old={"name": p_name})
                                        
                                        session.execute(text("DELETE FROM projects WHERE project_id = :pid"), {"pid": current_proj_id})
                                        session.commit()
                                        clear_cache()
                                        
                                        # ПРИНУДИТЕЛЬНАЯ ОЧИСТКА СОСТОЯНИЯ ПЕРЕД ПЕРЕЗАГРУЗКОЙ
                                        st.session_state.pop("last_active_proj_id", None)
                                        
                                        # Очищаем ключ самого виджета таблицы, чтобы сбросить выделение строки
                                        if f"sup_proj_list_df_{selected_sup_id}" in st.session_state:
                                            st.session_state.pop(f"sup_proj_list_df_{selected_sup_id}", None)
                                        
                                        st.success("Проект удален"); st.rerun()
                                    except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

                else:
                    if st.button("⬅️ Назад к меню"):
                        for k in ["tech_action_mode", "editing_item_id", "ds_form_proj", "ds_form_ds", "ds_form_i", "ds_form_cont", "ds_form_prov"]:
                            st.session_state.pop(k, None)
                        st.rerun()
                    
                    if action == "ADD": 
                        _render_dataset_link_form(session, selected_sup_id, current_proj_id, projs_df)
                    elif action == "EDIT":
                        opts = {f"{r['dataset_name']} | {r['info_name']}": r for _, r in items_df.iterrows()}
                        sel = st.selectbox("Связь:", [""] + list(opts.keys()), key="edit_link_sel_new")
                        if sel:
                            row = opts[sel]
                            if st.session_state.get("editing_item_id") != int(row['item_id']):
                                st.session_state["editing_item_id"] = int(row['item_id'])
                                st.session_state["ds_form_proj"] = row['project_name']
                                st.session_state["ds_form_ds"] = row['dataset_name']
                                st.session_state["ds_form_i"] = row['info_name']
                                st.session_state["ds_form_cont"] = row['tech_contact'] if pd.notna(row['tech_contact']) else "Не выбран"
                                st.session_state["ds_form_prov"] = row['provision_right']; st.rerun()
                            _render_dataset_link_form(session, selected_sup_id, current_proj_id, projs_df, is_edit=True)
                    elif action == "DEL":
                        opts = {f"{r['dataset_name']} | {r['info_name']}": r for _, r in items_df.iterrows()}
                        sel = st.selectbox("Выберите для удаления:", [""] + list(opts.keys()))
                        if sel and st.button("❌ Подтвердить удаление", width='stretch'):
                            _delete_item_logic(session, selected_sup_id, opts[sel])
        else: st.info("Режим просмотра")

def _render_dataset_link_form(session, supplier_id, current_proj_id, projs_df, is_edit=False):
    """Оптимизированная форма создания и редактирования"""
    
    # 🟢 1. ЛОГИКА ОТОБРАЖЕНИЯ ПРОЕКТА
    if not current_proj_id and not is_edit:
        # Режим нового проекта (Колонка 1 пуста)
        st.session_state["ds_form_proj"] = "(Новый проект)"
        st.text_input("Название нового проекта *", key="ds_form_new_p")
        st.checkbox("Проект Соглашения", key="ds_form_new_p_agr")
    else:
        # Режим добавления/изменения в существующий проект
        proj_names = projs_df["project_name"].tolist()
        # Ищем текущее имя проекта для дефолта
        def_p = projs_df[projs_df['project_id'] == current_proj_id]['project_name'].iloc[0] if current_proj_id else proj_names[0]
        st.selectbox("Проект *", proj_names, index=proj_names.index(def_p), key="ds_form_proj", disabled=is_edit)

    st.divider()

    # 2. НАБОР И ВИД
    dss = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    ds_names = ["(Новый набор)"] + dss["dataset_name"].tolist()
    st.selectbox("Набор данных *", ds_names, key="ds_form_ds", disabled=is_edit)
    
    if st.session_state.get("ds_form_ds") == "(Новый набор)" and not is_edit:
        st.text_input("Имя нового набора", key="ds_form_new_d")
        st.text_input("Имя нового вида", key="ds_form_new_i")
    else:
        d_id_res = dss[dss["dataset_name"] == st.session_state.get("ds_form_ds")]
        if not d_id_res.empty:
            d_id = int(d_id_res.iloc[0]["dataset_id"])
            infos = query_db("SELECT info_id, info_name FROM info_types WHERE dataset_id = :did", {"did": d_id})
            i_names = ["(Новый вид)"] + infos["info_name"].tolist()
            st.selectbox("Вид сведений *", i_names, key="ds_form_i", disabled=is_edit)
            if st.session_state.get("ds_form_i") == "(Новый вид)" and not is_edit:
                st.text_input("Имя нового вида", key="ds_form_new_i_name")

    # 3. ДОП ПАРАМЕТРЫ
    conts = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid", {"sid": int(supplier_id)})
    c_names = ["Не выбран"] + conts["full_name"].tolist()
    st.selectbox("Тех. контакт", c_names, key="ds_form_cont")
    
    prov_opts = ['Протокол не заключён', 'Оператор и Поставщик', 'Только Поставщик', 'Не предоставляется']
    st.selectbox("Право предоставления", prov_opts, key="ds_form_prov")

    # --- СОХРАНЕНИЕ ---
    btn_txt = "💾 Сохранить изменения" if is_edit else "🚀 Создать связь"
    if st.button(btn_txt, type="primary", width='stretch', key="ds_save_btn_final"):
        try:
            # А. Получаем ID проекта
            if st.session_state.ds_form_proj == "(Новый проект)":
                p_name = st.session_state.get("ds_form_new_p", "").strip()
                if not p_name: st.error("Укажите имя проекта"); st.stop()
                p_id = session.execute(text("INSERT INTO projects (supplier_id, project_name, status, is_agreement_project) VALUES (:sid, :pn, 1, :is_agr) RETURNING project_id"),
                                       {"sid": int(supplier_id), "pn": p_name, "is_agr": st.session_state.get("ds_form_new_p_agr", False)}).scalar()
            else:
                p_id = int(projs_df[projs_df["project_name"] == st.session_state.ds_form_proj].iloc[0]["project_id"])

            # Б. Набор и вид
            if not is_edit and st.session_state.ds_form_ds == "(Новый набор)":
                d_id = session.execute(text("INSERT INTO datasets (dataset_name) VALUES (:n) RETURNING dataset_id"), {"n": st.session_state.ds_form_new_d.strip()}).scalar()
                i_id = session.execute(text("INSERT INTO info_types (dataset_id, info_name) VALUES (:did, :n) RETURNING info_id"),
                                       {"did": d_id, "n": st.session_state.ds_form_new_i.strip()}).scalar()
            else:
                d_id = int(dss[dss["dataset_name"] == st.session_state.ds_form_ds].iloc[0]["dataset_id"])
                if not is_edit and st.session_state.ds_form_i == "(Новый вид)":
                    i_id = session.execute(text("INSERT INTO info_types (dataset_id, info_name) VALUES (:did, :n) RETURNING info_id"),
                                           {"did": d_id, "n": st.session_state.ds_form_new_i_name.strip()}).scalar()
                else:
                    i_res = query_db("SELECT info_id FROM info_types WHERE dataset_id=:did AND info_name=:n", {"did": d_id, "n": st.session_state.ds_form_i})
                    i_id = int(i_res.iloc[0]["info_id"])

            # В. Параметры связи
            c_id = int(conts[conts["full_name"] == st.session_state.ds_form_cont].iloc[0]["contact_id"]) if st.session_state.ds_form_cont != "Не выбран" else None
            
            if is_edit:
                session.execute(text("UPDATE project_items SET dataset_id=:did, info_id=:iid, tech_contact_id=:cid, provision_right=CAST(:prov AS data_provision_type) WHERE item_id=:id"),
                                {"did": i_id, "iid": i_id, "cid": c_id, "prov": st.session_state.ds_form_prov, "id": st.session_state.editing_item_id})
            else:
                session.execute(text("INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id, provision_right) VALUES (:pid, :did, :iid, :cid, CAST(:prov AS data_provision_type))"),
                                {"pid": p_id, "did": d_id, "iid": i_id, "cid": c_id, "prov": st.session_state.ds_form_prov})

            session.commit(); clear_cache(); st.success("Успешно!"); st.rerun()
        except Exception as e:
            st.error(f"Ошибка БД: {e}"); session.rollback()

def _delete_item_logic(session, supplier_id, item_row):
    """Вынесенная логика удаления, адаптированная под JSONB в project_stages"""
    item_id = int(item_row['item_id'])
    
    # 🟢 ОБНОВЛЕНО: Проверка наличия технологических этапов в единой таблице
    # Используем оператор @> для поиска ID набора внутри JSONB-массива
    check_stages_query = """
        SELECT 1 FROM project_stages 
        WHERE affected_item_ids @> CAST(:id_json AS JSONB) 
        LIMIT 1
    """
    has_stages = query_db(check_stages_query, {"id_json": f"[{item_id}]"})
    
    has_surveys = query_db("""
        SELECT 1 FROM surveys s JOIN survey_info_types sit ON s.survey_id = sit.survey_id
        WHERE s.supplier_id = :sid AND sit.info_id = :iid LIMIT 1
    """, {"sid": int(supplier_id), "iid": int(item_row['info_id'])})
    
    if not has_stages.empty or not has_surveys.empty:
        st.error("Удаление заблокировано: по этой связи есть история (этапы или опросники) в базе.")
    else:
        session.execute(text("DELETE FROM project_items WHERE item_id = :id"), {"id": item_id})
        session.commit(); clear_cache(); st.success("Удалено!"); st.rerun()

# ==========================================
# 👤 КОНТАКТЫ (3 КОЛОНКИ)
# ==========================================

def render_contacts_manager(session, supplier_id, is_readonly):
    """Улучшенное управление контактами: Список | Детали | Управление"""
    # 1. Загружаем данные (убеждаемся, что берем все поля)
    contacts_df = query_db("""
        SELECT contact_id, full_name, position, email, phone, notes
        FROM contacts WHERE supplier_id = :sid ORDER BY full_name
    """, {"sid": supplier_id})
    
    col_list, col_view, col_form = st.columns([0.25, 0.35, 0.4])

    with col_list:
        st.markdown("##### 👥 Список")
        if contacts_df.empty:
            is_selected = False
        else:
            selection = st.dataframe(
                contacts_df[["full_name"]], width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key=f"cl_{supplier_id}"
            )
            selected_rows = selection.get("selection", {}).get("rows", [])
            is_selected = len(selected_rows) > 0
            
            if is_selected:
                curr_contact = contacts_df.iloc[selected_rows[0]]
                # Сброс формы при переключении между людьми
                if st.session_state.get("last_cid") != int(curr_contact['contact_id']):
                    st.session_state["show_c_form"] = False
                    st.session_state["last_cid"] = int(curr_contact['contact_id'])
            else:
                # Если никто не выбран, убеждаемся, что режим редактирования выключен
                st.session_state["show_c_form"] = False

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
            st.info("👈 Выберите контакт")

    with col_form:
        if not is_readonly:
            st.markdown("##### ⚙️ Управление")
            if is_selected:
                # РЕЖИМ: ВЫБРАН СУЩЕСТВУЮЩИЙ
                if not st.session_state.get("show_c_form"):
                    with st.container(border=True):
                        st.write("Действие для выбранного контакта:")
                        if st.button("✏️ Редактировать данные", width='stretch', key="btn_edit_c"):
                            st.session_state["show_c_form"] = True
                            st.rerun()
                        if st.button("🗑 Удалить", type="secondary", width='stretch', key="btn_del_c"):
                            try:
                                log_action(st.session_state["auth"]["user_id"], "DELETE_CONTACT", "contacts", int(curr_contact['contact_id']), old={"name": curr_contact['full_name']})
                                session.execute(text("DELETE FROM contacts WHERE contact_id = :id"), {"id": int(curr_contact['contact_id'])})
                                session.commit(); clear_cache(); st.rerun()
                            except Exception as e: st.error(f"Ошибка удаления: {e}")
                else:
                    if st.button("⬅️ Назад к меню"):
                        st.session_state["show_c_form"] = False
                        st.rerun()
                    _render_contact_form_standalone(session, supplier_id, curr_contact)
            else:
                # РЕЖИМ: НИКТО НЕ ВЫБРАН (СОЗДАНИЕ)
                if not st.session_state.get("show_c_form_new"):
                    with st.container(border=True):
                        st.write("Хотите добавить нового человека?")
                        if st.button("➕ Создать новый контакт", width='stretch', key="btn_new_c"):
                            st.session_state["show_c_form_new"] = True
                            st.rerun()
                else:
                    if st.button("⬅️ Отмена"):
                        st.session_state["show_c_form_new"] = False
                        st.rerun()
                    _render_contact_form_standalone(session, supplier_id)

def _render_contact_form_standalone(session, supplier_id, data=None):
    """Полная форма контакта: все поля + выход из режима правки"""
    is_edit = data is not None
    cid = data['contact_id'] if is_edit else "new"
    
    with st.container(border=True):
        fn = st.text_input("ФИО *", value=data['full_name'] if is_edit else "", key=f"f_{cid}")
        pos = st.text_input("Должность", value=data['position'] if is_edit else "", key=f"p_{cid}")
        # 🟢 ВОЗВРАЩЕННЫЕ ПОЛЯ:
        em = st.text_input("Email", value=data['email'] if is_edit else "", key=f"e_{cid}")
        ph = st.text_input("Телефон", value=data['phone'] if is_edit else "", key=f"ph_{cid}")
        nt = st.text_area("Примечание", value=data['notes'] if is_edit else "", key=f"n_{cid}", height=100)
        
        if st.button("💾 Сохранить изменения" if is_edit else "💾 Создать", type="primary", width='stretch', key=f"s_{cid}"):
            if not fn:
                st.error("ФИО обязательно")
                return
            try:
                params = {"n": fn, "p": pos, "e": em, "ph": ph, "nt": nt, "sid": int(supplier_id)}
                if is_edit:
                    params["id"] = int(cid)
                    log_action(st.session_state["auth"]["user_id"], "UPDATE_CONTACT", "contacts", params["id"], new={"name": fn})
                    session.execute(text("""
                        UPDATE contacts SET full_name=:n, position=:p, email=:e, phone=:ph, notes=:nt 
                        WHERE contact_id=:id
                    """), params)
                else:
                    res = session.execute(text("""
                        INSERT INTO contacts (full_name, supplier_id, position, email, phone, notes) 
                        VALUES (:n, :sid, :p, :e, :ph, :nt) RETURNING contact_id
                    """), params)
                    new_id = res.scalar()
                    log_action(st.session_state["auth"]["user_id"], "CREATE_CONTACT", "contacts", int(new_id), new={"name": fn})

                session.commit()
                clear_cache()
                
                # 🟢 МАГИЯ ВЫХОДА: сбрасываем флаги показа формы
                st.session_state["show_c_form"] = False
                st.session_state["show_c_form_new"] = False
                st.toast("✅ Контакт сохранен")
                
                import time
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка БД: {e}")
                session.rollback()

# ==========================================
# 📝 ОПРОСНИКИ (SURVEYS)
# ==========================================

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