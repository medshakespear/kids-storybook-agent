"""Build dated event and undated reading-topic choices for the web generator."""
from datetime import date

from core.calendar_rules import event_period, today_in_timezone


def period_label(start: date, end: date) -> str:
    """Display an exact date or inclusive range with explicit years."""
    def stamp(day):
        """Format without platform-specific leading-zero directives."""
        return f'{day:%b} {day.day}, {day.year}'
    return stamp(start) if start == end else f'{stamp(start)} – {stamp(end)}'


def calendar_catalog(calendar: dict, *, today: date | None = None) -> dict:
    """Sort each event by its active or next configured occurrence, across New Year.

    No date is invented for undated topics or exhausted year-specific schedules.
    Seasonal periods are explicitly described as teaching windows, not observances.
    """
    reference = today or today_in_timezone()
    events, topics = [], []
    for source in calendar.get('events', []):
        if not source.get('enabled', True) or not source.get('theme_angles'):
            continue
        periods = []
        if source.get('schedule'):
            for year in range(reference.year - 1, reference.year + 3):
                period = event_period(source, year)
                if period and period[1] >= reference:
                    periods.append(period)
        if not periods:
            topics.append({**source, 'date_label': 'Date not configured',
                           'category': 'undated_topic',
                           'topic_group': 'Dates not configured'})
            continue
        start, end = min(periods)
        label = period_label(start, end)
        if source.get('category') == 'seasonal_theme' or source['event_name'] == 'Back to School':
            label += ' · Teaching window'
        if start <= reference <= end:
            label += ' · Current'
        events.append({**source, 'occurs_on': start.isoformat(),
                       'ends_on': end.isoformat(), 'date_label': label})
    names = {item['event_name'] for item in events + topics}
    for source in calendar.get('evergreen_topics', []):
        name, context = source['keyword'], source['topic']
        if name in names or not source.get('enabled', True):
            continue
        topics.append({'event_name': name, 'title_keywords': [name],
                       'theme_angles': source.get('theme_angles') or [
                           f'{context} Create original grade-appropriate readings with evidence, '
                           'inference, vocabulary and multiple-choice comprehension.'],
                       'keyword_topics': {name: context}, 'note': context,
                       'category': 'evergreen_topic', 'date_label': 'No fixed date',
                       'topic_group': source.get('subject', 'General reading')})
        names.add(name)
    events.sort(key=lambda item: (item['occurs_on'], item['ends_on'], item['event_name']))
    topics.sort(key=lambda item: (item['topic_group'], item['event_name']))
    return {'events': events, 'topics': topics, 'as_of': reference.isoformat()}
