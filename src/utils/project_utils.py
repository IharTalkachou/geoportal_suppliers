import pandas as pd
from sqlalchemy import text

def sync_project_status(session, project_id: int):
    """
    Автоматически определяет и обновляет статус проекта на основе прогресса по этапам.
    Адаптировано под единую таблицу project_stages и JSONB наборы.
    """
    # 1. Загружаем все этапы проекта из единой таблицы
    # Мы определяем трек (buro/tech) на основе track_category из справочника стадий
    query = """
        SELECT s.stage_name, s.stage_code, ms.micro_status_name, 
               CASE WHEN s.track_category = '1. Документарный' THEN 'buro' ELSE 'tech' END as track
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE ps.project_id = :pid
    """
    df = pd.read_sql(text(query), session.bind, params={"pid": project_id})

    if df.empty:
        return

    # Вспомогательные наборы данных
    done_stages = df[df['micro_status_name'] == 'Выполнено']
    
    # Ключевые маркеры
    has_application = any(df['stage_name'] == 'Заявка на размещение НПД')
    is_signed = any((done_stages['stage_name'] == 'Документ подписан') | (done_stages['stage_code'] == 'CONTRACT_SIGNED'))
    
    # --- РАСЧЕТ ЗАВЕРШЕННОСТИ ТЕХНОЛОГИИ ---
    # Сколько всего наборов в проекте
    total_items = session.execute(text("SELECT COUNT(*) FROM project_items WHERE project_id = :pid"), {"pid": project_id}).scalar()
    
    # Считаем, сколько УНИКАЛЬНЫХ наборов уже опубликовано (извлекая их из JSONB массивов)
    published_items = session.execute(text("""
        SELECT COUNT(DISTINCT item_id)
        FROM (
            SELECT jsonb_array_elements_text(ps.affected_item_ids)::int as item_id
            FROM project_stages ps
            JOIN stages s ON ps.stage_id = s.stage_id
            JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
            WHERE ps.project_id = :pid 
              AND (s.stage_name = 'Публикация набора' OR s.stage_code = 'PUBLISHED')
              AND ms.micro_status_name = 'Выполнено'
        ) sub
    """), {"pid": project_id}).scalar()

    tech_finished = (total_items > 0) and (published_items >= total_items)

    # --- ЛОГИКА ОПРЕДЕЛЕНИЯ (Приоритет от 5 к 1) ---
    new_status_id = 1 # По умолчанию

    if is_signed and tech_finished:
        new_status_id = 5 # Завершено
    elif is_signed or not df[df['track'] == 'tech'].empty:
        new_status_id = 4 # Размещение
    elif any(df['stage_name'].isin(['Опросный лист получен', 'Составление проекта документа', 'Согласование документа'])):
        new_status_id = 3 # Согласование
    elif has_application:
        verification_stages = ['Заявка на размещение НПД', 'Верификация заявки']
        current_stages = df['stage_name'].unique()
        if all(s in verification_stages for s in current_stages):
            new_status_id = 2 # Верификация
        else:
            new_status_id = 3 # Переходим в согласование
    else:
        new_status_id = 1 # Переговоры

    # 3. Обновляем статус в таблице projects
    session.execute(text("""
        UPDATE projects SET status = :sid WHERE project_id = :pid
    """), {"sid": new_status_id, "pid": project_id})
    session.commit()