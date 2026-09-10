#!/bin/sh
# Ежедневный бэкап БД.
#
# ВАЖНО: set -e здесь намеренно НЕ используется. Раньше он стоял, и падение
# pg_dump (например, когда БД временно недоступна) завершало весь скрипт ДО
# входа в цикл ожидания. Контейнер умирал, restart: unless-stopped поднимал его
# заново, скрипт снова падал - получался краш-луп с бэкапом каждые несколько
# минут. Ротация при этом исправно работала и вытесняла настоящие дампы
# пустыми файлами, так что история бэкапов терялась целиком.

if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$PGPASSWORD" ]; then
    echo "❌ Ошибка: отсутствуют DB_NAME, DB_USER или PGPASSWORD"
    exit 1
fi

BACKUP_DIR="/backups"
DAILY_DIR="$BACKUP_DIR/daily"
WEEKLY_DIR="$BACKUP_DIR/weekly"
mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

# Час, в который делается ежедневный бэкап (0-23). Можно переопределить в .env
BACKUP_HOUR="${BACKUP_HOUR:-3}"

run_backup() {
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    DAY_OF_WEEK=$(date +"%u") # 1=Пн, 7=Вс
    TARGET="$DAILY_DIR/backup_$TIMESTAMP.dump"

    echo "🔄 [$TIMESTAMP] Запуск бэкапа БД '$DB_NAME'..."
    if ! pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$TARGET"; then
        # Неудачный дамп оставляет за собой пустой или оборванный файл -
        # удаляем его, иначе он попадёт в ротацию как полноценный бэкап
        echo "❌ Бэкап не удался, файл удалён. Прошлые дампы сохранены."
        rm -f "$TARGET"
        return 1
    fi

    # Пустой дамп - тоже неудача, даже если pg_dump вернул 0
    if [ ! -s "$TARGET" ]; then
        echo "❌ Дамп пуст, файл удалён. Прошлые дампы сохранены."
        rm -f "$TARGET"
        return 1
    fi

    echo "✅ Ежедневный бэкап создан: $(du -h "$TARGET" | cut -f1)"

    if [ "$DAY_OF_WEEK" -eq 7 ]; then
        cp "$TARGET" "$WEEKLY_DIR/weekly_$TIMESTAMP.dump"
        echo "📅 Создан еженедельный бэкап."
        # Оставляем 4 последних недельных
        ls -t "$WEEKLY_DIR"/weekly_*.dump 2>/dev/null | tail -n +5 | xargs -r rm --
    fi

    # Ротация только после удачного дампа: иначе неудача вытесняет рабочие копии
    ls -t "$DAILY_DIR"/backup_*.dump 2>/dev/null | tail -n +8 | xargs -r rm --
    echo "🧹 Очистка завершена."
    return 0
}

# Сколько секунд осталось до ближайшего BACKUP_HOUR.
# Привязка ко времени суток, а не sleep 86400 от старта: при перезапуске
# контейнера расписание иначе съезжает на время перезапуска.
seconds_until_backup_hour() {
    # %H/%M/%S, а не %-H: последний - GNU-расширение, в BusyBox (alpine) его нет.
    # Приведение 10#... обязательно: "08" и "09" иначе трактуются как
    # восьмеричные числа и роняют арифметику.
    NOW_H=$(date +"%H")
    NOW_M=$(date +"%M")
    NOW_S=$(date +"%S")
    NOW_TOTAL=$(( 10#$NOW_H * 3600 + 10#$NOW_M * 60 + 10#$NOW_S ))
    TARGET_TOTAL=$(( BACKUP_HOUR * 3600 ))
    DIFF=$(( TARGET_TOTAL - NOW_TOTAL ))
    if [ "$DIFF" -le 0 ]; then
        DIFF=$(( DIFF + 86400 ))
    fi
    echo "$DIFF"
}

# 1. Бэкап сразу при старте контейнера
run_backup || echo "⚠️ Стартовый бэкап не удался, продолжаем по расписанию."

# 2. Далее - ежедневно в BACKUP_HOUR
while true; do
    WAIT=$(seconds_until_backup_hour)
    echo "⏳ Следующий бэкап в ${BACKUP_HOUR}:00 (через $(( WAIT / 3600 )) ч $(( (WAIT % 3600) / 60 )) мин)"
    sleep "$WAIT"
    run_backup || echo "⚠️ Бэкап не удался, следующая попытка по расписанию."
done
