"""
Признаки технологического трека по видам сведений: данные/метаданные получены
и опубликованы. Единый расчёт для карточки проекта (паспорт) и сводного отчёта
о поставщиках (№9), чтобы оба показывали одинаковое положение дел.

Признак = выполненный этап (любая итерация) с охватом affected_item_ids:
- элемент охвата с part_id = NULL закрывает вид сведений целиком (и все его части);
- элемент с конкретной частью закрывает только её.

Единица учёта - строка состава: вид сведений, а у разбитого на части вида
(есть строки project_item_part_details) - каждая его часть.
"""
import pandas as pd

from config.cache import query_db

# Признак -> этап, выполнение которого его выставляет
TECH_FLAG_STAGES = {
    'data_received': 'DATA_TRANSFER',   # Передача данных Оператору
    'data_published': 'DATA_PUB',       # Наборы опубликованы
    'meta_received': 'META_WAIT',       # Размещение метаданных Поставщиком
    'meta_published': 'META_PUB',       # Метаданные опубликованы
}

# Публикация без закрытого этапа получения - противоречие в данных этапов
TECH_FLAG_PAIRS = (
    ('data_received', 'data_published'),
    ('meta_received', 'meta_published'),
)


class TechFlagIndex:
    """Выполненные этапы TECH_FLAG_STAGES, разложенные по охвату."""

    def __init__(self, project_id=None):
        sql = """
            SELECT DISTINCT (aff ->> 'item_id')::int AS item_id,
                   (aff ->> 'part_id')::int AS part_id,
                   stg.stage_code
            FROM project_stages ps
            CROSS JOIN LATERAL jsonb_array_elements(ps.affected_item_ids) AS aff
            JOIN stages stg ON ps.stage_id = stg.stage_id
            JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
            WHERE stg.stage_code IN :codes
              AND ms.micro_status_name = 'Выполнено'
        """
        params = {"codes": tuple(TECH_FLAG_STAGES.values())}
        if project_id is not None:
            sql += " AND ps.project_id = :pid"
            params["pid"] = int(project_id)
        df = query_db(sql, params)

        self._whole = set()
        self._parts = set()
        for _, t in df.iterrows():
            if pd.isna(t['part_id']):
                self._whole.add((int(t['item_id']), t['stage_code']))
            else:
                self._parts.add((int(t['item_id']), int(t['part_id']), t['stage_code']))

    def done(self, item_id, part_id, code):
        if (item_id, code) in self._whole:
            return True
        return part_id is not None and (item_id, part_id, code) in self._parts

    def flags(self, item_id, part_id):
        """Все четыре признака для строки состава (вид сведений или его часть)."""
        return {flag: self.done(item_id, part_id, code)
                for flag, code in TECH_FLAG_STAGES.items()}


def flag_conflicts(flags):
    """Признаки публикации, выставленные без признака получения."""
    return [pub for rec, pub in TECH_FLAG_PAIRS if flags[pub] and not flags[rec]]


def project_tech_flags(project_id):
    """Признаки проекта целиком.

    Признак выставлен, только когда он выставлен по ВСЕМ строкам состава
    проекта; пустой состав - ни один признак не выставлен (передавать нечего).
    conflicts - признаки публикации, у которых хотя бы по одной строке
    публикация закрыта, а получение нет: {'data_published': [подписи строк], ...}.
    """
    units = query_db("""
        SELECT pi.item_id, pd.part_id, i.info_name, itp.part_name
        FROM project_items pi
        JOIN info_types i ON pi.info_id = i.info_id
        LEFT JOIN project_item_part_details pd ON pd.item_id = pi.item_id
        LEFT JOIN info_type_parts itp ON itp.part_id = pd.part_id
        WHERE pi.project_id = :pid
        ORDER BY i.info_name, itp.sort_order NULLS LAST, itp.part_id
    """, {"pid": int(project_id)})

    result = {flag: not units.empty for flag in TECH_FLAG_STAGES}
    conflicts = {}
    index = TechFlagIndex(project_id)
    for _, u in units.iterrows():
        part_id = int(u['part_id']) if pd.notna(u['part_id']) else None
        f = index.flags(int(u['item_id']), part_id)
        for flag, value in f.items():
            result[flag] = result[flag] and value
        label = (f"{u['info_name']} — {u['part_name']}" if part_id is not None
                 else u['info_name'])
        for pub in flag_conflicts(f):
            conflicts.setdefault(pub, []).append(label)

    return result, conflicts
