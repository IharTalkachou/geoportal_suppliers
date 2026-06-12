from datetime import datetime, timedelta
from sqlalchemy import delete
from src.config.database import SessionLocal
from src.models.tables import AuditLog

def clear_old_audit_logs(days_to_keep: int = 30):
    """
    Удаляет записи из таблицы audit_log старше указанного количества дней.
    """
    db = SessionLocal()
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        stmt = delete(AuditLog).where(AuditLog.created_at < cutoff_date)
        result = db.execute(stmt)
        db.commit()
        return result.rowcount  # Возвращает количество удаленных строк
    except Exception as e:
        db.rollback()
        print(f"Ошибка при очистке логов: {e}")
        return 0
    finally:
        db.close()