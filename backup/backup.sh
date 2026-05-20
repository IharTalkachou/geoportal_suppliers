#!/bin/sh
set -e

if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$PGPASSWORD" ]; then
    echo "❌ Ошибка: отсутствуют DB_NAME, DB_USER или PGPASSWORD"
    exit 1
fi

BACKUP_DIR="/backups"
DAILY_DIR="$BACKUP_DIR/daily"
WEEKLY_DIR="$BACKUP_DIR/weekly"
mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

run_backup() {
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    DAY_OF_WEEK=$(date +"%u") # 1=Пн, 7=Вс
    
    echo "🔄 [$TIMESTAMP] Запуск бэкапа БД '$DB_NAME'..."
    pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$DAILY_DIR/backup_$TIMESTAMP.dump"
    echo "✅ Ежедневный бэкап создан."

    if [ "$DAY_OF_WEEK" -eq 7 ]; then
        cp "$DAILY_DIR/backup_$TIMESTAMP.dump" "$WEEKLY_DIR/weekly_$TIMESTAMP.dump"
        echo "📅 Создан еженедельный бэкап."
        # Оставляем 4 последних недельных
        ls -t "$WEEKLY_DIR"/weekly_*.dump 2>/dev/null | tail -n +5 | xargs -r rm --
    fi

    # Оставляем 7 последних ежедневных
    ls -t "$DAILY_DIR"/backup_*.dump 2>/dev/null | tail -n +8 | xargs -r rm --
    echo "🧹 Очистка завершена."
}

# 1. Запускаем бэкап сразу при старте контейнера
run_backup

# 2. Цикл каждые 24 часа
while true; do
    echo "⏳ Ожидание 24 часа до следующего бэкапа..."
    sleep 86400
    run_backup
done