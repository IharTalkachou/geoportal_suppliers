import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache

def render_bureaucracy_tab(session, project_id):
    st.subheader("📜 Бюрократия (Документарные этапы)")
    st.caption("⚙️ Итерация и плановые даты считаются автоматически. Факт. начало закрывает предыдущий этап.")

    # 📖 Справочник этапов (только документарный трек, сортировка по order)
    stages = query_db("""
        SELECT stage_id, stage_name, stage_type, duration_days, stage_order
        FROM stages 
        WHERE track_category = '1. Документарный'
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

    # 📊 Текущие этапы проекта
    ps_df = query_db("""
        SELECT ps.stage_progress_id, s.stage_name, ms.micro_status_name,
               ps.iteration_count, ps.planned_start, ps.planned_end,
               ps.actual_start, ps.actual_end, ps.comments
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE ps.project_id = :pid
        ORDER BY s.stage_order, ps.iteration_count
    """, {"pid": project_id})

    # ⚙️ Конфиг редактора
    col_config = {
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

    with st.form("buro_editor_form"):
        edited_df = st.data_editor(
            ps_df, key="buro_editor", hide_index=True, use_container_width=True,
            num_rows="dynamic", column_config=col_config, disabled=["stage_progress_id"],
            column_order=["stage_name", "micro_status_name", "iteration_count", "planned_start", 
                         "planned_end", "actual_start", "actual_end", "comments"]  # 🔹 ID скрыт из UI
        )

        orig_ids = set(ps_df["stage_progress_id"].dropna().astype(int))
        curr_ids = set(edited_df["stage_progress_id"].dropna().astype(int))
        deleted_ids = orig_ids - curr_ids

        if st.form_submit_button("💾 Сохранить этапы", type="primary"):
            try:
                if deleted_ids:
                    session.execute(text("DELETE FROM project_stages WHERE stage_progress_id IN :ids"), {"ids": tuple(deleted_ids)})

                for _, row in edited_df.iterrows():
                    pid = row.get("stage_progress_id")
                    is_new = pd.isna(pid)

                    stage_info = stage_map.get(row.get("stage_name"))
                    if not stage_info:
                        continue

                    micro_id = micro_map.get(row.get("micro_status_name"))
                    
                    def to_sql_date(val):
                        if pd.isna(val) or val is None:
                            return None
                        if isinstance(val, date):
                            return val
                        if isinstance(val, pd.Timestamp):
                            return val.date()
                        try:
                            return pd.to_datetime(val).date()
                        except:
                            return None

                    p_start_raw = row.get("planned_start")
                    a_start_raw = row.get("actual_start")
                    a_end_raw = row.get("actual_end")
                    
                    p_start = to_sql_date(p_start_raw)
                    a_start = to_sql_date(a_start_raw)
                    a_end = to_sql_date(a_end_raw)
                    comment = row.get("comments") or ""

                    # 📅 Авто-расчёт планового окончания
                    p_end = None
                    if p_start is not None:
                        if stage_info["type"] == "Веха":
                            p_end = p_start
                        else:
                            p_end = p_start + timedelta(days=stage_info["duration"])

                    # 🔢 Авто-итерация
                    iteration = 1
                    if is_new:
                        max_iter = session.execute(text("""
                            SELECT COALESCE(MAX(iteration_count), 0) FROM project_stages
                            WHERE project_id = :pid AND stage_id = :sid
                        """), {"pid": project_id, "sid": stage_info["id"]}).scalar()
                        iteration = max_iter + 1
                    else:
                        iteration = int(row.get("iteration_count", 1))

                    # 🎯 Авто-закрытие предыдущего этапа
                    if is_new and a_start is not None and completed_status_id is not None:
                        session.execute(text("""
                            UPDATE project_stages 
                            SET actual_end = :close_date, micro_status = :completed_id
                            WHERE stage_progress_id = (
                                SELECT ps.stage_progress_id FROM project_stages ps
                                WHERE ps.project_id = :pid 
                                  AND ps.actual_end IS NULL 
                                ORDER BY (SELECT s.stage_order FROM stages s WHERE s.stage_id = ps.stage_id) DESC, 
                                         ps.iteration_count DESC
                                LIMIT 1
                            )
                        """), {
                            "close_date": a_start,
                            "completed_id": completed_status_id,
                            "pid": project_id
                        })

                    # 🔹 Для Вехи: факт. окончание = факт. началу
                    if a_start is not None and stage_info["type"] == "Веха":
                        a_end = a_start

                    # 💾 Запись в БД
                    if is_new:
                        session.execute(text("""
                            INSERT INTO project_stages (project_id, stage_id, micro_status, iteration_count,
                                                        planned_start, planned_end, actual_start, actual_end, comments)
                            VALUES (:pid, :sid, :mst, :iter, :ps, :pe, :as, :ae, :comm)
                        """), {
                            "pid": project_id, "sid": stage_info["id"], "mst": micro_id,
                            "iter": iteration, "ps": p_start, "pe": p_end,
                            "as": a_start, "ae": a_end, "comm": comment
                        })
                    else:
                        session.execute(text("""
                            UPDATE project_stages SET stage_id=:sid, micro_status=:mst, iteration_count=:iter,
                                                      planned_start=:ps, planned_end=:pe, 
                                                      actual_start=:as, actual_end=:ae, comments=:comm
                            WHERE stage_progress_id=:id
                        """), {
                            "sid": stage_info["id"], "mst": micro_id,
                            "iter": iteration,
                            "ps": p_start, "pe": p_end,
                            "as": a_start, "ae": a_end, "comm": comment,
                            "id": int(pid)
                        })

                session.commit()
                clear_cache()
                st.success("✅ Этапы сохранены! Автоматические расчёты применены.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка БД: {e}")
                session.rollback()