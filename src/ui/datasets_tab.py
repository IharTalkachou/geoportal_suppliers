import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_datasets_tab(session, user_role="user"):
    st.subheader("📚 Справочники данных")
    is_readonly = (user_role == "user")

    # 1. 📑 СЕРВЕРНАЯ НАВИГАЦИЯ
    choice = st.segmented_control(
        "Разделы справочника",
        options=["🗃️ Наборы данных", "📄 Виды сведений"],
        default="🗃️ Наборы данных",
        key="ds_sub_nav",
        label_visibility="collapsed"
    )
    st.markdown("---")

    # ==========================================
    # РАЗДЕЛ 1: НАБОРЫ ДАННЫХ
    # ==========================================
    if choice == "🗃️ Наборы данных":
        render_datasets_manager(session, is_readonly)

    # ==========================================
    # РАЗДЕЛ 2: ВИДЫ СВЕДЕНИЙ
    # ==========================================
    elif choice == "📄 Виды сведений":
        render_info_types_manager(session, is_readonly)

# ==========================================
# 🛠️ ПОД-ФУНКЦИИ (КОМПОНЕНТЫ)
# ==========================================

def render_datasets_manager(session, is_readonly):
    ds_df = query_db("SELECT dataset_id, dataset_name, is_mandatory, is_basic FROM datasets ORDER BY is_mandatory DESC, dataset_name")

    # Размещаем радио-кнопку. Она автоматически исключает выбор нескольких вариантов.
    filter_mode = st.radio(
        "🔍 Фильтр наборов по обязательности:",
        options=["Все", "Только обязательные", "Только необязательные"],
        horizontal=False, # Как ты и просил: один под другим
        key="ds_filter_radio"
    )
    
    # Логика фильтрации
    display_ds = ds_df.copy()
    if filter_mode == "Только обязательные":
        display_ds = display_ds[display_ds["is_mandatory"] == True]
    elif filter_mode == "Только необязательные":
        display_ds = display_ds[display_ds["is_mandatory"] == False]

    st.markdown(f"**Отображено записей:** {len(display_ds)}")

    st.dataframe(display_ds[["dataset_name", "is_mandatory", "is_basic"]], 
                 width="stretch", 
                 hide_index=True,
                 height=500,
                 column_config={
                     "dataset_name": "Название набора", 
                     "is_mandatory": "Обязательный", 
                     "is_basic": "Базовый"
                 })

    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать набор"):
            edit_options = ["(Создать новый)"] + ds_df["dataset_name"].tolist()
            sel_ds = st.selectbox("Выберите набор для редактирования:", edit_options, key="ds_edit_selector")
            is_editing = sel_ds != "(Создать новый)"

            if st.session_state.get("ds_prev_sel") != sel_ds:
                if is_editing:
                    curr = ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]
                    st.session_state["ds_name_in"] = curr["dataset_name"]
                    st.session_state["ds_mand_in"] = bool(curr["is_mandatory"])
                    st.session_state["ds_basic_in"] = bool(curr["is_basic"])
                else:
                    st.session_state["ds_name_in"] = ""
                    st.session_state["ds_mand_in"] = False
                    st.session_state["ds_basic_in"] = False
                st.session_state["ds_prev_sel"] = sel_ds

            with st.form("ds_save_form"):
                st.text_input("Название набора *", key="ds_name_in")
                c1, c2 = st.columns(2)
                with c1: st.checkbox("Обязательный (is_mandatory)", key="ds_mand_in")
                with c2: st.checkbox("Базовый (is_basic)", key="ds_basic_in")
                
                if st.form_submit_button("💾 Сохранить набор", width="stretch"):
                    new_name = st.session_state["ds_name_in"].strip()
                    if not new_name:
                        st.error("❌ Название обязательно")
                    else:
                        try:
                            if is_editing:
                                target_id = int(ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]["dataset_id"])
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "UPDATE_DATASET", "datasets", target_id, new={"name": new_name})
                                session.execute(text("UPDATE datasets SET dataset_name=:n, is_mandatory=:m, is_basic=:b WHERE dataset_id=:id"),
                                                {"n": new_name, "m": st.session_state["ds_mand_in"], "b": st.session_state["ds_basic_in"], "id": target_id})
                            else:
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "CREATE_DATASET", "datasets", None, new={"name": new_name})
                                session.execute(text("INSERT INTO datasets (dataset_name, is_mandatory, is_basic) VALUES (:n, :m, :b)"),
                                                {"n": new_name, "m": st.session_state["ds_mand_in"], "b": st.session_state["ds_basic_in"]})
                            session.commit(); clear_cache(); st.success("✅ Сохранено!"); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()

            if is_editing:
                if st.button("🗑 Удалить набор", type="secondary", width="stretch", key="ds_del_btn"):
                    target_id = int(ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]["dataset_id"])
                    has_info_types = session.execute(text("SELECT 1 FROM info_types WHERE dataset_id = :id LIMIT 1"), {"id": target_id}).scalar()
                    in_use = session.execute(text("SELECT 1 FROM project_items WHERE dataset_id = :id LIMIT 1"), {"id": target_id}).scalar()
                    
                    if has_info_types or in_use:
                        st.error("❌ Нельзя удалить набор: он используется или содержит виды сведений.")
                    else:
                        try:
                            log_action(st.session_state["auth"]["user_id"], "DELETE_DATASET", "datasets", target_id, old={"name": sel_ds})
                            session.execute(text("DELETE FROM datasets WHERE dataset_id = :id"), {"id": target_id})
                            session.commit(); clear_cache(); st.success("🗑 Удалён"); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()

def clear_parts_form_state():
    """Сброс полей диалога частей.

    Ключи содержат part_id/info_id (заранее не известны), поэтому чистятся
    по префиксу - иначе поля тянутся из ранее открытого вида сведений.
    """
    for k in [k for k in st.session_state.keys() if k.startswith("itp_")]:
        st.session_state.pop(k, None)

@st.dialog("Части вида сведений", width="large")
def info_type_parts_dialog(session, info_id, info_name):
    """Управление разбиением вида сведений на части.

    Часть = единица, которой соответствует один протокол. Состав частей общий
    для всех поставщиков (вид сведений задан регламентом), поэтому правка здесь
    видна во всех проектах, где этот вид используется.
    """
    st.caption(f"**{info_name}**")
    st.info("Части общие для всех поставщиков. Разбиение нужно, только если вид сведений "
            "передаётся несколькими протоколами. Нет частей — протокол покрывает вид целиком.")

    parts = query_db("""
        SELECT part_id, part_name, sort_order
        FROM info_type_parts WHERE info_id = :iid
        ORDER BY sort_order NULLS LAST, part_id
    """, {"iid": info_id})

    if parts.empty:
        st.warning("Частей нет — вид сведений передаётся целиком.")
    else:
        for pos, (_, p) in enumerate(parts.iterrows()):
            pid = int(p['part_id'])
            with st.container(border=True):
                st.text_input("Название части", value=p['part_name'], key=f"itp_name_{pid}",
                              label_visibility="collapsed")
                b1, b2, b3, b4 = st.columns([0.25, 0.25, 0.25, 0.25])

                if b1.button("💾", key=f"itp_save_{pid}", help="Сохранить название", width='stretch'):
                    new_name = (st.session_state.get(f"itp_name_{pid}") or "").strip()
                    if not new_name:
                        st.warning("Название не может быть пустым")
                    else:
                        try:
                            log_action(st.session_state["auth"]["user_id"], "UPDATE_INFO_PART",
                                       "info_type_parts", pid, new={"name": new_name})
                            session.execute(text("UPDATE info_type_parts SET part_name=:n WHERE part_id=:id"),
                                            {"n": new_name, "id": pid})
                            session.commit(); clear_cache(); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()

                # Перестановка: меняем sort_order местами с соседом
                if b2.button("⬆️", key=f"itp_up_{pid}", help="Выше", width='stretch', disabled=(pos == 0)):
                    _swap_part_order(session, parts, pos, pos - 1)
                if b3.button("⬇️", key=f"itp_down_{pid}", help="Ниже", width='stretch',
                             disabled=(pos == len(parts) - 1)):
                    _swap_part_order(session, parts, pos, pos + 1)

                if b4.button("🗑", key=f"itp_del_{pid}", help="Удалить часть", width='stretch'):
                    usage = query_db("""
                        SELECT (SELECT COUNT(*) FROM project_document_items WHERE part_id = :pid) AS in_docs,
                               (SELECT COUNT(*) FROM project_item_part_details WHERE part_id = :pid) AS in_details
                    """, {"pid": pid}).iloc[0]
                    if int(usage['in_docs']) or int(usage['in_details']):
                        sups = query_db("""
                            SELECT DISTINCT s.supplier_name
                            FROM project_item_part_details pd
                            JOIN project_items pi ON pd.item_id = pi.item_id
                            JOIN projects p ON pi.project_id = p.project_id
                            JOIN suppliers s ON p.supplier_id = s.supplier_id
                            WHERE pd.part_id = :pid
                            ORDER BY s.supplier_name
                        """, {"pid": pid})
                        names = ", ".join(sups['supplier_name'].tolist()) if not sups.empty else "—"
                        st.error(f"❌ Нельзя удалить: часть используется "
                                 f"(охват документов: {int(usage['in_docs'])}, параметры передачи: "
                                 f"{int(usage['in_details'])}). Поставщики: {names}")
                    else:
                        try:
                            log_action(st.session_state["auth"]["user_id"], "DELETE_INFO_PART",
                                       "info_type_parts", pid, old={"name": p['part_name']})
                            session.execute(text("DELETE FROM info_type_parts WHERE part_id = :id"), {"id": pid})
                            session.commit(); clear_cache(); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()

    st.divider()
    st.text_input("Название новой части", key="itp_new_name")
    if st.button("➕ Добавить часть", type="primary", width='stretch', key="itp_add_btn"):
        new_part = (st.session_state.get("itp_new_name") or "").strip()
        if not new_part:
            st.warning("Укажите название части")
        else:
            try:
                session.execute(text("""
                    INSERT INTO info_type_parts (info_id, part_name, sort_order)
                    VALUES (:iid, :n, (SELECT COALESCE(MAX(sort_order), 0) + 1
                                         FROM info_type_parts WHERE info_id = :iid))
                """), {"iid": info_id, "n": new_part})
                session.commit(); clear_cache()
                log_action(st.session_state["auth"]["user_id"], "CREATE_INFO_PART",
                           "info_type_parts", None, new={"info_id": info_id, "name": new_part})
                st.session_state.pop("itp_new_name", None)
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка: {e}"); session.rollback()

def _swap_part_order(session, parts, pos_a, pos_b):
    """Меняет местами sort_order двух частей и перезапускает диалог."""
    a, b = parts.iloc[pos_a], parts.iloc[pos_b]
    try:
        session.execute(text("UPDATE info_type_parts SET sort_order=:o WHERE part_id=:id"),
                        {"o": int(b['sort_order']) if pd.notna(b['sort_order']) else pos_b + 1,
                         "id": int(a['part_id'])})
        session.execute(text("UPDATE info_type_parts SET sort_order=:o WHERE part_id=:id"),
                        {"o": int(a['sort_order']) if pd.notna(a['sort_order']) else pos_a + 1,
                         "id": int(b['part_id'])})
        session.commit(); clear_cache(); st.rerun()
    except Exception as e:
        st.error(f"Ошибка: {e}"); session.rollback()

def render_info_types_manager(session, is_readonly):
    datasets_list = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    if datasets_list.empty:
        st.info("Сначала создайте хотя бы один набор данных.")
        return

    ds_map = dict(zip(datasets_list["dataset_name"], datasets_list["dataset_id"]))
    sel_ds_name = st.selectbox("📦 Выберите набор данных:", list(ds_map.keys()), key="info_tab_ds_sel")
    sel_ds_id = ds_map[sel_ds_name]

    # Справочники из БД
    formats_list = query_db("SELECT format_name FROM ref_file_formats ORDER BY format_name")["format_name"].tolist()
    periods_list = query_db("SELECT period_name FROM ref_update_periods ORDER BY period_name")["period_name"].tolist()

    info_df = query_db("""
        SELECT it.info_id, it.info_name, it.type, it.format, it."update",
               s.supplier_name, s.supplier_id
        FROM info_types it
        LEFT JOIN project_items pi ON it.info_id = pi.info_id
        LEFT JOIN projects p ON pi.project_id = p.project_id
        LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
        WHERE it.dataset_id = :did
        ORDER BY it.info_name
    """, {"did": sel_ds_id})

    # Документы (соглашения/протоколы), покрывающие вид сведений у конкретного
    # поставщика: либо явным охватом project_document_items, либо неявно -
    # документ с пустым охватом покрывает весь проект, т.е. все его наборы
    docs_df = query_db("""
        SELECT pi.info_id, p.supplier_id,
               pd.doc_id, pd.doc_kind, pd.doc_number, pd.doc_url, pd.is_signed,
               -- Какие именно части покрывает документ. Пусто = вид сведений целиком:
               -- либо охват не задан вовсе, либо задан на уровне item без части.
               string_agg(itp.part_name, ', ' ORDER BY itp.sort_order NULLS LAST) AS covered_parts
        FROM project_items pi
        JOIN projects p ON pi.project_id = p.project_id
        JOIN project_documents pd ON pd.project_id = pi.project_id
        JOIN info_types it ON pi.info_id = it.info_id
        LEFT JOIN project_document_items pdi
               ON pdi.doc_id = pd.doc_id AND pdi.item_id = pi.item_id
        LEFT JOIN info_type_parts itp ON pdi.part_id = itp.part_id
        WHERE it.dataset_id = :did
          AND (
            pdi.link_id IS NOT NULL
            OR NOT EXISTS (SELECT 1 FROM project_document_items x
                            WHERE x.doc_id = pd.doc_id)
          )
        -- GROUP BY вместо DISTINCT: один вид сведений может встречаться в
        -- нескольких project_items одного проекта, но документ нужен один раз.
        -- При DISTINCT сортировка по CASE невозможна - выражения ORDER BY
        -- обязаны быть в списке выборки.
        GROUP BY pi.info_id, p.supplier_id, pd.doc_id, pd.doc_kind,
                 pd.doc_number, pd.doc_url, pd.is_signed
        ORDER BY pi.info_id, p.supplier_id,
                 CASE WHEN pd.doc_kind = 'Соглашение' THEN 0 ELSE 1 END, pd.doc_id
    """, {"did": sel_ds_id})

    # Части видов сведений этого набора (общие для всех поставщиков)
    parts_df = query_db("""
        SELECT itp.info_id, count(*) AS parts_cnt,
               string_agg(itp.part_name, ' · ' ORDER BY itp.sort_order NULLS LAST, itp.part_id) AS parts_list
        FROM info_type_parts itp
        JOIN info_types it ON itp.info_id = it.info_id
        WHERE it.dataset_id = :did
        GROUP BY itp.info_id
    """, {"did": sel_ds_id})

    if info_df.empty:
        st.info("В этом наборе еще нет видов сведений.")
    else:
        st.markdown(f"#### 📄 Виды сведений: {sel_ds_name}")
        
        # Группируем данные по названию вида (чтобы объединить разных поставщиков в одну карточку)
        grouped = info_df.groupby("info_name")
        
        # Создаем сетку: 4 колонки
        cols = st.columns(4)
        
        # Функция-коллбэк для перехода (определяем один раз)
        def go_to_sup_callback(sid):
            st.session_state["main_nav"] = "📁 Поставщики"
            st.session_state["filter_supplier_id"] = sid

        # Итерируемся по группам с индексом для распределения по колонкам
        for idx, (info_name, group) in enumerate(grouped):
            with cols[idx % 4]:
                with st.container(border=True):
                    # Заголовок вида сведений
                    st.markdown(f"**{info_name}**")
                    
                    # Компактные мета-данные
                    row = group.iloc[0]
                    st.caption(f"🛠 {row['type']} | 📂 {row['format']}")
                    st.caption(f"📅 Обновление: {row['update']}")

                    # Разбиение на части: показываем состав и даём им управлять
                    cur_info_id = int(row['info_id'])
                    my_parts = parts_df[parts_df['info_id'] == cur_info_id] if not parts_df.empty else parts_df
                    if not my_parts.empty:
                        p_row = my_parts.iloc[0]
                        st.caption(f"✂️ Частей: {int(p_row['parts_cnt'])} — {p_row['parts_list']}")
                    if not is_readonly:
                        if st.button("✂️ Части", key=f"parts_btn_{idx}_{cur_info_id}", width='stretch'):
                            clear_parts_form_state()
                            info_type_parts_dialog(session, cur_info_id, info_name)

                    # Блок поставщиков (маленькие кнопки)
                    st.markdown("---")
                    st.markdown("<div style='font-size: 0.8rem; margin-bottom: 5px;'>Поставщики:</div>", unsafe_allow_html=True)
                    
                    valid_sups = group[group['supplier_id'].notna()]
                    if not valid_sups.empty:
                        for _, s_row in valid_sups.iterrows():
                            # Документы этого поставщика, покрывающие данный вид сведений
                            if not docs_df.empty:
                                sup_docs = docs_df[
                                    (docs_df['info_id'] == s_row['info_id']) &
                                    (docs_df['supplier_id'] == s_row['supplier_id'])
                                ]
                                if not sup_docs.empty:
                                    parts = []
                                    for _, d in sup_docs.iterrows():
                                        mark = "✅" if d['is_signed'] else "⏳"
                                        num = str(d['doc_number']).strip() if pd.notna(d['doc_number']) else ""
                                        name = f"{d['doc_kind']} {num}".strip()
                                        # Документ может покрывать не весь вид сведений,
                                        # а только отдельные его части - помечаем явно
                                        cov = d.get('covered_parts')
                                        if pd.notna(cov) and str(cov).strip():
                                            name = f"{name} (часть: {cov})"
                                        if d['doc_url']:
                                            parts.append(f'<a href="{d["doc_url"]}" target="_blank" '
                                                         f'style="text-decoration:none;font-size:0.75rem;">{mark} {name}</a>')
                                        else:
                                            parts.append(f'<span style="font-size:0.75rem;">{mark} {name}</span>')
                                    st.markdown('<div style="margin:2px 0 4px 0;">' + " · ".join(parts) + '</div>',
                                                unsafe_allow_html=True)
                            st.button(
                                f"🏢 {s_row['supplier_name']}",
                                key=f"btn_nav_{idx}_{s_row['supplier_id']}",
                                on_click=go_to_sup_callback,
                                args=(int(s_row['supplier_id']),),
                                width='stretch'
                                # Мы можем добавить здесь небольшой CSS, чтобы кнопка была еще меньше, 
                                # но стандартный use_container_width в колонке и так сделает её компактной
                            )
                    else:
                        st.caption("Не используется в проектах")

    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать вид"):
            edit_opts_i = ["(Создать новый)"] + info_df["info_name"].tolist()
            sel_i = st.selectbox("Выберите вид:", edit_opts_i, key="info_edit_selector")
            is_editing_i = sel_i != "(Создать новый)"

            # Логика инициализации полей
            if st.session_state.get("info_prev_sel") != sel_i:
                if is_editing_i:
                    curr = info_df[info_df["info_name"] == sel_i].iloc[0]
                    st.session_state["i_name_in"] = curr["info_name"]
                    st.session_state["i_type_in"] = curr["type"] if curr["type"] in ["Данные", "Сервис"] else "Данные"
                    
                    # 🛠️ ПРЕОБРАЗОВАНИЕ СТРОКИ ФОРМАТОВ В СПИСОК ДЛЯ MULTISELECT
                    db_formats = curr["format"] or ""
                    # Очищаем от пробелов и фильтруем только те, что есть в справочнике
                    st.session_state["i_format_in"] = [f.strip() for f in db_formats.split(",") if f.strip() in formats_list]
                    
                    st.session_state["i_upd_in"] = curr["update"] if curr["update"] in periods_list else (periods_list[0] if periods_list else "")
                else:
                    st.session_state["i_name_in"] = ""
                    st.session_state["i_type_in"] = "Данные"
                    st.session_state["i_format_in"] = []
                    st.session_state["i_upd_in"] = periods_list[0] if periods_list else ""
                st.session_state["info_prev_sel"] = sel_i

            with st.form("info_save_form"):
                st.text_input("Название вида *", key="i_name_in")
                c1, c2, c3 = st.columns(3)
                with c1: st.selectbox("Тип", ["Данные", "Сервис"], key="i_type_in")
                with c2: 
                    # 🛠️ ЗАМЕНА SELECTBOX НА MULTISELECT
                    st.multiselect("Допустимые форматы", options=formats_list, key="i_format_in")
                with c3: 
                    st.selectbox("Срок обновления", options=periods_list, key="i_upd_in")
                
                if st.form_submit_button("💾 Сохранить вид", width="stretch"):
                    name = st.session_state["i_name_in"].strip()
                    # 🛠️ СКЛЕЙКА СПИСКА В СТРОКУ ПЕРЕД СОХРАНЕНИЕМ
                    fmt_string = ", ".join(st.session_state["i_format_in"])
                    
                    if name:
                        try:
                            if is_editing_i:
                                t_id = int(info_df[info_df["info_name"] == sel_i].iloc[0]["info_id"])
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "UPDATE_INFO_TYPE", "info_types", t_id, new={"name": name, "format": fmt_string})
                                session.execute(text("UPDATE info_types SET info_name=:n, type=:t, format=:f, \"update\"=:u WHERE info_id=:id"),
                                                {"n": name, "t": st.session_state["i_type_in"], "f": fmt_string, "u": st.session_state["i_upd_in"], "id": t_id})
                            else:
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "CREATE_INFO_TYPE", "info_types", None, new={"name": name, "format": fmt_string})
                                session.execute(text("INSERT INTO info_types (dataset_id, info_name, type, format, \"update\") VALUES (:did, :n, :t, :f, :u)"),
                                                {"did": sel_ds_id, "n": name, "t": st.session_state["i_type_in"], "f": fmt_string, "u": st.session_state["i_upd_in"]})
                            session.commit(); clear_cache(); st.success("✅ Сохранено!"); st.rerun()
                        except Exception as e: 
                            st.error(f"Ошибка: {e}"); session.rollback()

            if is_editing_i:
                if st.button("🗑 Удалить вид сведений", type="secondary", width="stretch", key="info_del_btn"):
                    t_id = int(info_df[info_df["info_name"] == sel_i].iloc[0]["info_id"])
                    in_use = session.execute(text("SELECT 1 FROM project_items WHERE info_id = :id LIMIT 1"), {"id": t_id}).scalar()
                    if in_use: 
                        st.error("❌ Нельзя удалить: этот вид сведений уже добавлен в проекты!")
                    else:
                        try:
                            log_action(st.session_state["auth"]["user_id"], "DELETE_INFO_TYPE", "info_types", t_id, old={"name": sel_i})
                            session.execute(text("DELETE FROM info_types WHERE info_id = :id"), {"id": t_id})
                            session.commit(); clear_cache(); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()