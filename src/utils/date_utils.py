import pandas as pd
from datetime import timedelta
from config.cache import query_db

def add_business_days(start_date, days_to_add):
    """
    Прибавляет к дате количество РАБОЧИХ дней, 
    учитывая выходные и праздники РБ из таблицы ref_calendar_exceptions.
    """
    # 1. Загружаем праздники из базы
    exceptions = query_db("SELECT exception_date, is_workday FROM ref_calendar_exceptions")
    holidays = set(exceptions[exceptions['is_workday'] == False]['exception_date'])
    extra_workdays = set(exceptions[exceptions['is_workday'] == True]['exception_date'])

    current_date = start_date
    added_days = 0
    
    while added_days < days_to_add:
        current_date += timedelta(days=1)
        
        # Проверяем, является ли день рабочим
        # День рабочий, если: (это не Сб/Вс И это не праздник) ИЛИ (это рабочая суббота)
        is_weekend = current_date.weekday() >= 5
        is_holiday = current_date in holidays
        is_forced_workday = current_date in extra_workdays
        
        if (not is_weekend and not is_holiday) or is_forced_workday:
            added_days += 1
            
    return current_date