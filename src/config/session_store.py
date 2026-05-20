import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

SESSION_DIR = Path("app_data/sessions")
SESSION_DIR.mkdir(parents=True, exist_ok=True)

def create_token(auth_data: dict) -> str:
    """Сохраняет сессию на диск и возвращает UUID-токен."""
    token = str(uuid.uuid4())
    safe_data = auth_data.copy()
    # 🔹 Преобразуем datetime в строку для безопасной записи в JSON
    if isinstance(safe_data.get("last_active"), datetime):
        safe_data["last_active"] = safe_data["last_active"].isoformat()
    safe_data["_saved_at"] = datetime.now().isoformat()
    
    with open(SESSION_DIR / f"{token}.json", "w", encoding="utf-8") as f:
        json.dump(safe_data, f, ensure_ascii=False)
    return token

def restore_session(token: str) -> dict | None:
    """Восстанавливает сессию по токену. Возвращает None, если истекла или отсутствует."""
    path = SESSION_DIR / f"{token}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    saved_at = datetime.fromisoformat(data.pop("_saved_at", datetime.now().isoformat()))
    if datetime.now() - saved_at > timedelta(minutes=30):
        path.unlink(missing_ok=True)
        return None
        
    # 🔹 Фикс: преобразуем last_active обратно в datetime для check_session_timeout()
    if isinstance(data.get("last_active"), str):
        data["last_active"] = datetime.fromisoformat(data["last_active"])
        
    return data

def destroy_session(token: str) -> None:
    """Удаляет сессию с диска."""
    (SESSION_DIR / f"{token}.json").unlink(missing_ok=True)