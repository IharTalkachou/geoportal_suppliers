import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache
from ui.bureaucracy_tab import render_bureaucracy_tab
from ui.technology_tab import render_technology_tab
from config.auth import log_action

def render_project_dashboard(session, user_role="user"):
    st.subheader("📂 Управление проектами")
    is_readonly = (user_role == "user")

    # 🔹 Инициализация версии списка проектов (гарантирует сброс кэша виджета)
    if "proj_list_ver" not in st.session_state:
        st.session_state["proj_list_ver"] = 0
        
    if "dash_edit_mode" not in st.session_state:
        st.session_state.dash_edit_mode = False
    if "selected_project_id" not in st.session_state:
        st.session_state.selected_project_id = None

    # 🔍 1. Зависимые фильтры
    suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(suppliers["supplier_name"], suppliers["supplier_id"]))
    
    # ✅ ИСПРАВЛЕНИЕ 2: Полная очистка состояния при смене поставщика
    def _on_supplier_change():
        # 1. Сбрасываем глобальный ID
        st.session_state["selected_project_id"] = None
        
        # 2. Высчитываем текущий ключ виджета "Проект" и удаляем его из памяти.
        # Без своей памяти виджет принудительно посмотрит на параметр index=0.
        current_ver = st.session_state.get("proj_list_ver", 0)
        widget_key = f"dash_proj_filter_v{current_ver}"
        if widget_key in st.session_state:
            del st.session_state[widget_key]

    selected_sup = st.selectbox(
        "🔍 Поставщик", 
        ["Все"] + list(sup_map.keys()), 
        key="dash_sup_filter",
        on_change=_on_supplier_change
    )
    
    # Загружаем проекты
    cache_buster = st.session_state.get("proj_list_ver", 0)
    
    if selected_sup == "Все":
        projects = query_db(f"SELECT project_id, project_name FROM projects ORDER BY project_name /* v{cache_buster} */")
    else:
        projects = query_db(f"SELECT project_id, project_name FROM projects WHERE supplier_id = :sid ORDER BY project_name /* v{cache_buster} */", {"sid": sup_map[selected_sup]})

    proj_map = dict(zip(projects["project_id"], projects["project_name"]))
    proj_options = [None] + list(proj_map.keys())

    # ✅ ИСПРАВЛЕНИЕ 2: Вычисляем индекс, чтобы он либо сбросился в 0, либо удержал выбранный проект
    current_proj = st.session_state.get("selected_project_id")
    if current_proj in proj_options:
        default_idx = proj_options.index(current_proj)
    else:
        default_idx = 0

    selected_proj_id = st.selectbox(
        "🔍 Проект", 
        proj_options, 
        index=default_idx, # Управляем выбором через индекс
        format_func=lambda x: proj_map.get(x, "Выберите проект..."), 
        # ✅ ИСПРАВЛЕНИЕ 3: Динамический ключ. При переименовании cache_buster увеличится,
        # ключ изменится, и Streamlit ПРИНУДИТЕЛЬНО перерисует имена проектов!
        key=f"dash_proj_filter_v{cache_buster}" 
    )
    
    # Валидация и сохранение ID (стало проще и чище)
    if selected_proj_id is not None:
        try:
            st.session_state["selected_project_id"] = int(selected_proj_id)
        except (ValueError, TypeError):
            st.session_state["selected_project_id"] = None
    else:
        st.session_state["selected_project_id"] = None

    # Если проект не выбран или невалиден — показываем подсказку
    if not st.session_state.get("selected_project_id"):
        st.info("👆 Выберите поставщика и проект для начала работы.")
        return

    # Безопасное приведение к int
    try:
        proj_id_int = int(st.session_state["selected_project_id"])
    except (ValueError, TypeError):
        st.error("⚠️ Некорректный идентификатор проекта. Пожалуйста, выберите проект заново.")
        st.session_state["selected_project_id"] = None
        st.rerun()

    # 📋 2. Карточка проекта (используем валидный proj_id_int)
    proj_data = query_db("""
        SELECT p.project_id, p.supplier_id, p.project_name, 
               s.supplier_name, c.full_name, rs.status_name, p.notes
        FROM projects p
        LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
        LEFT JOIN contacts c ON p.main_contact_id = c.contact_id
        LEFT JOIN ref_statuses rs ON p.status = rs.status_id
        WHERE p.project_id = :pid
    """, {"pid": proj_id_int}).iloc[0]

    st.markdown("### 📋 Детали проекта")
    st.metric("📂 Проект", proj_data['project_name'])
    st.metric("🏢 Поставщик", proj_data['supplier_name'])
    st.metric("📊 Статус", proj_data['status_name'])
    st.metric("👤 Контакт", proj_data['full_name'] or "Не указан")

    col_note, col_btn = st.columns([3, 1])
    with col_note:
        st.markdown(f"**📝 Примечание:** {proj_data['notes'] or '-'}")
    with col_btn:
        if not is_readonly and st.button("✏️ Изменить реквизиты", type="secondary", use_container_width=True):
            st.session_state.dash_edit_mode = not st.session_state.dash_edit_mode

    st.markdown("---")

    # 📝 3. Форма редактирования реквизитов (только admin/editor)
    if not is_readonly and st.session_state.dash_edit_mode:
        with st.form("edit_proj_form"):
            st.markdown("#### 📝 Редактирование реквизитов")
            proj_supplier_id = int(proj_data['supplier_id'])
            
            sup_list = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
            cont_list = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid ORDER BY full_name", {"sid": proj_supplier_id})
            stat_list = query_db("SELECT status_id, status_name FROM ref_statuses ORDER BY status_name")

            sup_names = sup_list["supplier_name"].tolist()
            stat_names = stat_list["status_name"].tolist()
            cont_names = cont_list["full_name"].tolist() if not cont_list.empty else []

            sup_idx = sup_names.index(proj_data['supplier_name']) if proj_data['supplier_name'] in sup_names else 0
            stat_idx = stat_names.index(proj_data['status_name']) if proj_data['status_name'] in stat_names else 0
            cont_idx = 0
            if pd.notna(proj_data['full_name']) and proj_data['full_name'] in cont_names:
                cont_idx = cont_names.index(proj_data['full_name']) + 1

            col1, col2 = st.columns(2)
            with col1:
                p_name = st.text_input("Название проекта", value=proj_data['project_name'])
                p_sup = st.selectbox("Поставщик", sup_names, index=sup_idx)
                p_stat = st.selectbox("Статус", stat_names, index=stat_idx)
            with col2:
                p_contact = st.selectbox("Основной контакт", ["Не указан"] + cont_names, index=cont_idx)
                p_notes = st.text_area("Примечание", value=proj_data['notes'] or "")

            if st.form_submit_button("💾 Сохранить изменения проекта", type="primary"):
                try:
                    sup_id = int(sup_list[sup_list["supplier_name"]==p_sup]["supplier_id"].iloc[0])
                    stat_id = int(stat_list[stat_list["status_name"]==p_stat]["status_id"].iloc[0])
                    cont_id = None
                    if p_contact != "Не указан":
                        matching = cont_list[cont_list["full_name"]==p_contact]
                        if not matching.empty: cont_id = int(matching["contact_id"].iloc[0])

                    log_action(st.session_state["auth"]["user_id"], "UPDATE_PROJECT", "projects", int(selected_proj_id),
                               old={"name": proj_data['project_name'], "status": proj_data['status_name']},
                               new={"name": p_name, "status": p_stat})
                    session.execute(text("""UPDATE projects SET project_name=:name, supplier_id=:sup, main_contact_id=:cont,
                        status=:stat, notes=:notes WHERE project_id=:id"""), 
                    {
                        "name": p_name, "sup": sup_id, "cont": cont_id, "stat": stat_id,
                        "notes": p_notes, "id": int(selected_proj_id)
                    })
                    session.commit(); clear_cache()
                    # 🔹 Увеличиваем версию → виджет принудительно перестроит метки
                    st.session_state["proj_list_ver"] += 1
                    
                    st.session_state.dash_edit_mode = False
                    st.success("✅ Реквизиты обновлены!"); st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}"); session.rollback()
        st.divider()

    # ==========================================
    # БЛОК: СОСТАВ ПРОЕКТА (Реактивный CRUD без st.form)
    # ==========================================
    st.markdown("### 📦 Состав проекта (Наборы → Виды)")
    
    datasets = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    info_types = query_db("SELECT info_id, info_name, dataset_id FROM info_types ORDER BY info_name")
    
    ds_map = dict(zip(datasets["dataset_name"], datasets["dataset_id"]))
    info_map = {row["info_name"]: {"id": row["info_id"], "ds_id": row["dataset_id"]} for _, row in info_types.iterrows()}
    ds_names = list(ds_map.keys())

    items_df = query_db("""
        SELECT pi.item_id, d.dataset_name, i.info_name, c.full_name as tech_contact
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
        WHERE pi.project_id = :pid
        ORDER BY d.dataset_name, i.info_name
    """, {"pid": proj_id_int})

    st.dataframe(items_df[["dataset_name", "info_name", "tech_contact"]], 
                 use_container_width=True, hide_index=True,
                 column_config={"dataset_name": "Набор данных", "info_name": "Вид сведений", "tech_contact": "Тех. контакт"})

    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать элемент состава"):
            # 1. Выбор элемента для редактирования
            item_options = ["(Добавить новый)"]
            item_ids_map = {}
            for _, row in items_df.iterrows():
                label = f"{row['dataset_name']} → {row['info_name']}"
                item_options.append(label)
                item_ids_map[label] = row["item_id"]

            sel_item = st.selectbox("Выберите элемент:", item_options, key="crud_item_sel")
            is_editing = sel_item != "(Добавить новый)"

            # 🔍 FIX 1: Авто-подстановка текущих значений при выборе существующего элемента
            if is_editing:
                curr = items_df[items_df["item_id"] == item_ids_map[sel_item]].iloc[0]
                st.session_state["crud_ds"] = curr["dataset_name"]
                st.session_state["crud_info"] = curr["info_name"]
                st.session_state["crud_cont"] = curr["tech_contact"] if pd.notna(curr["tech_contact"]) else "Не выбран"
            else:
                # Сброс при переключении на "Добавить новый"
                if st.session_state.get("crud_item_sel_prev") != sel_item:
                    st.session_state["crud_ds"] = ds_names[0]
                    st.session_state["crud_info"] = "(Нет видов для этого набора)"
                    st.session_state["crud_cont"] = "Не выбран"
            
            st.session_state["crud_item_sel_prev"] = sel_item

            # 2. Набор данных
            ds_idx = ds_names.index(st.session_state.get("crud_ds", ds_names[0])) if st.session_state.get("crud_ds") in ds_names else 0
            sel_ds = st.selectbox("Набор данных *", ds_names, index=ds_idx, key="crud_ds")

            # 🔍 FIX 2: Динамическая фильтрация видов по набору
            valid_infos = [k for k, v in info_map.items() if v["ds_id"] == ds_map[sel_ds]]
            if not valid_infos: valid_infos = ["(Нет видов для этого набора)"]
            
            # Сброс выбора, если текущий вид не принадлежит новому набору
            if st.session_state.get("crud_info") not in valid_infos:
                st.session_state["crud_info"] = valid_infos[0]

            info_idx = valid_infos.index(st.session_state.get("crud_info", valid_infos[0]))
            sel_info = st.selectbox("Вид сведений *", valid_infos, index=info_idx, key="crud_info")

            # 🔍 FIX 3: Контакты фильтруются по поставщику проекта
            proj_sup_id = int(proj_data['supplier_id'])
            sup_contacts = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid ORDER BY full_name", {"sid": proj_sup_id})
            sup_cont_map = dict(zip(sup_contacts["full_name"], sup_contacts["contact_id"]))
            cont_options = ["Не выбран"] + list(sup_cont_map.keys())

            if st.session_state.get("crud_cont") not in cont_options:
                st.session_state["crud_cont"] = "Не выбран"
                
            cont_idx = cont_options.index(st.session_state["crud_cont"])
            sel_cont = st.selectbox("Тех. контакт", cont_options, index=cont_idx, key="crud_cont")

            # 3. Кнопки действий
            col_btn, col_del = st.columns([3, 1])
            with col_btn:
                if st.button("💾 Сохранить", type="primary", key="crud_save"):
                    sel_ds = st.session_state["crud_ds"]
                    sel_info = st.session_state["crud_info"]
                    sel_cont = st.session_state["crud_cont"]

                    if sel_info == "(Нет видов для этого набора)":
                        st.warning("⚠️ Выберите корректный набор данных и вид сведений.")
                        st.stop()

                    ds_id = ds_map[sel_ds]
                    info_id = info_map[sel_info]["id"]
                    cont_id = sup_cont_map.get(sel_cont) if sel_cont != "Не выбран" else None

                    try:
                        if not is_editing:
                            exists = session.execute(text("""
                                SELECT 1 FROM project_items WHERE project_id = :pid AND dataset_id = :ds AND info_id = :info
                            """), {"pid": selected_proj_id, "ds": ds_id, "info": info_id}).scalar()
                            if exists:
                                st.warning("⚠️ Эта связка уже существует в составе проекта.")
                                st.stop()
                            session.execute(text("INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id) VALUES (:pid, :ds, :info, :cont)"),
                                        {"pid": selected_proj_id, "ds": ds_id, "info": info_id, "cont": cont_id})
                            log_action(st.session_state["auth"]["user_id"], "CREATE_PROJECT_ITEM", "project_items",
                                   new={"project_id": selected_proj_id, "dataset": sel_ds, "info": sel_info})
                        else:
                            # 🔍 Читаем ТЕКУЩИЕ значения из items_df ПЕРЕД обновлением
                            curr = items_df[items_df["item_id"] == item_ids_map[sel_item]].iloc[0]
                            old_ds = curr["dataset_name"]
                            old_info = curr["info_name"]
                            old_cont = curr["tech_contact"] if pd.notna(curr["tech_contact"]) else "Не выбран"

                            session.execute(text("UPDATE project_items SET dataset_id=:ds, info_id=:info, tech_contact_id=:cont WHERE item_id=:id"),
                                        {"ds": ds_id, "info": info_id, "cont": cont_id, "id": int(item_ids_map[sel_item])})
                            log_action(st.session_state["auth"]["user_id"], "UPDATE_PROJECT_ITEM", "project_items", int(item_ids_map[sel_item]),
                                   old={"dataset": old_ds, "info": old_info, "contact": old_cont}, 
                                   new={"dataset": sel_ds, "info": sel_info, "contact": sel_cont})

                        session.commit(); clear_cache()
                        st.success("✅ Состав проекта обновлён!"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}"); session.rollback()

            with col_del:
                if is_editing and st.button("🗑 Удалить", type="secondary", key="crud_del"):
                    try:
                        # 🔍 Читаем значения для лога перед удалением
                        curr = items_df[items_df["item_id"] == item_ids_map[sel_item]].iloc[0]
                        old_ds = curr["dataset_name"]
                        old_info = curr["info_name"]
                        
                        log_action(st.session_state["auth"]["user_id"], "DELETE_PROJECT_ITEM", "project_items", int(item_ids_map[sel_item]), 
                                   old={"dataset": old_ds, "info": old_info})
                        session.execute(text("DELETE FROM project_items WHERE item_id = :id"), {"id": int(item_ids_map[sel_item])})
                        session.commit(); clear_cache()
                        st.success("🗑 Элемент удалён!"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}"); session.rollback()

    st.markdown("---")
    
    tab_buro, tab_tech = st.tabs(["📜 Бюрократия", "⚙️ Технология"])
    with tab_buro:
        render_bureaucracy_tab(session, proj_id_int, user_role=user_role)  # ✅ proj_id_int
    with tab_tech:
        render_technology_tab(session, proj_id_int, user_role=user_role)   # ✅ proj_id_int