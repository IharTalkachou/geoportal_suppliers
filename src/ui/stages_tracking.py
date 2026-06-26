import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
import json
from config.cache import query_db, clear_cache

def render_stages_tab(session):
    st.subheader("⚙️ Трекинг этапов выполнения")
    level = st.radio("Уровень детализации:", ["📦 Наборы (Технология)", "📂 Проекты (Бюрократия)"], horizontal=True)
    is_item_level = (level == "📦 Наборы (Технология)")
    
    # 🔑 Вся работа теперь идет с ОДНОЙ таблицей
    table_name = "project_stages"
    
    if is_item_level:
        # Для уровня наборов нам нужно знать и item_id, и проект, к которому он привязан
        entities = query_db("""
            SELECT i.item_id AS id, i.project_id, p.project_name, d.dataset_name, it.info_name 
            FROM project_items i 
            JOIN projects p ON i.project_id = p.project_id 
            JOIN datasets d ON i.dataset_id = d.dataset_id 
            JOIN info_types it ON i.info_id = it.info_id
        """)
    else:
        entities = query_db("SELECT project_id AS id, project_name FROM projects")
        entities["project_id"] = entities["id"]
        entities["dataset_name"] = ""
        entities["info_name"] = ""

    stages = query_db("SELECT stage_id, stage_name, stage_type, duration_days FROM stages ORDER BY stage_order")
    micro_statuses = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses")

    if stages.empty:
        st.error("❌ Справочник стадий пуст."); st.stop()

    stage_map = {row["stage_id"]: {"name": row["stage_name"], "type": row["stage_type"], "duration": row["duration_days"] or 0} for _, row in stages.iterrows()}
    entity_map = {row["id"]: f"{row['project_name']} / {row['dataset_name']} {row['info_name']}" if row['dataset_name'] else row['project_name'] for _, row in entities.iterrows()}

    st.markdown("---")
    st.subheader("➕ Регистрация этапа")

    with st.form("stage_reg_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            sel_id = st.selectbox("Объект", options=list(entity_map.keys()), format_func=lambda x: entity_map[x])
            sel_stage = st.selectbox("Стадия", options=stage_map.keys(), format_func=lambda x: stage_map[x]["name"])
        with col2:
            sel_micro = st.selectbox("Микростатус", options=micro_statuses["micro_status_id"].tolist(), 
                                     format_func=lambda x: micro_statuses[micro_statuses["micro_status_id"]==x]["micro_status_name"].values[0])
            planned_start = st.date_input("Плановое начало", value=date.today())
            
            info = stage_map[sel_stage]
            planned_end = planned_start if info["type"] == "Веха" else planned_start + timedelta(days=int(info["duration"]))
            st.caption(f"📅 План. завершение: {planned_end.strftime('%d.%m.%Y')}")
            
        with col3:
            actual_start = st.date_input("Фактическое начало", value=planned_start)
            comments = st.text_area("Комментарий", height=100)

        submit_btn = st.form_submit_button("💾 Сохранить этап", type="primary", width="stretch")

        if submit_btn:
            # Находим реальный project_id для записи
            target_proj_id = int(entities[entities["id"] == sel_id]["project_id"].iloc[0])
            
            # Подготовка affected_item_ids (если это уровень набора)
            affected_items = json.dumps([int(sel_id)]) if is_item_level else json.dumps([])

            # Итерация (считаем по проекту и стадии)
            iter_q = text(f"SELECT COALESCE(MAX(iteration_count), 0) FROM {table_name} WHERE project_id = :pid AND stage_id = :sid")
            max_iter = session.execute(iter_q, {"pid": target_proj_id, "sid": sel_stage}).scalar()
            new_iter = max_iter + 1

            try:
                session.execute(text(f"""
                    INSERT INTO {table_name} (project_id, stage_id, micro_status, iteration_count,
                                             planned_start, planned_end, actual_start, comments, affected_item_ids)
                    VALUES (:pid, :sid, :mst, :iter, :ps, :pe, :as, :comm, :items)
                """), {
                    "pid": target_proj_id, "sid": sel_stage, "mst": sel_micro,
                    "iter": new_iter, "ps": planned_start, "pe": planned_end,
                    "as": actual_start, "comm": comments, "items": affected_items
                })
                session.commit(); clear_cache()
                st.success(f"✅ Этап записан в общую таблицу. Итерация #{new_iter}"); st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка БД: {e}"); session.rollback()

    # 🔄 МАССОВОЕ КЛОНИРОВАНИЕ (Адаптировано)
    st.markdown("---")
    with st.expander("🔄 Массовое клонирование стадии"):
        clone_stage = st.selectbox("Клонируемая стадия", options=stage_map.keys(), format_func=lambda x: stage_map[x]["name"])
        clone_target_id = st.selectbox("Источник (чей этап копируем):", options=entity_map.keys(), format_func=lambda x: entity_map[x], key="clone_src")
        clone_btn = st.button("Запустить копирование для всех наборов проекта", type="secondary")
        
        if clone_btn:
            try:
                # 1. Находим все наборы этого же проекта
                target_proj_id = int(entities[entities["id"] == clone_target_id]["project_id"].iloc[0])
                all_items = query_db("SELECT item_id FROM project_items WHERE project_id = :pid", {"pid": target_proj_id})
                
                count = 0
                for _, row in all_items.iterrows():
                    tid = int(row["item_id"])
                    if tid == clone_target_id and is_item_level: continue # Пропускаем сам источник
                    
                    # Создаем новую запись в project_stages для каждого набора
                    session.execute(text(f"""
                        INSERT INTO {table_name} (project_id, stage_id, micro_status, iteration_count,
                                                 planned_start, planned_end, comments, affected_item_ids)
                        SELECT project_id, stage_id, micro_status, iteration_count, 
                               planned_start, planned_end, comments || ' [КЛОН]', :new_item_json
                        FROM {table_name} 
                        WHERE project_id = :pid AND stage_id = :sid 
                        AND (affected_item_ids @> :src_item_json OR affected_item_ids = '[]'::jsonb)
                        LIMIT 1
                    """), {
                        "pid": target_proj_id, 
                        "sid": clone_stage, 
                        "new_item_json": json.dumps([tid]),
                        "src_item_json": json.dumps([int(clone_target_id)]) if is_item_level else "[]"
                    })
                    count += 1
                
                session.commit(); clear_cache()
                st.success(f"✅ Создано {count} записей в проектном треке."); st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка: {e}"); session.rollback()