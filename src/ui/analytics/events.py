import streamlit as st
import pandas as pd
from datetime import timedelta

from ui.analytics.data_provider import get_analytics_snapshot
from ui.analytics.kpi_logic import format_date_ru_local, badge_html

# ==========================================
# 🕘 ПОСЛЕДНИЕ СОБЫТИЯ
# ==========================================

def _build_events(raw_df):
    """Свод этапов обоих треков: одна строка на событие.

    Выполненные этапы датируются фактическим завершением, этапы в работе -
    фактическим началом; и те и другие попадают в одну ленту.

    Технологическая ветка снапшота развёрнута по affected_item_ids, поэтому один
    этап, затрагивающий несколько видов сведений, приходит несколькими одинаковыми
    строками. Здесь они схлопываются обратно в одно событие, а виды сведений
    (или их части) склеиваются в одну подпись.
    """
    done = raw_df[(raw_df['status'] == 'Выполнено') & raw_df['actual_end'].notna()].copy()
    done['event_date'] = done['actual_end']
    done['is_active'] = False

    # Этапы в работе всегда сверху ленты: они актуальны сегодня, независимо от
    # того, когда начались. Дата начала остаётся в подписи карточки.
    active = raw_df[(raw_df['status'] == 'В работе') & raw_df['actual_start'].notna()].copy()
    active['event_date'] = pd.Timestamp.today().normalize()
    active['started_at'] = active['actual_start']
    active['is_active'] = True
    done['started_at'] = pd.NaT

    df = pd.concat([done, active], ignore_index=True)
    if df.empty:
        return df

    # Ключ события: конкретная итерация конкретного этапа проекта
    df['event_key'] = (df['project_id'].astype(str) + '|' + df['track_type'] + '|'
                       + df['stage_code'].astype(str) + '|' + df['iteration_count'].astype(str))

    rows = []
    for _, grp in df.groupby('event_key', sort=False):
        first = grp.iloc[0]

        # Охват: у бюрократии этап всегда про проект целиком, у технологии -
        # про конкретные виды сведений (или их части)
        if first['track_type'] == 'tech':
            names = [n for n in grp['info_name'].dropna().unique().tolist()
                     if str(n).strip() and str(n) != '—']
            scope = "; ".join(names) if names else first['project_name']
        else:
            scope = first['project_name']

        rows.append({
            'event_date': first['event_date'],
            'started_at': first['started_at'],
            'is_active': bool(first['is_active']),
            'supplier_name': first['supplier_name'],
            'project_name': first['project_name'],
            'scope': scope,
            'stage_name': first['stage_name'],
            'stage_color': first.get('stage_color'),
            'track_type': first['track_type'],
            'comments': first['comments'],
            'iteration_count': first['iteration_count'],
        })

    events = pd.DataFrame(rows)
    return events.sort_values('event_date', ascending=False)


def render_events_tab():
    raw_df = get_analytics_snapshot()
    if raw_df.empty:
        st.info("Нет данных.")
        return

    events = _build_events(raw_df)
    if events.empty:
        st.info("Выполненных этапов пока нет.")
        return

    # --- ФИЛЬТРЫ ---
    c_sup, c_period = st.columns([0.6, 0.4])
    with c_sup:
        suppliers = ["Все"] + sorted(events['supplier_name'].dropna().unique().tolist())
        sel_sup = st.selectbox("Поставщик:", suppliers, key="ev_supplier")
    with c_period:
        period = st.radio("Период:", ["За неделю", "За месяц", "Всё время"],
                          horizontal=True, key="ev_period")

    if sel_sup != "Все":
        events = events[events['supplier_name'] == sel_sup]

    if period != "Всё время":
        days = 7 if period == "За неделю" else 30
        cutoff = pd.Timestamp.today().normalize() - timedelta(days=days)
        events = events[events['event_date'] >= cutoff]

    if events.empty:
        st.info("За выбранный период событий нет.")
        return

    st.caption(f"Событий: {len(events)}")

    # --- ЛЕНТА ---
    # Группировка по дате: заголовок-дата, под ним события этого дня
    for day, group in events.groupby(events['event_date'].dt.date, sort=False):
        st.markdown(f"##### {format_date_ru_local(day)}")
        for _, ev in group.iterrows():
            track_icon = "📄" if ev['track_type'] == 'bureaucracy' else "💻"
            s_color = ev.get('stage_color') or "#BDC3C7"
            s_text = "white" if str(s_color).lower() in ["#3498db", "#e74c3c", "#27ae60",
                                                        "#6c3483", "#2c3e50"] else "#333"
            with st.container(border=True):
                st.markdown(f"**🏢 {ev['supplier_name']}**")
                st.caption(f"📁 {ev['scope']}")

                it = f" (ит. {int(ev['iteration_count'])})" if pd.notna(ev['iteration_count']) else ""
                # Незакрытый этап помечается отдельным бейджем рядом с названием,
                # иначе пометка и название сливаются в одну полосу
                stage_badge = badge_html(f"{ev['stage_name']}{it}", s_color, s_text, icon=track_icon)
                if ev['is_active'] and pd.notna(ev['started_at']):
                    work_badge = badge_html(f"⏳ В работе с {format_date_ru_local(ev['started_at'].date())}",
                                            "#FDEBD0", "#935116")
                    st.markdown(
                        f'<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; '
                        f'font-size:0.95rem;">{work_badge}{stage_badge}</div>',
                        unsafe_allow_html=True)
                else:
                    st.markdown(stage_badge, unsafe_allow_html=True)

                # Пустой комментарий заменяется названием этапа: строка без текста
                # выглядела бы как потерянные данные
                comment = (ev['comments'] if pd.notna(ev['comments']) and str(ev['comments']).strip()
                           else ev['stage_name'])
                st.markdown(
                    f'<div style="margin-top:8px; padding:8px; background:#f9f9f9; '
                    f'border-left:3px solid {s_color}; font-size:0.85rem;">💬 {comment}</div>',
                    unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
