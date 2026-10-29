"""
Справочник способов передачи данных (ref_data_methods), правится в
Админ-панели -> Справочники.
"""
import sys

from config.cache import query_db

# Особое значение: форма состава проекта блокирует для него срок данных.
# В Админ-панели защищено от переименования и удаления.
DATA_METHOD_NOT_TRANSMITTED = "Не передаются"

# Прежний список из кода - на случай, если миграция b2d6e83f4a17 ещё не применена
_FALLBACK_DATA_METHODS = ["Сервис (WMS/WFS)", "Ссылка на облако", "Прямая загрузка",
                          "Носитель", DATA_METHOD_NOT_TRANSMITTED]


def load_data_methods():
    try:
        df = query_db("SELECT method_name FROM ref_data_methods ORDER BY sort_order, method_id")
        methods = df["method_name"].tolist()
    except Exception as e:
        print(f"ref_data_methods недоступен: {e}", file=sys.stderr)
        methods = []
    return methods or list(_FALLBACK_DATA_METHODS)


def options_with_current(options, current):
    """Значение из записи, которого уже нет в справочнике, остаётся в списке -
    иначе выпадающий список подменил бы его первым вариантом при сохранении."""
    if current and current not in options:
        return list(options) + [current]
    return list(options)
