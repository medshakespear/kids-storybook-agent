"""Check chronological manual choices without altering the random cron window."""
from datetime import date
import json
from pathlib import Path
import unittest

from core.calendar_catalog import calendar_catalog, period_label


def event(name, schedule=None, **extra):
    """Make a minimal selectable calendar event."""
    return dict(event_name=name, schedule=schedule, theme_angles=['Read original texts.'], **extra)


class CalendarCatalogTests(unittest.TestCase):
    """Verify resolved dates, cross-year order and honest undated labels."""

    def test_chronology_replaces_alphabetical_order_with_current_periods_first(self):
        """September-starting ongoing periods precede late October and November."""
        calendar = {'events': [
            event('A November Event', {'kind':'fixed', 'month':11, 'day':1}),
            event('Z Halloween', {'kind':'fixed', 'month':10, 'day':31}),
            event('Current month', {'kind':'month', 'month':10}),
            event('Heritage period', {'kind':'range', 'month':9, 'day':15, 'end_month':10, 'end_day':15}),
        ]}
        rows = calendar_catalog(calendar, today=date(2026,10,10))['events']
        self.assertEqual([r['event_name'] for r in rows],
                         ['Heritage period', 'Current month', 'Z Halloween', 'A November Event'])
        self.assertEqual(rows[0]['date_label'], 'Sep 15, 2026 – Oct 15, 2026 · Current')
        self.assertEqual(rows[2]['date_label'], 'Oct 31, 2026')

    def test_movable_events_and_new_year_have_actual_year_dates(self):
        """A passed holiday rolls forward, and weekday dates are recalculated."""
        calendar = {'events': [
            event('New Year', {'kind':'fixed', 'month':1, 'day':1}),
            event('Thanksgiving', {'kind':'nth_weekday', 'month':11, 'weekday':3, 'nth':4}),
            event('Kwanzaa', {'kind':'range', 'month':12, 'day':26, 'end_month':1, 'end_day':1}),
        ]}
        rows = calendar_catalog(calendar, today=date(2026,12,24))['events']
        self.assertEqual([r['event_name'] for r in rows], ['Kwanzaa','New Year','Thanksgiving'])
        self.assertEqual(rows[0]['date_label'], 'Dec 26, 2026 – Jan 1, 2027')
        self.assertEqual(rows[1]['date_label'], 'Jan 1, 2027')
        self.assertEqual(rows[2]['date_label'], 'Nov 25, 2027')

    def test_undated_and_expired_specific_dates_are_separate_from_dated_events(self):
        """No invented dates or re-enabled disabled events enter the calendar selector."""
        calendar = {'events': [
            event('Unscheduled'),
            event('Needs update', {'kind':'dates','years':{'2026':['2026-01-02','2026-01-02']}}),
            event('Disabled', {'kind':'fixed','month':12,'day':1}, enabled=False),
        ], 'evergreen_topics': [{'keyword':'Ocean Ecosystems','topic':'Learn about ocean habitats.', 'subject':'Science'}]}
        catalog = calendar_catalog(calendar, today=date(2027,10,10))
        self.assertEqual(catalog['events'], [])
        self.assertEqual({r['event_name'] for r in catalog['topics']},
                         {'Unscheduled','Needs update','Ocean Ecosystems'})
        ocean = next(r for r in catalog['topics'] if r['event_name']=='Ocean Ecosystems')
        self.assertEqual(ocean['date_label'], 'No fixed date')
        self.assertIn('Learn about ocean habitats.', ocean['theme_angles'][0])
        self.assertNotIn('occurs_on', ocean)

    def test_seasonal_periods_are_labeled_as_teaching_windows(self):
        """Teaching dates are displayed without turning them into official observances."""
        calendar = {'events':[event('Fall', {'kind':'range','month':9,'day':1,'end_month':11,'end_day':30},category='seasonal_theme')]}
        row = calendar_catalog(calendar,today=date(2026,10,10))['events'][0]
        self.assertIn('Teaching window', row['date_label'])
        self.assertIn('Current', row['date_label'])

    def test_shipped_topics_have_subjects_original_angles_and_selectable_titles(self):
        """Useful new topics are available independently of holiday dates."""
        calendar = json.loads(Path('calendar.json').read_text())
        catalog = calendar_catalog(calendar,today=date(2026,10,10))
        by_name = {r['event_name']:r for r in catalog['topics']}
        for name in ('The Solar System','Media Literacy','Digital Citizenship','Accessible Communities',
                     'Money Choices','Animal Adaptations','Mysteries Solved with Evidence'):
            with self.subTest(topic=name):
                self.assertEqual(by_name[name]['date_label'],'No fixed date')
                self.assertEqual(by_name[name]['title_keywords'],[name])
                self.assertEqual(len(by_name[name]['theme_angles']),2)
        self.assertGreaterEqual(len(by_name),28)
        starts = [r['occurs_on'] for r in catalog['events']]
        self.assertEqual(starts, sorted(starts))

    def test_range_labels_never_omit_cross_year_dates(self):
        """Every range retains both years for clear planning."""
        self.assertEqual(period_label(date(2026,12,4),date(2026,12,12)), 'Dec 4, 2026 – Dec 12, 2026')


if __name__ == '__main__':
    unittest.main()
