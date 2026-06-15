import streamlit as st
import pandas as pd
from config.cache import query_db

@st.cache_data(ttl=300)
def get_analytics_snapshot():
    """
    Централизованный сбор данных для всей аналитики.
    Выполняется один раз в 5 минут или при принудительном сбросе.
    """
    query = """
        SELECT 
            p.project_id, p.project_name, s.supplier_name, s.is_mandatory,
            stg.stage_name, stg.stage_order, stg.stage_type, stg.track_category,
            COALESCE(stg.duration_days, 14) as norm_days,
            ps.iteration_count,
            ms.micro_status_name as status,
            ps.planned_start, ps.planned_end, ps.actual_start, ps.actual_end,
            ps.comments, u.display_name as responsible_name, 
            'bureaucracy' as track_type,
            '—' as info_name,
            p.is_agreement_project
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id 
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id 
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        
        UNION ALL
        
        SELECT 
            p.project_id, p.project_name, s.supplier_name, s.is_mandatory,
            stg.stage_name, stg.stage_order, stg.stage_type, stg.track_category,
            COALESCE(stg.duration_days, 14) as norm_days,
            ist.iteration_count,
            ms.micro_status_name as status,
            ist.planned_start, ist.planned_end, ist.actual_start, ist.actual_end,
            ist.comments, u.display_name as responsible_name, 
            'tech' as track_type,
            it.info_name,
            p.is_agreement_project
        FROM item_stages ist
        JOIN project_items pi ON ist.item_id = pi.item_id
        JOIN projects p ON pi.project_id = p.project_id 
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN info_types it ON pi.info_id = it.info_id 
        JOIN stages stg ON ist.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id 
        LEFT JOIN users u ON ist.responsible_id = u.user_id
    """
    df = query_db(query)
    # Приведение типов данных
    for col in ['actual_start', 'actual_end', 'planned_end', 'planned_start']:
        df[col] = pd.to_datetime(df[col], errors='coerce')
    
    return df