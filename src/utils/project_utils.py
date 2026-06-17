import pandas as pd
from sqlalchemy import text

def sync_project_status(session, project_id: int):
    """
    Автоматически определяет и обновляет статус проекта на основе прогресса по этапам.
    Статусы: 1. Переговоры, 2. Верификация, 3. Согласование, 4. Размещение, 5. Завершено.
    """
    # 1. Загружаем все этапы проекта из обоих треков (для анализа)
    query = """
        SELECT s.stage_name, s.stage_code, ms.micro_status_name, 'buro' as track
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE ps.project_id = :pid
        
        UNION ALL
        
        SELECT s.stage_name, s.stage_code, ms.micro_status_name, 'tech' as track
        FROM item_stages ist
        JOIN project_items pi ON ist.item_id = pi.item_id
        JOIN stages s ON ist.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id
        WHERE pi.project_id = :pid
    """
    df = pd.read_sql(text(query), session.bind, params={"pid": project_id})

    # Если этапов вообще нет - оставляем текущий или ставим 1
    if df.empty:
        return

    # Вспомогательные наборы данных
    done_stages = df[df['micro_status_name'] == 'Выполнено']
    active_stages = df[df['micro_status_name'].isin(['В работе', 'Ожидание'])]
    
    # Ключевые маркеры
    has_application = any(df['stage_name'] == 'Заявка на размещение НПД')
    is_signed = any((done_stages['stage_name'] == 'Документ подписан') | (done_stages['stage_code'] == 'CONTRACT_SIGNED'))
    
    # Проверка завершенности технологии (Все наборы должны иметь этап Публикация в статусе Выполнено)
    # Сначала узнаем, сколько всего наборов в проекте
    total_items = session.execute(text("SELECT COUNT(*) FROM project_items WHERE project_id = :pid"), {"pid": project_id}).scalar()
    
    # Считаем, сколько наборов уже опубликовано
    published_items = session.execute(text("""
        SELECT COUNT(DISTINCT pi.item_id)
        FROM project_items pi
        JOIN item_stages ist ON pi.item_id = ist.item_id
        JOIN stages s ON ist.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id
        WHERE pi.project_id = :pid 
          AND (s.stage_name = 'Публикация набора' OR s.stage_code = 'PUBLISHED')
          AND ms.micro_status_name = 'Выполнено'
    """), {"pid": project_id}).scalar()

    tech_finished = (total_items > 0) and (published_items >= total_items)

    # --- ЛОГИКА ОПРЕДЕЛЕНИЯ (Приоритет от 5 к 1) ---
    
    new_status_id = 1 # По умолчанию

    if is_signed and tech_finished:
        new_status_id = 5 # Завершено
    
    elif is_signed or not df[df['track'] == 'tech'].empty:
        new_status_id = 4 # Размещение (Бумаги подписаны ИЛИ началась техника)
    
    elif any(df['stage_name'].isin(['Опросный лист получен', 'Составление проекта документа', 'Согласование документа'])):
        new_status_id = 3 # Согласование
        
    elif has_application:
        # Если была заявка, проверяем, не ушли ли мы дальше верификации
        # Если текущие этапы - только Заявка или Верификация
        verification_stages = ['Заявка на размещение НПД', 'Верификация заявки']
        current_stages = df['stage_name'].unique()
        
        # Если в проекте только верификационные этапы
        if all(s in verification_stages for s in current_stages):
            new_status_id = 2 # Верификация
        else:
            # Если проект начался с заявки, но уже пошли другие этапы (опросники и т.д.)
            new_status_id = 3 # Переходим в согласование
            
    else:
        new_status_id = 1 # Переговоры

    # 3. Обновляем статус в таблице projects
    session.execute(text("""
        UPDATE projects SET status = :sid WHERE project_id = :pid
    """), {"sid": new_status_id, "pid": project_id})
    session.commit()