import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache

def render_technology_tab(session, project_id):
    st.subheader("⚙️ Технология (Этапы по наборам)")
    st.caption("⚙️ Итерация и плановые даты считаются автоматически. Факт. начало закрывает предыдущий этап.")

    # 🔍 1. Загружаем ТОЛЬКО состав текущего проекта для фильтров
    project_items = query_db("""
        SELECT pi.item_id, d.dataset_name, i.info_name
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        WHERE pi.project_id = :pid
        ORDER BY d.dataset_name, i.info_name
    """, {"pid": project_id})

    if project_items.empty:
        st.info("📭 В составе этого проекта пока нет наборов данных. Добавьте их в блоке «Состав проекта» выше.")
        return

    # 🔍 2. Фильтры
    available_datasets = sorted(project_items["dataset_name"].dropna().unique().tolist())
    selected_ds = st.selectbox("🔍 Набор данных", [""] + available_datasets, key="tech_ds_sel")

    available_infos = []
    if selected_ds:
        available_infos = sorted(
            project_items[project_items["dataset_name"] == selected_ds]["info_name"]
            .dropna().unique().tolist()
        )
    selected_info = st.selectbox("🔍 Вид сведений", [""] + available_infos, key="tech_info_sel")

    if selected_ds and selected_info:
        item_record = project_items[
            (project_items["dataset_name"] == selected_ds) & 
            (project_items["info_name"] == selected_info)
        ]
        if not item_record.empty:
            selected_item_id = int(item_record.iloc[0]["item_id"])
        else:
            st.warning("⚠️ Связка не найдена. Обновите страницу или проверьте состав проекта.")
            return
    else:
        st.info("👆 Выберите Набор и Вид сведений из состава проекта для просмотра этапов.")
        return

    # 📖 Справочник этапов (только технологический трек)
    stages = query_db("""
        SELECT stage_id, stage_name, stage_type, duration_days, stage_order
        FROM stages 
        WHERE track_category = '2. Технологический'
        ORDER BY stage_order
    """)
    micro_statuses = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses ORDER BY micro_status_id")

    stage_map = {
        row["stage_name"]: {
            "id": row["stage_id"],
            "type": row["stage_type"],
            "duration": int(row["duration_days"] or 0),
            "order": row["stage_order"]
        }
        for _, row in stages.iterrows()
    }
    micro_map = dict(zip(micro_statuses["micro_status_name"], micro_statuses["micro_status_id"]))
    completed_status_id = micro_map.get("Выполнено")

    # 📊 Текущие этапы для выбранного набора
    stages_df = query_db("""
        SELECT ist.stage_progress_id, s.stage_name, ms.micro_status_name,
               ist.iteration_count, ist.planned_start, ist.planned_end,
               ist.actual_start, ist.actual_end, ist.comments
        FROM item_stages ist
        JOIN stages s ON ist.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id
        WHERE ist.item_id = :iid
        ORDER BY s.stage_order, ist.iteration_count
    """, {"iid": selected_item_id})

    # ⚙️ Конфиг редактора
    stage_col_config = {
        "stage_name": st.column_config.SelectboxColumn("Этап", options=list(stage_map.keys()), required=True),
        "micro_status_name": st.column_config.SelectboxColumn("Микростатус", options=list(micro_map.keys()), required=True),
        "iteration_count": st.column_config.NumberColumn("🔒 Итерация", format="%d", disabled=True),
        "planned_start": st.column_config.DateColumn("План. начало", required=True),
        "planned_end": st.column_config.DateColumn("🔒 План. конец", disabled=True),
        "actual_start": st.column_config.DateColumn("Факт. начало"),
        "actual_end": st.column_config.DateColumn("Факт. окончание"),
        "comments": st.column_config.TextColumn("Комментарий"),
        "stage_progress_id": st.column_config.NumberColumn("ID", disabled=True)
    }

    with st.form("tech_item_stages_form"):
        edited_stages = st.data_editor(
            stages_df, key="tech_item_stages_editor", hide_index=True, use_container_width=True,
            num_rows="dynamic", column_config=stage_col_config, disabled=["stage_progress_id"],
            column_order=["stage_name", "micro_status_name", "iteration_count", "planned_start", 
                         "planned_end", "actual_start", "actual_end", "comments"]  # 🔹 ID скрыт из UI
        )

        orig_ids = set(stages_df["stage_progress_id"].dropna().astype(int))
        curr_ids = set(edited_stages["stage_progress_id"].dropna().astype(int))
        deleted_ids = list(orig_ids - curr_ids)

        if st.form_submit_button("💾 Сохранить этапы набора", type="primary"):
            try:
                # 🔻 Удаления
                if deleted_ids:
                    session.execute(text("DELETE FROM item_stages WHERE stage_progress_id IN :ids"), {"ids": tuple(deleted_ids)})

                # 🔧 Универсальный конвертер дат
                def to_sql_date(val):
                    if pd.isna(val) or val is None:
                        return None
                    if isinstance(val, date):
                        return val
                    if isinstance(val, pd.Timestamp):
                        return val.date()
                    try:
                        return pd.to_datetime(val).date()
                    except Exception:
                        return None

                # 🔺 Вставка и 🔄 Обновление
                for _, row in edited_stages.iterrows():
                    sid = row.get("stage_progress_id")
                    is_new = pd.isna(sid)

                    stage_info = stage_map.get(row.get("stage_name"))
                    if not stage_info:
                        continue

                    micro_id = micro_map.get(row.get("micro_status_name"))
                    p_start = to_sql_date(row.get("planned_start"))
                    a_start = to_sql_date(row.get("actual_start"))
                    a_end = to_sql_date(row.get("actual_end"))
                    comment = row.get("comments") or ""

                    # 📅 1. Авто-расчёт планового окончания
                    p_end = None
                    if p_start is not None:
                        if stage_info["type"] == "Веха":
                            p_end = p_start
                        else:
                            p_end = p_start + timedelta(days=stage_info["duration"])

                    # 🔢 2. Авто-итерация
                    iteration = 1
                    if is_new:
                        max_iter = session.execute(text("""
                            SELECT COALESCE(MAX(iteration_count), 0) FROM item_stages
                            WHERE item_id = :iid AND stage_id = :sid
                        """), {"iid": selected_item_id, "sid": stage_info["id"]}).scalar()
                        iteration = max_iter + 1
                    else:
                        iteration = int(row.get("iteration_count", 1))

                    # 🎯 3. АВТО-ЗАКРЫТИЕ ПРЕДЫДУЩЕГО ЭТАПА/ИТЕРАЦИИ
                    if is_new and a_start is not None and completed_status_id is not None:
                        session.execute(text("""
                            UPDATE item_stages
                            SET actual_end = :close_date, micro_status = :completed_id
                            WHERE stage_progress_id = (
                                SELECT ist.stage_progress_id FROM item_stages ist
                                WHERE ist.item_id = :iid
                                  AND ist.actual_end IS NULL
                                ORDER BY (SELECT s.stage_order FROM stages s WHERE s.stage_id = ist.stage_id) DESC,
                                         ist.iteration_count DESC
                                LIMIT 1
                            )
                        """), {
                            "close_date": a_start,
                            "completed_id": completed_status_id,
                            "iid": selected_item_id
                        })

                    # 🔹 Для Вехи: факт. окончание = факт. началу
                    if a_start is not None and stage_info["type"] == "Веха":
                        a_end = a_start

                    # 💾 Запись в БД
                    if is_new:
                        session.execute(text("""
                            INSERT INTO item_stages (item_id, stage_id, micro_status, iteration_count,
                                                     planned_start, planned_end, actual_start, actual_end, comments)
                            VALUES (:iid, :sid, :mst, :iter, :ps, :pe, :as, :ae, :comm)
                        """), {
                            "iid": selected_item_id, "sid": stage_info["id"], "mst": micro_id,
                            "iter": iteration, "ps": p_start, "pe": p_end,
                            "as": a_start, "ae": a_end, "comm": comment
                        })
                    else:
                        session.execute(text("""
                            UPDATE item_stages SET stage_id=:sid, micro_status=:mst, iteration_count=:iter,
                                                   planned_start=:ps, planned_end=:pe,
                                                   actual_start=:as, actual_end=:ae, comments=:comm
                            WHERE stage_progress_id=:id
                        """), {
                            "sid": stage_info["id"], "mst": micro_id,
                            "iter": iteration,
                            "ps": p_start, "pe": p_end,
                            "as": a_start, "ae": a_end, "comm": comment,
                            "id": int(sid)
                        })

                session.commit()
                clear_cache()
                st.success("✅ Этапы набора сохранены! Автоматические расчёты применены.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка БД: {e}")
                session.rollback()