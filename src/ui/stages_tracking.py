import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache  # 🔑 Импорт

def render_stages_tab(session):
    st.subheader("⚙️ Трекинг этапов выполнения")
    level = st.radio("Уровень детализации:", ["📦 Наборы (ItemStages)", "📂 Проекты (ProjectStages)"], horizontal=True)
    is_item_level = (level == "📦 Наборы (ItemStages)")
    
    # 🔑 Чтение через кэш
    if is_item_level:
        entities = query_db("""
            SELECT i.item_id AS id, p.project_name, d.dataset_name, it.info_name 
            FROM project_items i JOIN projects p ON i.project_id = p.project_id 
            JOIN datasets d ON i.dataset_id = d.dataset_id JOIN info_types it ON i.info_id = it.info_id
        """)
        fk_col, table_name = "item_id", "item_stages"
    else:
        entities = query_db("SELECT project_id AS id, project_name FROM projects")
        entities["dataset_name"] = ""
        entities["info_name"] = ""
        fk_col, table_name = "project_id", "project_stages"

    stages = query_db("SELECT stage_id, stage_name, stage_type, duration_days FROM stages ORDER BY stage_order")
    micro_statuses = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses")

    if stages.empty:
        st.error("❌ Запрос вернул 0 строк. Кэш не сброшен или подключение не проходит.")
        st.stop()

    stage_map = {row["stage_id"]: {"name": row["stage_name"], "type": row["stage_type"], "duration": row["duration_days"] or 0} for _, row in stages.iterrows()}
    stage_options = list(stage_map.keys())

    entity_map = {row["id"]: f"{row['project_name']} / {row['dataset_name']}" if row['dataset_name'] else row['project_name'] for _, row in entities.iterrows()}

    st.markdown("---")
    st.subheader("➕ Регистрация этапа")

    with st.form("stage_reg_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            sel_entity = st.selectbox("Объект", options=list(entity_map.keys()), format_func=lambda x: entity_map[x])
            sel_stage = st.selectbox("Стадия", options=stage_map.keys(), format_func=lambda x: stage_map[x]["name"])
        with col2:
            sel_micro = st.selectbox("Микростатус", options=micro_statuses["micro_status_id"], format_func=lambda x: micro_statuses[micro_statuses["micro_status_id"]==x]["micro_status_name"].values[0])
            planned_start = st.date_input("Плановое начало", value=date.today())
            
            # 🔧 ЛОГИКА 1: AutoCalculateDates (перенос из Access)
            info = stage_map[sel_stage]
            if info["type"] == "Веха":
                planned_end = planned_start
            else:
                planned_end = planned_start + timedelta(days=int(info["duration"]))
            st.caption(f"📅 Плановое окончание: {planned_end.strftime('%d.%m.%Y')}")
            
        with col3:
            actual_start = st.date_input("Фактическое начало", value=planned_start)
            comments = st.text_area("Комментарий", height=100)

        submit_btn = st.form_submit_button("💾 Сохранить этап", type="primary", use_container_width=True)

        if submit_btn:
            # 🔧 ЛОГИКА 2: IterationCount (автоинкремент)
            iter_q = text(f"SELECT COALESCE(MAX(iteration_count), 0) FROM {table_name} WHERE {fk_col} = :eid AND stage_id = :sid")
            max_iter = session.execute(iter_q, {"eid": sel_entity, "sid": sel_stage}).scalar()
            new_iter = max_iter + 1

            # 🔧 ЛОГИКА 3: Форматирование Notes
            notes_formatted = f"{planned_start.strftime('%d.%m.%Y')}. {info['name']} (ит. {new_iter}) [{sel_micro}]: {comments or 'Без комментария'}"

            try:
                session.execute(text(f"""
                    INSERT INTO {table_name} ({fk_col}, stage_id, micro_status, iteration_count,
                                             planned_start, planned_end, actual_start, comments)
                    VALUES (:eid, :sid, :mst, :iter, :ps, :pe, :as, :comm)
                """), {
                    "eid": sel_entity, "sid": sel_stage, "mst": sel_micro,
                    "iter": new_iter, "ps": planned_start, "pe": planned_end,
                    "as": actual_start, "comm": notes_formatted
                })
                session.commit()
                clear_cache()
                st.success(f"✅ Этап записан. Итерация #{new_iter}. Лог: `{notes_formatted[:50]}...`")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка БД: {e}")
                session.rollback()

    # 🔧 ЛОГИКА 4: Клонирование стадии (аналог Кнопка33_Click)
    st.markdown("---")
    with st.expander("🔄 Массовое клонирование стадии"):
        clone_stage = st.selectbox("Клонируемая стадия", options=stage_map.keys(), format_func=lambda x: stage_map[x]["name"])
        clone_target = st.selectbox("Клонировать для всех наборов поставщика:", options=entity_map.keys(), format_func=lambda x: entity_map[x])
        clone_btn = st.button("Запустить клонирование", type="secondary")
        
        if clone_btn:
            try:
                # Начинаем транзакцию явно
                with session.begin():
                    # Получаем список всех target_id для выбранного поставщика
                    targets = pd.read_sql(text(f"SELECT {fk_col} FROM projects WHERE supplier_id = (SELECT supplier_id FROM projects WHERE project_id = :pid LIMIT 1)"), session.bind, params={"pid": clone_target if is_item_level else clone_target})
                    
                    # Если уровень Item, берём item_id из project_items
                    if is_item_level:
                        targets = pd.read_sql(text("SELECT item_id FROM project_items WHERE project_id = :pid"), session.bind, params={"pid": clone_target})
                    
                    count = 0
                    for _, row in targets.iterrows():
                        tid = row.iloc[0]
                        # Проверяем, нет ли уже такой стадии у этого объекта
                        exists = session.execute(text(f"SELECT 1 FROM {table_name} WHERE {fk_col} = :tid AND stage_id = :sid LIMIT 1"), {"tid": tid, "sid": clone_stage}).scalar()
                        if not exists:
                            session.execute(text(f"""
                                INSERT INTO {table_name} ({fk_col}, stage_id, micro_status, iteration_count,
                                                         planned_start, planned_end, comments)
                                SELECT :tid, stage_id, micro_status, iteration_count+1, 
                                       planned_start, planned_end, comments || ' [СКЛОНИРОВАНО]'
                                FROM {table_name} WHERE {fk_col} = :src AND stage_id = :sid LIMIT 1
                            """), {"tid": tid, "src": clone_target, "sid": clone_stage})
                            count += 1
                    st.success(f"✅ Клонировано {count} новых этапов.")
                    clear_cache()
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка клонирования: {e}")
                session.rollback()