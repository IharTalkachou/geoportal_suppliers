import json
import uuid
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SESSION_DIR = Path(os.getenv("SESSION_DIR", "./sessions"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)
SESSION_TIMEOUT_MINUTES = 2

def _debug(msg: str):
    sys.stderr.write(f"[FP] {msg}\n")
    sys.stderr.flush()

def _get_client_ip(headers: dict) -> str:
    """Извлекает реальный IP пользователя с учетом прокси (Nginx)"""
    # X-Forwarded-For может содержать цепочку IP: "client_ip, proxy1_ip, proxy2_ip"
    xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return headers.get("X-Real-IP") or "unknown_ip"

def _normalize_fingerprint(ua: str, lang: str) -> str:
    """Создает стабильный ключ: Браузер/Версия/ОС/Язык."""
    ua = ua.lower() if ua else ""
    lang = lang.lower().split(",")[0].strip() if lang else "xx"

    # 1. Браузер + мажорная версия
    browser, ver = "unknown", "0"
    if "firefox/" in ua:
        browser = "firefox"
        m = re.search(r"firefox/([\d.]+)", ua)
    elif "edg/" in ua:
        browser = "edge"
        m = re.search(r"edg/([\d.]+)", ua)
    elif "chrome/" in ua:
        browser = "chrome"
        m = re.search(r"chrome/([\d.]+)", ua)
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "safari"
        m = re.search(r"version/([\d.]+)", ua)
    else:
        m = None
    if m: ver = m.group(1).split(".")[0]

    # 2. ОС
    os_name = "unknown"
    if "windows" in ua: os_name = "win"
    elif "macintosh" in ua or "mac os" in ua: os_name = "mac"
    elif "linux" in ua: os_name = "linux"
    elif "android" in ua: os_name = "android"
    elif "iphone" in ua or "ipad" in ua: os_name = "ios"

    return f"{browser}_{ver}_{os_name}_{lang}"

def _compute_fingerprint() -> dict:
    import streamlit as st
    try:
        headers = dict(st.context.headers) if hasattr(st.context, 'headers') else {}
        ua = headers.get("User-Agent") or headers.get("user-agent", "")
        lang = headers.get("Accept-Language") or headers.get("accept-language", "")
        ip = _get_client_ip(headers)
        
        fp_key = _normalize_fingerprint(ua, lang)
        return {"fp_key": fp_key, "ip": ip}
    except Exception as e:
        _debug(f"⚠️ FP Error: {e}")
        return {"fp_key": f"err_{type(e).__name__}", "ip": "unknown"}

def _fingerprints_match(stored: dict, current: dict, strict_ip: bool = True) -> bool:
    """Сверяет отпечатки. В корпоративной сети strict_ip = True обязателен!"""
    if stored.get("fp_key") != current.get("fp_key"):
        return False
    if strict_ip and stored.get("ip") != current.get("ip"):
        return False
    return True

def _kill_previous_sessions(user_id: str):
    """Обеспечивает правило: 1 пользователь = 1 сессия"""
    if not user_id: return
    for p in SESSION_DIR.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("user_id") == user_id:
                p.unlink(missing_ok=True)
                _debug(f"🚪 Killed previous session for user {user_id}")
        except:
            continue

def create_token(auth_data: dict) -> str:
    # 1. Убиваем старые сессии этого пользователя (предотвращаем мульти-логин)
    user_id = auth_data.get("user_id")
    _kill_previous_sessions(user_id)

    # 2. Создаем новую
    token = str(uuid.uuid4())
    safe_data = auth_data.copy()
    safe_data["_ui_state"] = {k: v for k, v in {
        "selected_supplier_id": auth_data.get("ui_supplier_id"),
        "selected_project_id": auth_data.get("ui_project_id"),
        "show_admin": auth_data.get("ui_show_admin", False)
    }.items() if v is not None}
    
    safe_data["_fingerprint"] = _compute_fingerprint()
    if isinstance(safe_data.get("last_active"), datetime):
        safe_data["last_active"] = safe_data["last_active"].isoformat()
    
    safe_data["_saved_at"] = datetime.now().isoformat()
    
    with open(SESSION_DIR / f"{token}.json", "w", encoding="utf-8") as f:
        json.dump(safe_data, f, ensure_ascii=False)
        
    _debug(f"🔑 Created: {token[:8]}... | FP: {safe_data['_fingerprint']['fp_key']} | IP: {safe_data['_fingerprint']['ip']}")
    return token

def restore_session(token: str, strict_ip: bool = True) -> dict | None:
    import streamlit as st
    fp = SESSION_DIR / f"{token}.json"
    if not fp.exists(): 
        return None
    
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # Проверка на истечение времени (от последнего действия)
    saved_time_str = data.get("_saved_at", datetime.now().isoformat())
    saved = datetime.fromisoformat(saved_time_str)
    
    if datetime.now() - saved > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        fp.unlink(missing_ok=True)
        _debug("⏱ Session Expired.")
        return None
        
    current_fp = _compute_fingerprint()
    stored_fp = data.get("_fingerprint", {})
    
    # ПРОВЕРКА ОТПЕЧАТКА (ЗАЩИТА ОТ КРАЖИ ССЫЛКИ)
    if not _fingerprints_match(stored_fp, current_fp, strict_ip):
        _debug("🚨 MISMATCH! Unauthorized access attempt. Session kept alive for original user.")
        # ВАЖНО: Мы больше НЕ удаляем файл сессии (fp.unlink). 
        # Просто отказываем в доступе этому конкретному браузеру.
        try:
            from config.auth import log_action
            log_action(user_id=data.get("user_id"), action="SESSION_HIJACK_ATTEMPT", 
                       target_table="auth", old=stored_fp, new=current_fp)
        except: pass
        return None
        
    # Восстановление прошло успешно
    
    # ПРОДЛЕНИЕ ЖИЗНИ СЕССИИ (Sliding Expiration)
    # Переписываем _saved_at на текущее время, чтобы таймаут 30 мин обновлялся при Ctrl+R
    data["_saved_at"] = datetime.now().isoformat()
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    if isinstance(data.get("last_active"), str):
        data["last_active"] = datetime.fromisoformat(data["last_active"])
    
    # Восстановление UI State
    ui_state = data.get("_ui_state", {})
    for k, v in ui_state.items():
        if v is not None: st.session_state[k] = v
        
    _debug(f"✅ Restored & Extended: {token[:8]}...")
    return data

def destroy_session(token: str) -> None:
    (SESSION_DIR / f"{token}.json").unlink(missing_ok=True)
    _debug(f"🗑 Destroyed: {token[:8]}...")

def cleanup_expired_sessions() -> int:
    """Удаляет сессии, которые не обновлялись больше SESSION_TIMEOUT_MINUTES.
    Вызывать эту функцию можно при старте приложения или раз в N запусков."""
    removed = 0
    cutoff = datetime.now() - timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    for p in SESSION_DIR.glob("*.json"):
        try:
            # Читаем json, чтобы узнать точное _saved_at (надежнее, чем время изменения файла)
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved = datetime.fromisoformat(data.get("_saved_at", "2000-01-01T00:00:00"))
            if saved < cutoff:
                p.unlink()
                removed += 1
        except Exception:
            # Если файл битый - сносим его
            p.unlink(missing_ok=True)
            removed += 1
    return removed

def sync_session_to_disk(token: str, auth_data: dict):
    """
    Синхронизирует текущее состояние авторизации из памяти на диск.
    Это критично для поддержания 'скользящего' таймаута.
    """
    if not token:
        return
    
    fp = SESSION_DIR / f"{token}.json"
    try:
        # 1. Сначала подгружаем текущие данные с диска, чтобы не затереть Fingerprint и UI State
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = auth_data.copy()

        # 2. Обновляем метку времени и данные пользователя
        data["_saved_at"] = datetime.now().isoformat()
        
        # Переносим важные изменения из памяти (например, если сменилось имя или роль)
        for key in ["user_id", "username", "display_name", "role", "role_name"]:
            if key in auth_data:
                data[key] = auth_data[key]

        # 3. Сохраняем обратно
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            
    except Exception as e:
        _debug(f"❌ Sync Error: {e}")