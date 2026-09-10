import streamlit as st
import pandas as pd
from config.cache import query_db

@st.cache_data(ttl=60)
def get_analytics_snapshot():
    """
    Централизованный сбор данных для всей аналитики.
    Адаптировано под единую таблицу project_stages и JSONB affected_item_ids.
    """
    query = """
        -- 1. БЛОК БЮРОКРАТИИ
        SELECT 
            p.project_id, p.project_name, p.supplier_id, s.supplier_name, s.is_mandatory,
            stg.stage_name, stg.stage_order, stg.stage_type, 
            stg.stage_code,
            stg.track_category,
            COALESCE(stg.duration_days, 14) as norm_days,
            ps.iteration_count,
            ms.micro_status_name as status,
            ps.planned_start, ps.planned_end, ps.actual_start, ps.actual_end,
            ps.comments, u.display_name as responsible_name, 
            'bureaucracy' as track_type,
            '—' as info_name,
            stg.stage_color,
            p.is_agreement_project,
            -- Документы проекта (соглашение + протоколы): бюро-трек закрыт,
            -- только когда подписаны все. Читается в calculate_buro_progress.
            (SELECT COUNT(*) FROM project_documents pd WHERE pd.project_id = p.project_id) as docs_total,
            (SELECT COUNT(*) FROM project_documents pd WHERE pd.project_id = p.project_id AND pd.is_signed) as docs_signed
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id 
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id 
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE stg.track_category = '1. Документарный'

        UNION ALL
        
        -- 2. БЛОК ТЕХНОЛОГИИ (РАЗВЕРНУТЫЙ ИЗ JSONB)
        SELECT 
            p.project_id, p.project_name, p.supplier_id, s.supplier_name, s.is_mandatory,
            stg.stage_name, stg.stage_order, stg.stage_type, 
            stg.stage_code,
            stg.track_category,
            COALESCE(stg.duration_days, 14) as norm_days,
            ps.iteration_count,
            ms.micro_status_name as status,
            ps.planned_start, ps.planned_end, ps.actual_start, ps.actual_end,
            ps.comments, u.display_name as responsible_name, 
            'tech' as track_type,
            CASE WHEN itp.part_name IS NOT NULL
                 THEN it.info_name || ' — ' || itp.part_name
                 ELSE it.info_name END as info_name,
            stg.stage_color,
            p.is_agreement_project,
            NULL::bigint as docs_total,
            NULL::bigint as docs_signed
        FROM project_stages ps
        -- affected_item_ids: массив объектов {item_id, part_id};
        -- part_id = NULL означает "вид сведений целиком"
        CROSS JOIN LATERAL jsonb_array_elements(ps.affected_item_ids) AS aff
        JOIN project_items pi ON pi.item_id = (aff ->> 'item_id')::int
        JOIN projects p ON pi.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN info_types it ON pi.info_id = it.info_id
        LEFT JOIN info_type_parts itp ON itp.part_id = (aff ->> 'part_id')::int
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE stg.track_category = '2. Технологический'
    """
    df = query_db(query)
    
    # Приведение типов
    for col in ['actual_start', 'actual_end', 'planned_end', 'planned_start']:
        df[col] = pd.to_datetime(df[col], errors='coerce')
    
    return df

def clear_analytics_cache():
    """Функция для ручного сброса кэша аналитики"""
    st.cache_data.clear()