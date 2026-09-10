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

    # Бюрократия проекта завершена, только когда подписаны ВСЕ его документы
    # (соглашение + протоколы). Раньше хватало одного закрытого CONTRACT_SIGNED,
    # из-за чего проект с подписанным соглашением и незакрытыми протоколами
    # считался завершённым. Проекты без заведённых документов - по-прежнему.
    doc_counts = session.execute(text("""
        SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_signed) AS signed
        FROM project_documents WHERE project_id = :pid
    """), {"pid": project_id}).mappings().first()

    if doc_counts and doc_counts['total'] > 0:
        is_signed = (doc_counts['signed'] == doc_counts['total'])
    else:
        # Подписание: у соглашения - "Документ подписан", у протокола - "Протокол подписан"
        is_signed = any(done_stages['stage_name'].isin(['Документ подписан', 'Протокол подписан'])
                        | done_stages['stage_code'].isin(['CONTRACT_SIGNED', 'PROTOCOL_SIGNED']))
    
    # --- РАСЧЕТ ЗАВЕРШЕННОСТИ ТЕХНОЛОГИИ ---
    # Сколько всего наборов в проекте
    total_items = session.execute(text("SELECT COUNT(*) FROM project_items WHERE project_id = :pid"), {"pid": project_id}).scalar()
    
    # Сколько УНИКАЛЬНЫХ наборов опубликовано. Вид сведений считается
    # опубликованным, когда закрыты ВСЕ его части: этап с part_id = NULL
    # закрывает вид целиком, этап с конкретной частью - только её.
    published_items = session.execute(text("""
        WITH pub AS (
            SELECT (aff ->> 'item_id')::int AS item_id,
                   (aff ->> 'part_id')::int AS part_id
            FROM project_stages ps
            CROSS JOIN LATERAL jsonb_array_elements(ps.affected_item_ids) AS aff
            JOIN stages s ON ps.stage_id = s.stage_id
            JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
            WHERE ps.project_id = :pid
              AND (s.stage_name = 'Публикация набора' OR s.stage_code = 'PUBLISHED')
              AND ms.micro_status_name = 'Выполнено'
        )
        SELECT COUNT(*)
        FROM project_items pi
        WHERE pi.project_id = :pid
          AND (
            -- этап на весь вид сведений
            EXISTS (SELECT 1 FROM pub WHERE pub.item_id = pi.item_id AND pub.part_id IS NULL)
            -- либо закрыты все части, заведённые у этого поставщика
            OR (
              EXISTS (SELECT 1 FROM project_item_part_details pd WHERE pd.item_id = pi.item_id)
              AND NOT EXISTS (
                SELECT 1 FROM project_item_part_details pd
                WHERE pd.item_id = pi.item_id
                  AND NOT EXISTS (
                    SELECT 1 FROM pub
                    WHERE pub.item_id = pi.item_id AND pub.part_id = pd.part_id
                  )
              )
            )
          )
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