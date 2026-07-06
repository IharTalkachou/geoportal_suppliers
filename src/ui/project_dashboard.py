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

    # 1. ОБРАБОТКА ВХОДЯЩИХ ФИЛЬТРОВ
    suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(suppliers["supplier_name"], suppliers["supplier_id"]))
    inv_sup_map = {v: k for k, v in sup_map.items()}

    inc_sup_id = st.session_state.get("filter_supplier_id")
    inc_prj_id = st.session_state.get("filter_project_id")

    if inc_sup_id:
        st.session_state["dash_sup_filter"] = inv_sup_map.get(inc_sup_id, "Все")
        st.session_state["filter_supplier_id"] = None
        
    if inc_prj_id:
        st.session_state["selected_project_id"] = int(inc_prj_id)
        st.session_state["filter_project_id"] = None

    # 2. ГЛОБАЛЬНЫЕ ФИЛЬТРЫ
    if "proj_list_ver" not in st.session_state:
        st.session_state["proj_list_ver"] = 0

    def _on_supplier_change():
        st.session_state["selected_project_id"] = None
        st.session_state["proj_list_ver"] += 1
        st.session_state["dash_edit_mode"] = False

    selected_sup = st.selectbox(
        "🏢 Фильтр по поставщику", 
        ["Все"] + list(sup_map.keys()), 
        key="dash_sup_filter",
        on_change=_on_supplier_change
    )
    
    current_ver = st.session_state["proj_list_ver"]
    if selected_sup == "Все":
        projects = query_db(f"SELECT project_id, project_name FROM projects ORDER BY project_name /* v{current_ver} */")
    else:
        projects = query_db(f"SELECT project_id, project_name FROM projects WHERE supplier_id = :sid ORDER BY project_name /* v{current_ver} */", 
                            {"sid": sup_map[selected_sup]})

    proj_map = {int(r["project_id"]): r["project_name"] for _, r in projects.iterrows()}
    proj_options = [None] + list(proj_map.keys())

    current_proj_id = st.session_state.get("selected_project_id")
    if current_proj_id not in proj_options:
        current_proj_id = None

    selected_proj_id = st.selectbox(
        "🔍 Выберите проект", 
        proj_options, 
        index=0 if current_proj_id is None else proj_options.index(current_proj_id),
        format_func=lambda x: proj_map.get(x, "Выберите проект..."), 
        key=f"dash_project_selector_v{current_ver}" 
    )
    
    if selected_proj_id != st.session_state.get("selected_project_id"):
        st.session_state["selected_project_id"] = selected_proj_id
        if selected_proj_id:
            log_action(st.session_state["auth"]["user_id"], "VIEW_PROJECT", "projects", int(selected_proj_id))
        st.rerun()

    # 3. 🟢 ЛОГИКА СОЗДАНИЯ НОВОГО ПРОЕКТА
    if not st.session_state.get("selected_project_id"):
        if selected_sup != "Все":
            st.info("💡 Выберите проект поставщика или создайте новый проект")
            if not is_readonly:
                with st.expander("➕ Создать новый проект для этого поставщика"):
                    # 🟢 МЫ УБРАЛИ st.form, чтобы кнопка могла напрямую влиять на session_state
                    # Это сделает процесс "создать и открыть" более надежным
                    new_p_name = st.text_input("Название проекта *", key="new_proj_name_field")
                    new_p_agr = st.checkbox("Проект Соглашения (первичное подключение)", key="new_proj_agr_field")
                    
                    if st.button("🚀 Создать и открыть", width='stretch'):
                        if new_p_name:
                            try:
                                s_id = int(sup_map[selected_sup])
                                # 1. Вставка в БД
                                new_id_val = session.execute(text("""
                                    INSERT INTO projects (supplier_id, project_name, status, is_agreement_project) 
                                    VALUES (:sid, :pn, 1, :is_agr) RETURNING project_id
                                """), {"sid": s_id, "pn": new_p_name.strip(), "is_agr": new_p_agr}).scalar()
                                
                                # 2. ЛОГИРОВАНИЕ
                                log_action(
                                    user_id=st.session_state["auth"]["user_id"], 
                                    action="CREATE_PROJECT", 
                                    target_table="projects", 
                                    target_id=int(new_id_val), 
                                    new={"name": new_p_name, "is_agreement": new_p_agr}
                                )
                                
                                session.commit()
                                clear_cache() # Сбрасываем кэш запросов
                                
                                # 3. Увеличиваем версию, чтобы селектбокс обновил список из БД
                                st.session_state["proj_list_ver"] += 1
                                # Принудительно ставим новый ID как выбранный
                                st.session_state["selected_project_id"] = int(new_id_val)
                                
                                st.toast(f"✅ Проект '{new_p_name}' создан и открыт!")
                                # Даем небольшую паузу, чтобы тост успел инициироваться перед рераном
                                import time
                                time.sleep(0.5)
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Ошибка при создании: {e}")
                                session.rollback()
                        else:
                            st.error("❌ Укажите название проекта")
        else:
            st.info("👆 Выберите поставщика и проект для начала работы.")
        return 

    # 4. ЗАГРУЗКА ДАННЫХ ПРОЕКТА
    proj_id_int = int(st.session_state["selected_project_id"])
    
    # Сначала получаем результат запроса
    proj_query_res = query_db("""
        SELECT p.project_id, p.supplier_id, p.project_name, 
               s.supplier_name, c.full_name, rs.status_name, p.notes,
               p.is_agreement_project
        FROM projects p
        LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
        LEFT JOIN contacts c ON p.main_contact_id = c.contact_id
        LEFT JOIN ref_statuses rs ON p.status = rs.status_id
        WHERE p.project_id = :pid
    """, {"pid": proj_id_int})

    # Если проект не найден (например, только что удален)
    if proj_query_res.empty:
        st.session_state["selected_project_id"] = None
        st.session_state["proj_list_ver"] += 1 # Сбрасываем виджет выбора
        st.rerun()
    
    proj_data = proj_query_res.iloc[0]

    # 5. ПОД-НАВИГАЦИЯ
    sub_nav = st.segmented_control(
        "Разделы проекта",
        options=["📄 Паспорт", "📦 Состав", "📜 Согласование документов", "⚙️ Техническая проработка"],
        default="📄 Паспорт",
        key=f"project_nav_{proj_id_int}",
        label_visibility="collapsed"
    )
    st.markdown("---")

    if sub_nav == "📄 Паспорт":
        render_passport_subtab(session, proj_id_int, is_readonly, proj_data)
    elif sub_nav == "📦 Состав":
        render_composition_subtab(session, proj_id_int, is_readonly, proj_data)
    elif sub_nav == "📜 Согласование документов":
        render_bureaucracy_tab(session, proj_id_int, user_role=user_role)
    elif sub_nav == "⚙️ Техническая проработка":
        render_technology_tab(session, proj_id_int, user_role=user_role)

# ==========================================
# 🛠️ ПОД-ФУНКЦИИ (КОМПОНЕНТЫ)
# ==========================================

def render_passport_subtab(session, proj_id_int, is_readonly, proj_data):
    """Паспорт проекта с индикаторами прогресса и настройками SLA"""
    
    # 1. Сбор команды
    resp_df = query_db("""
        SELECT DISTINCT u.display_name FROM users u
        WHERE u.user_id IN (
            SELECT responsible_id FROM project_stages WHERE project_id = :pid AND responsible_id IS NOT NULL
        )
    """, {"pid": proj_id_int})
    responsibles_str = ", ".join(resp_df["display_name"].tolist()) if not resp_df.empty else "Не назначены"

    # 2. 🟢 РАСЧЕТ ИНДИКАТОРОВ (ГАЛОЧКИ)
    # А. Администратор
    admin_check = query_db("""
        SELECT 1 FROM reg_request_users rru
        JOIN reg_requests rr ON rru.req_id = rr.req_id
        WHERE rr.result_supplier_id = :sid AND rru.is_admin = TRUE AND rru.is_active = TRUE
        LIMIT 1
    """, {"sid": int(proj_data['supplier_id'])})
    has_admin = not admin_check.empty

    # Б. Стадии (Метаданные/Данные)
    # Ищем выполненные (micro_status=4) этапы с конкретными кодами
    stage_checks = query_db("""
        SELECT s.stage_code 
        FROM project_stages ps 
        JOIN stages s ON ps.stage_id = s.stage_id 
        WHERE ps.project_id = :pid AND ps.micro_status = 4
    """, {"pid": proj_id_int})
    done_codes = stage_checks['stage_code'].tolist() if not stage_checks.empty else []

    has_meta = 'META_PUB' in done_codes
    has_data = 'DATA_PUB' in done_codes
    # Временный маркер для "Передан набор", если у тебя есть такой код, замени 'DATA_WAIT'
    has_transfer = 'DATA_WAIT' in done_codes 

    # 3. ВИЗУАЛИЗАЦИЯ ПАСПОРТА
    with st.container(border=True):
        col_main, col_side = st.columns([2, 1])
        with col_main:
            st.markdown(f"### {proj_data['project_name']}")
            st.markdown(f"**🏢 Поставщик:** {proj_data['supplier_name']}")
            
            st.button("🏢 Перейти к поставщику", key="btn_go_to_sup",
                      on_click=lambda sid: st.session_state.update({"main_nav": "📁 Поставщики", "filter_supplier_id": sid}),
                      args=(int(proj_data['supplier_id']),))
            
            st.markdown(f"**📊 Статус:** {proj_data['status_name']}")
            st.markdown(f"**👥 Команда:** {responsibles_str}")
            
            # 🟢 ВЫВОД ИНДИКАТОРОВ
            st.write("")
            ic1, ic2, ic3, ic4 = st.columns(4)
            ic1.checkbox("🔑 Админ. зарегистрирован", value=has_admin, disabled=True)
            ic2.checkbox("📦 Набор передан", value=has_transfer, disabled=True)
            ic3.checkbox("📑 Метаданные опубл.", value=has_meta, disabled=True)
            ic4.checkbox("🌐 Данные опубликованы", value=has_data, disabled=True)

        with col_side:
            if proj_data.get('is_agreement_project'):
                st.warning("📜 Проект Соглашения")
            st.info(f"📝 {proj_data['notes'] or 'Нет примечаний'}")
            
            # SLA Справка
            #with st.expander("⏳ Параметры SLA"):
            #    st.caption(f"Метаданные: {proj_data.get('meta_days', 10)} дн. ({proj_data.get('meta_method', '—')})")
            #    st.caption(f"Данные: {proj_data.get('data_days', 10)} дн. ({proj_data.get('data_method', '—')})")

    if not is_readonly:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✏️ Изменить реквизиты", type="secondary", width='stretch'):
                st.session_state["dash_edit_mode"] = not st.session_state.get("dash_edit_mode", False)
                st.rerun()
        with c2:
            if st.button("🗑 Удалить проект", type="secondary", width='stretch'):
                # ... (логика удаления без изменений) ...
                pass

        if st.session_state.get("dash_edit_mode"):  
            # 🟢 ОБНОВЛЕННАЯ ФОРМА РЕДАКТИРОВАНИЯ
            with st.form("edit_proj_form"):
                st.markdown("#### 📝 Редактирование реквизитов и SLA")
                
                # Подгружаем доп. данные для формы (SLA поля)
                curr_full = query_db("SELECT * FROM projects WHERE project_id = :pid", {"pid": proj_id_int}).iloc[0]

                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    p_name_in = st.text_input("Название проекта", value=curr_full['project_name'])
                    p_is_agr = st.checkbox("Проект Соглашения", value=bool(curr_full['is_agreement_project']))
                    
                    st.divider()
                    st.markdown("**SLA Метаданные**")
                    m_days = st.number_input("Дней на размещение (мета)", value=int(curr_full.get('meta_days', 10)), min_value=1)
                    m_meth = st.selectbox("Способ (мета)", ["Электронный кабинет", "Передача XML", "API", "Другой"], 
                                          index=0 if curr_full.get('meta_method') not in ["Передача XML", "API", "Другой"] else ["Электронный кабинет", "Передача XML", "API", "Другой"].index(curr_full.get('meta_method')))
                
                with col_f2:
                    stat_list = query_db("SELECT status_id, status_name FROM ref_statuses ORDER BY status_id")
                    s_names = stat_list["status_name"].tolist()
                    st.selectbox("Статус", s_names, index=s_names.index(curr_full['status_name']) if curr_full['status_name'] in s_names else 0, key="p_stat_in")
                    
                    st.divider()
                    st.markdown("**SLA Данные и сервисы**")
                    d_days = st.number_input("Дней на размещение (данные)", value=int(curr_full.get('data_days', 10)), min_value=1)
                    d_meth = st.selectbox("Способ (данные)", ["Сервис (WMS/WFS)", "Ссылка на облако", "Прямая загрузка", "Носитель"],
                                          index=0 if curr_full.get('data_method') not in ["Сервис (WMS/WFS)", "Ссылка на облако", "Прямая загрузка", "Носитель"] else ["Сервис (WMS/WFS)", "Ссылка на облако", "Прямая загрузка", "Носитель"].index(curr_full.get('data_method')))

                p_notes_in = st.text_area("Примечание", value=curr_full['notes'] or "")

                if st.form_submit_button("💾 Сохранить изменения", type="primary"):
                    try:
                        # Получаем ID статуса из выбранного имени
                        new_stat_id = int(stat_list[stat_list["status_name"]==st.session_state.p_stat_in]["status_id"].iloc[0])
                        
                        session.execute(text("""
                            UPDATE projects SET 
                                project_name=:name, is_agreement_project=:is_agr, status=:stat, notes=:notes,
                                meta_days=:md, data_days=:dd, meta_method=:mm, data_method=:dm
                            WHERE project_id=:id
                        """), {
                            "name": p_name_in, "is_agr": p_is_agr, "stat": new_stat_id, "notes": p_notes_in,
                            "md": m_days, "dd": d_days, "mm": m_meth, "dm": d_meth, "id": proj_id_int
                        })
                        
                        session.commit(); clear_cache()
                        st.session_state.dash_edit_mode = False
                        st.success("✅ Данные проекта обновлены!"); st.rerun()
                    except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()


def render_composition_subtab(session, proj_id_int, is_readonly, proj_data):
    """Вынесенный состав проекта"""
    st.markdown("#### 📦 Состав проекта (Наборы → Виды)")

    proj_sup_id = int(proj_data['supplier_id'])
    
    # 1. Загружаем справочники
    datasets_all = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    info_types_all = query_db("SELECT info_id, info_name, dataset_id FROM info_types ORDER BY info_name")
    ds_map = dict(zip(datasets_all["dataset_name"], datasets_all["dataset_id"]))
    # info_map хранит и ID вида, и ID набора для проверки
    info_map = {row["info_name"]: {"id": row["info_id"], "ds_id": row["dataset_id"]} for _, row in info_types_all.iterrows()}

    # 2. Загружаем текущий состав проекта
    items_df = query_db("""
        SELECT 
            pi.item_id, d.dataset_name, i.info_name, 
            i.format, i.update,
            c.full_name as tech_contact,
            pi.provision_right,
            pi.meta_days, pi.data_days,
            pi.meta_method, pi.data_method
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
        WHERE pi.project_id = :pid
        ORDER BY d.dataset_name, i.info_name
    """, {"pid": proj_id_int})

    st.dataframe(items_df[["dataset_name", "info_name", "tech_contact", "provision_right", "format", "update", "data_method"]], 
                    width='stretch', hide_index=True,
                    column_config={
                        "dataset_name": "Набор данных", 
                        "info_name": "Вид сведений", 
                        "tech_contact": "Технический контакт",
                        "provision_right": "Право предоставления набора",
                        "format": "Формат предоставления набора",
                        "update": "Срок обновления набора",
                        "data_method": "Способ предоставления набора"
                    })

    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать элемент состава", expanded=False):
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
                'На безвозмездной основе',
                'Оператор и Поставщик',
                'Только Поставщик',
                'Только метаданные',
                'Не предоставляется'
            ]

            # Логика подстановки значений
            if st.session_state.get("crud_item_sel_prev") != sel_item:
                if is_editing:
                    # Извлекаем данные один раз здесь
                    curr = items_df[items_df["item_id"] == item_ids_map[sel_item]].iloc[0]
                    
                    st.session_state["crud_ds_in"] = curr["dataset_name"]
                    st.session_state["crud_info_in"] = curr["info_name"]
                    st.session_state["crud_cont_in"] = curr["tech_contact"] if pd.notna(curr["tech_contact"]) else "Не выбран"
                    st.session_state["crud_prov_in"] = curr["provision_right"] if pd.notna(curr["provision_right"]) else prov_options[0]
                    st.session_state["c_meta_d"] = int(curr["meta_days"])
                    st.session_state["c_meta_m"] = curr["meta_method"]
                    st.session_state["c_data_d"] = int(curr["data_days"])
                    st.session_state["c_data_m"] = curr["data_method"]
                else:
                    st.session_state["crud_ds_in"] = list(ds_map.keys())[0] if ds_map else ""
                    st.session_state["crud_info_in"] = ""
                    st.session_state["crud_cont_in"] = "Не выбран"
                    st.session_state["crud_prov_in"] = prov_options[0]
                    st.session_state["c_meta_d"] = 10
                    st.session_state["c_meta_m"] = "Электронный кабинет"
                    st.session_state["c_data_d"] = 0
                    st.session_state["c_data_m"] = "Сервис (WMS/WFS)"
                
                st.session_state["crud_item_sel_prev"] = sel_item

            # Виджеты
            sel_ds = st.selectbox("Набор данных *", list(ds_map.keys()), key="crud_ds_in")
            
            # Фильтрация видов
            current_ds_id = ds_map.get(sel_ds)
            valid_infos = [k for k, v in info_map.items() if v["ds_id"] == current_ds_id]
            if not valid_infos: valid_infos = ["(Пусто)"]
            
            sel_info = st.selectbox("Вид сведений *", valid_infos, key="crud_info_in")
            
            # Контакты поставщика
            #proj_sup_id = int(proj_data['supplier_id'])
            sup_contacts = query_db("SELECT contact_id, full_name FROM contacts WHERE supplier_id = :sid ORDER BY full_name", {"sid": proj_sup_id})
            sup_cont_map = dict(zip(sup_contacts["full_name"], sup_contacts["contact_id"]))
            
            sel_cont = st.selectbox("Тех. контакт", ["Не выбран"] + list(sup_cont_map.keys()), key="crud_cont_in")
            sel_prov = st.selectbox("Право предоставления *", prov_options, key="crud_prov_in")

            st.markdown("---")
            st.markdown("**⏳ Параметры размещения (ALM/SLA)**")
            csla1, csla2 = st.columns(2)
            with csla1:
                st.number_input("Срок метаданных (дн.)", min_value=1, key="c_meta_d")
                st.selectbox("Способ (метаданные)", 
                            ["Электронный кабинет", "Передача XML", "API", "Другой"], 
                            key="c_meta_m")
            with csla2:
                is_not_transmitted = (st.session_state.get("c_data_m") == "Не передаются")
                if is_not_transmitted:
                    st.session_state["c_data_d"] = 0
                
                
                st.number_input(
                    "Срок данных (дн.)", 
                    min_value=0, 
                    key="c_data_d", 
                    disabled=is_not_transmitted,
                    help="Срок не указывается, если данные не передаются" if is_not_transmitted else None
                )
                if is_not_transmitted:
                    st.caption("🚫 **Срок не требуется:** выбран режим без передачи данных")
                    
                st.selectbox("Способ (данные)", 
                            ["Сервис (WMS/WFS)", "Ссылка на облако", "Прямая загрузка", "Носитель", "Не передаются"], 
                            key="c_data_m")

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
                                    UPDATE project_items SET 
                                        dataset_id=:d, info_id=:i, tech_contact_id=:c, provision_right=CAST(:prov AS data_provision_type),
                                        meta_days=:md, data_days=:dd, meta_method=:mm, data_method=:dm
                                    WHERE item_id=:id
                                """), {"d": d_id, "i": i_id, "c": c_id, "prov": sel_prov, 
                                    "md": st.session_state.c_meta_d, "mm": st.session_state.c_meta_m, "dd": st.session_state.c_data_d, "dm": st.session_state.c_data_m, "id": target_item_id})
                            else:
                                # Проверка на дубликат перед вставкой
                                is_dup = not items_df[(items_df["dataset_name"] == sel_ds) & (items_df["info_name"] == sel_info)].empty
                                if is_dup:
                                    st.warning("⚠️ Этот вид сведений уже есть в проекте")
                                    st.stop()
                                    
                                session.execute(text("""
                                    INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id, provision_right, meta_days, data_days, meta_method, data_method) 
                                    VALUES (:p, :d, :i, :c, CAST(:prov AS data_provision_type), :md, :dd, :mm, :dm)
                                """), {"p": proj_id_int, "d": d_id, "i": i_id, "c": c_id, "prov": sel_prov, 
                                    "md": st.session_state.c_meta_d, "mm": st.session_state.c_meta_m, "dd": st.session_state.c_data_d, "dm": st.session_state.c_data_m})
                            
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
                        check_stages = query_db("""
                            SELECT 1 FROM project_stages 
                            WHERE affected_item_ids @> CAST(:id_json AS JSONB) LIMIT 1
                        """, {"id_json": f"[{target_item_id}]"})
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

