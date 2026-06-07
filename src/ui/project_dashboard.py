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

    # 1. 🛡️ ПЕРВИЧНАЯ ИНИЦИАЛИЗАЦИЯ И ОЧИСТКА
    if "proj_list_ver" not in st.session_state:
        st.session_state["proj_list_ver"] = 0
    
    # Санитарная проверка: если в ID попал текст - сносим его немедленно
    cur_id = st.session_state.get("selected_project_id")
    if cur_id is not None and not isinstance(cur_id, int):
        if isinstance(cur_id, str) and cur_id.isdigit():
            st.session_state["selected_project_id"] = int(cur_id)
        else:
            st.session_state["selected_project_id"] = None

    # 2. 🔄 КОЛЛБЭК СМЕНЫ ПОСТАВЩИКА
    def _on_supplier_change():
        # Сбрасываем выбранный проект
        st.session_state["selected_project_id"] = None
        # Увеличиваем версию — это заставит Streamlit ПЕРЕСОЗДАТЬ selectbox проекта
        st.session_state["proj_list_ver"] += 1
        st.session_state.dash_edit_mode = False

    # 🔍 3. ГЛОБАЛЬНЫЕ ФИЛЬТРЫ
    suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(suppliers["supplier_name"], suppliers["supplier_id"]))
    
    selected_sup = st.selectbox(
        "🏢 Поставщик", 
        ["Все"] + list(sup_map.keys()), 
        key="dash_sup_filter",
        on_change=_on_supplier_change # 👈 Триггер сброса
    )
    
    # Загружаем проекты для текущего поставщика
    current_ver = st.session_state["proj_list_ver"]
    if selected_sup == "Все":
        projects = query_db(f"SELECT project_id, project_name FROM projects ORDER BY project_name /* v{current_ver} */")
    else:
        projects = query_db(f"SELECT project_id, project_name FROM projects WHERE supplier_id = :sid ORDER BY project_name /* v{current_ver} */", 
                            {"sid": sup_map[selected_sup]})

    # Формируем карту ID -> Название (строго int для ключей)
    proj_map = {int(r["project_id"]): r["project_name"] for _, r in projects.iterrows()}
    proj_options = [None] + list(proj_map.keys())

    # Проверяем, валиден ли текущий ID для этого списка
    current_proj_id = st.session_state.get("selected_project_id")
    if current_proj_id not in proj_options:
        current_proj_id = None
        st.session_state["selected_project_id"] = None

    # 4. 🎯 ВИДЖЕТ ВЫБОРА ПРОЕКТА С ВЕРСИОНИРОВАНИЕМ
    # Мы меняем key каждый раз при смене поставщика (v0, v1, v2...)
    # Это гарантирует, что в поле не останется "призрака" старого проекта
    selected_proj_id = st.selectbox(
        "🔍 Проект", 
        proj_options, 
        index=0 if current_proj_id is None else proj_options.index(current_proj_id),
        format_func=lambda x: proj_map.get(x, "Выберите проект..."), 
        key=f"dash_project_selector_v{current_ver}" 
    )
    
    # Синхронизируем выбор в основное состояние
    if selected_proj_id != st.session_state.get("selected_project_id"):
        st.session_state["selected_project_id"] = selected_proj_id
        st.rerun()

    # 5. 🛑 ПРЕДОХРАНИТЕЛЬ
    if st.session_state.get("selected_project_id") is None:
        st.info("👆 Выберите поставщика и проект для начала работы.")
        return 

    # ТЕПЕРЬ ТУТ ГАРАНТИРОВАННО ЧИСЛО
    proj_id_int = int(st.session_state["selected_project_id"])

    # ==========================================
    # 📑 ОСНОВНЫЕ ТАБЫ ПРОЕКТА
    # ==========================================
    tab_passport, tab_composition, tab_stages = st.tabs([
        "📄 Паспорт проекта", "📦 Состав проекта", "📈 Этапы и прогресс"
    ])

    # ------------------------------------------
    # ТАБ 1: ПАСПОРТ ПРОЕКТА
    # ------------------------------------------
    with tab_passport:
        # Загружаем основные данные проекта
        proj_data = query_db("""
            SELECT p.project_id, p.supplier_id, p.project_name, 
                   s.supplier_name, c.full_name, rs.status_name, p.notes,
                   p.is_agreement_project
            FROM projects p
            LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
            LEFT JOIN contacts c ON p.main_contact_id = c.contact_id
            LEFT JOIN ref_statuses rs ON p.status = rs.status_id
            WHERE p.project_id = :pid
        """, {"pid": proj_id_int}).iloc[0]
      
        # 🔹 АВТОМАТИЧЕСКИЙ СБОР ОТВЕТСТВЕННЫХ ИЗ ВСЕХ ЭТАПОВ
        # Собираем уникальные имена из Бюрократии И Технологии этого проекта
        combined_resp_query = """
            SELECT DISTINCT u.display_name 
            FROM users u
            WHERE u.user_id IN (
                -- Ответственные из документарных этапов
                SELECT responsible_id FROM project_stages WHERE project_id = :pid AND responsible_id IS NOT NULL
                UNION
                -- Ответственные из технологических этапов всех элементов состава
                SELECT responsible_id FROM item_stages 
                WHERE item_id IN (SELECT item_id FROM project_items WHERE project_id = :pid) 
                AND responsible_id IS NOT NULL
            )
        """
        
        resp_df = query_db(combined_resp_query, {"pid": proj_id_int})
        responsibles_str = ", ".join(resp_df["display_name"].tolist()) if not resp_df.empty else "Не назначены"

        st.markdown(f"**📂 Проект:** {proj_data['project_name']}")
        if proj_data.get('is_agreement_project'):
            st.info("📜 **Это проект первичного подключения (заключение Соглашения)**")
        st.markdown(f"**📊 Статус:** {proj_data['status_name']}")
        st.markdown(f"**👤 Основной контакт:** {proj_data['full_name'] or 'Не указан'}")
        '''# 🔹 ВЫВОД НОВОГО ПОЛЯ
        st.markdown(f"**👥 Ответственные сотрудники:** {responsibles_str}")'''
        # Теперь это поле заполняется само!
        st.markdown(f"**👥 Команда проекта (из этапов):** {responsibles_str}")
        st.markdown(f"**📝 Примечание:** {proj_data['notes'] or '-'}")

        if not is_readonly:
            st.write("")
            if st.button("✏️ Изменить реквизиты проекта", type="secondary"):
                st.session_state.dash_edit_mode = not st.session_state.dash_edit_mode
            
            if st.session_state.dash_edit_mode:
                with st.form("edit_proj_form"):
                    st.markdown("#### 📝 Редактирование реквизитов")
                    
                    # Подготовка списков для формы
                    sup_list = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
                    cont_list = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid ORDER BY full_name", {"sid": int(proj_data['supplier_id'])})
                    stat_list = query_db("SELECT status_id, status_name FROM ref_statuses ORDER BY status_name")
                    
                    sup_names = sup_list["supplier_name"].tolist()
                    stat_names = stat_list["status_name"].tolist()
                    cont_names = cont_list["full_name"].tolist() if not cont_list.empty else []

                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        p_name_in = st.text_input("Название проекта", value=proj_data['project_name'])
                        p_sup_in = st.selectbox("Поставщик", sup_names, index=sup_names.index(proj_data['supplier_name']) if proj_data['supplier_name'] in sup_names else 0)
                        p_is_agr = st.checkbox("Проект включает заключение Соглашения", value=bool(proj_data['is_agreement_project']))
                        p_stat_in = st.selectbox("Статус", stat_names, index=stat_names.index(proj_data['status_name']) if proj_data['status_name'] in stat_names else 0)
                    with col_f2:
                        p_contact_in = st.selectbox("Основной контакт", ["Не указан"] + cont_names, index=cont_names.index(proj_data['full_name'])+1 if proj_data['full_name'] in cont_names else 0)
                    
                    p_notes_in = st.text_area("Примечание", value=proj_data['notes'] or "")

                    if st.form_submit_button("💾 Сохранить изменения", type="primary"):
                        try:
                            new_sup_id = int(sup_list[sup_list["supplier_name"]==p_sup_in]["supplier_id"].iloc[0])
                            new_stat_id = int(stat_list[stat_list["status_name"]==p_stat_in]["status_id"].iloc[0])
                            new_cont_id = int(cont_list[cont_list["full_name"]==p_contact_in]["contact_id"].iloc[0]) if p_contact_in != "Не указан" else None

                            # 1. Обновляем основную таблицу
                            session.execute(text("""UPDATE projects SET project_name=:name, supplier_id=:sup, 
                                main_contact_id=:cont, status=:stat, notes=:notes, is_agreement_project=:is_agr WHERE project_id=:id"""), 
                            {"name": p_name_in, "sup": new_sup_id, "cont": new_cont_id, "stat": new_stat_id, "notes": p_notes_in, "is_agr": p_is_agr, "id": proj_id_int})
                            
                            session.commit(); clear_cache()
                            st.session_state["proj_list_ver"] += 1
                            st.session_state.dash_edit_mode = False
                            st.success("✅ Данные проекта и список ответственных обновлены!"); st.rerun()
                        except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

    # ------------------------------------------
    # ТАБ 2: СОСТАВ ПРОЕКТА
    # ------------------------------------------
    with tab_composition:
        st.markdown("#### 📦 Состав проекта (Наборы → Виды)")
        
        # 1. Загружаем справочники
        datasets_all = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
        info_types_all = query_db("SELECT info_id, info_name, dataset_id FROM info_types ORDER BY info_name")
        ds_map = dict(zip(datasets_all["dataset_name"], datasets_all["dataset_id"]))
        # info_map хранит и ID вида, и ID набора для проверки
        info_map = {row["info_name"]: {"id": row["info_id"], "ds_id": row["dataset_id"]} for _, row in info_types_all.iterrows()}

        # 2. Загружаем текущий состав проекта
        items_df = query_db("""
            SELECT pi.item_id, d.dataset_name, i.info_name, c.full_name as tech_contact,
                   pi.provision_right
            FROM project_items pi
            JOIN datasets d ON pi.dataset_id = d.dataset_id
            JOIN info_types i ON pi.info_id = i.info_id
            LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
            WHERE pi.project_id = :pid
            ORDER BY d.dataset_name, i.info_name
        """, {"pid": proj_id_int})

        st.dataframe(items_df[["dataset_name", "info_name", "tech_contact", "provision_right"]], 
                     width='stretch', hide_index=True,
                     column_config={
                         "dataset_name": "Набор данных", 
                         "info_name": "Вид сведений", 
                         "tech_contact": "Тех. контакт",
                         "provision_right": "Право предоставления"
                     })

        if not is_readonly:
            with st.expander("➕ Добавить / ✏️ Редактировать элемент состава", expanded=True):
                item_options = ["(Добавить новый)"]
                item_ids_map = {}
                for _, row in items_df.iterrows():
                    label = f"{row['dataset_name']} → {row['info_name']}"
                    item_options.append(label)
                    item_ids_map[label] = row["item_id"]

                sel_item = st.selectbox("Выберите элемент для редактирования:", item_options, key="crud_item_sel")
                is_editing = sel_item != "(Добавить новый)"

                # Список опций (ВАЖНО: Должен СТРОГО совпадать с БД)
                prov_options = [
                    'Протокол не заключён',
                    'Оператор и Поставщик',
                    'Только Поставщик',
                    'Не предоставляется'
                ]

                # Логика подстановки значений
                if st.session_state.get("crud_item_sel_prev") != sel_item:
                    if is_editing:
                        curr = items_df[items_df["item_id"] == item_ids_map[sel_item]].iloc[0]
                        st.session_state["crud_ds_in"] = curr["dataset_name"]
                        st.session_state["crud_info_in"] = curr["info_name"]
                        st.session_state["crud_cont_in"] = curr["tech_contact"] if pd.notna(curr["tech_contact"]) else "Не выбран"
                        st.session_state["crud_prov_in"] = curr["provision_right"] if pd.notna(curr["provision_right"]) else prov_options[0]
                    else:
                        st.session_state["crud_ds_in"] = list(ds_map.keys())[0] if ds_map else ""
                        st.session_state["crud_info_in"] = ""
                        st.session_state["crud_cont_in"] = "Не выбран"
                        st.session_state["crud_prov_in"] = prov_options[0]
                    st.session_state["crud_item_sel_prev"] = sel_item

                # Виджеты
                sel_ds = st.selectbox("Набор данных *", list(ds_map.keys()), key="crud_ds_in")
                
                # Фильтрация видов
                current_ds_id = ds_map.get(sel_ds)
                valid_infos = [k for k, v in info_map.items() if v["ds_id"] == current_ds_id]
                if not valid_infos: valid_infos = ["(Пусто)"]
                
                sel_info = st.selectbox("Вид сведений *", valid_infos, key="crud_info_in")
                
                # Контакты поставщика
                proj_sup_id = int(proj_data['supplier_id'])
                sup_contacts = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid ORDER BY full_name", {"sid": proj_sup_id})
                sup_cont_map = dict(zip(sup_contacts["full_name"], sup_contacts["contact_id"]))
                
                sel_cont = st.selectbox("Тех. контакт", ["Не выбран"] + list(sup_cont_map.keys()), key="crud_cont_in")
                sel_prov = st.selectbox("Право предоставления *", prov_options, key="crud_prov_in")

                c_btn, c_del = st.columns([3, 1])
                with c_btn:
                    if st.button("💾 Сохранить в состав", type="primary", width='stretch'):
                        if sel_info == "(Пусто)":
                            st.error("❌ Выберите корректный Вид сведений")
                        else:
                            try:
                                # Извлекаем ID из маппингов
                                d_id = int(ds_map[sel_ds])
                                i_id = int(info_map[sel_info]["id"])
                                c_id = int(sup_cont_map[sel_cont]) if sel_cont != "Не выбран" else None
                                
                                if is_editing:
                                    target_item_id = int(item_ids_map[sel_item])
                                    session.execute(text("""
                                        UPDATE project_items 
                                        SET dataset_id=:d, info_id=:i, tech_contact_id=:c, 
                                            provision_right = CAST(:prov AS data_provision_type)
                                        WHERE item_id=:id
                                    """), {"d": d_id, "i": i_id, "c": c_id, "prov": sel_prov, "id": target_item_id})
                                else:
                                    # Проверка на дубликат перед вставкой
                                    is_dup = not items_df[(items_df["dataset_name"] == sel_ds) & (items_df["info_name"] == sel_info)].empty
                                    if is_dup:
                                        st.warning("⚠️ Этот вид сведений уже есть в проекте")
                                        st.stop()
                                        
                                    session.execute(text("""
                                        INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id, provision_right) 
                                        VALUES (:p, :d, :i, :c, CAST(:prov AS data_provision_type))
                                    """), {"p": proj_id_int, "d": d_id, "i": i_id, "c": c_id, "prov": sel_prov})
                                
                                session.commit()
                                clear_cache()
                                st.success("✅ Сохранено!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Ошибка БД: {e}")
                                session.rollback()
                
                with c_del:
                    if is_editing and st.button("🗑 Удалить", type="secondary", key="del_item_btn", width='stretch'):
                        try:
                            target_item_id = int(item_ids_map[sel_item])
                            # Проверка на этапы
                            check_stages = query_db("SELECT 1 FROM item_stages WHERE item_id = :id LIMIT 1", {"id": target_item_id})
                            if not check_stages.empty:
                                st.error("❌ Нельзя удалить: есть связанные технологические этапы!")
                            else:
                                session.execute(text("DELETE FROM project_items WHERE item_id = :id"), {"id": target_item_id})
                                session.commit()
                                clear_cache()
                                st.success("Удалено")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}")
                            session.rollback()

    # ------------------------------------------
    # ТАБ 3: ЭТАПЫ ПРОЕКТА
    # ------------------------------------------
    with tab_stages:
        track_tabs = st.tabs(["📜 Бюрократия", "⚙️ Технология"])
        with track_tabs[0]:
            render_bureaucracy_tab(session, proj_id_int, user_role=user_role)
        with track_tabs[1]:
            render_technology_tab(session, proj_id_int, user_role=user_role)