# test_connection.py
import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "port": "5432",
    "database": "geodata_suppliers_dev",
    "user": "app_user_dev",       # <-- Проверьте имя пользователя
    "password": "app_user_pass"      # <-- Вставьте пароль вручную для теста
}

try:
    print(f"🔌 Попытка подключения к {DB_CONFIG['host']}:{DB_CONFIG['port']} как {DB_CONFIG['user']}...")
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ УСПЕХ: Подключение установлено!")
    cur = conn.cursor()
    cur.execute("SELECT current_user, current_database();")
    result = cur.fetchone()
    print(f"   Вы подключены как: {result[0]}, база: {result[1]}")
    conn.close()
except Exception as e:
    print(f"❌ ОШИБКА: {e}")
    print("\n💡 Возможные причины:")
    print("   1. Неверный пароль или имя пользователя")
    print("   2. Пользователь не имеет права CONNECT на базу")
    print("   3. PostgreSQL не слушает локальные подключения (проверьте pg_hba.conf)")
    print("   4. Служба PostgreSQL не запущена")