"""Check future-week selection, calendar coverage and exact keyword title delivery."""
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import json
import random
import unittest

from core.calendar_rules import event_period, find_events_in_window
from core.theme_picker import pick_daily_book_specs
import cron_job


class CalendarKeywordTests(unittest.TestCase):
    """Run real picker contracts without calling AI or external delivery."""

    def setUp(self):
        """Load the shipped calendar and fresh state."""
        self.calendar=json.loads(Path('calendar.json').read_text())
        self.state={'generated':[]}

    def test_second_week_boundaries_and_overlapping_periods(self):
        """Exclude the first week/day14 while including day7/day13 and active months."""
        today=date(2026,12,25)
        events=[{'event_name':str(n),'schedule':{'kind':'fixed','month':(today+timedelta(days=n)).month,'day':(today+timedelta(days=n)).day},'theme_angles':['Read']} for n in (0,6,7,13,14)]
        events += [{'event_name':'Ongoing','schedule':{'kind':'range','month':12,'day':20,'end_month':1,'end_day':5},'theme_angles':['Read']},
                   {'event_name':'Ended','schedule':{'kind':'range','month':12,'day':20,'end_month':12,'end_day':31},'theme_angles':['Read']}]
        found=find_events_in_window({'events':events},today=today,start_offset=7,days=13)
        self.assertEqual({e['event_name'] for e in found},{'7','13','Ongoing'})
        specs=pick_daily_book_specs({'events':events},self.state,count=8,today=today,rng=random.Random(2))
        self.assertTrue(all(s['event_name'] in {'7','13','Ongoing'} for s in specs))
        self.assertTrue(all(s['selection_window_start']=='2027-01-01' and s['selection_window_end']=='2027-01-07' for s in specs))

    def test_today_calendar_excludes_early_and_late_october_events(self):
        """On October6 only observances overlapping October13-19 qualify."""
        choices={pick_daily_book_specs(self.calendar,self.state,count=1,today=date(2026,10,6),rng=random.Random(n))[0]['event_name'] for n in range(40)}
        self.assertEqual(choices,{'Hispanic Heritage Month','National Bullying Prevention Month'})

    def test_all_screenshot_holidays_are_enabled(self):
        """The missing pictured tags now have resolvable 2026 periods."""
        names=['April Fools\' Day','Arbor Day','Cinco de Mayo','Day of the Dead / Dia de los Muertos','Diwali','Easter',"Father's Day",'Groundhog Day','Lunar New Year','Mardi Gras',"Mother's Day",'Passover','Ramadan',"St. Patrick's Day",'Hanukkah / Chanukah','Christmas','Kwanzaa']
        by={e['event_name']:e for e in self.calendar['events']}
        for name in names:
            with self.subTest(name=name):
                self.assertIsNotNone(event_period(by[name],2026))

    def test_user_keyword_bank_is_complete(self):
        """Rank/volume numbers do not contaminate the fifty provided search phrases."""
        expected={'constitution day','grandparents day','hispanic heritage month','patriot day','bullying prevention month','red ribbon week','community helpers','labor day','dia de los muertos','columbus day','halloween bulletin board','indigenous peoples day','fire prevention week','halloween craft','diwali','apples','native american heritage month','fall','spiders','veterans day','back to school','day of the dead','christmas around the world','pumpkins','apple activities','fall activities','bats','halloween activities','election day','harvest','holidays around the world','hanukkah','addition','gratitude','thanksgiving','pumpkin activities','monsters','autumn','reindeer','5 senses','gingerbread','christmas','thanksgiving activities','santa','elves','kwanzaa','winter','christmas activities','new year','chanukah'}
        found={k.lower() for e in self.calendar['events'] for k in e['title_keywords']}
        found.update(t['keyword'].lower() for t in self.calendar['evergreen_topics'])
        self.assertFalse(expected-found)
        self.assertTrue(all(len(k)<=52 for e in self.calendar['events'] for k in e['title_keywords']))

    def test_movable_and_cross_year_dates(self):
        """No hardcoded 2026 dates for annual weekday holidays or Western Easter."""
        by={e['event_name']:e for e in self.calendar['events']}
        for name,year,start,end in [('Grandparents Day',2026,'2026-09-13','2026-09-13'),('Grandparents Day',2025,'2025-09-07','2025-09-07'),('Election Day and Civic Learning',2026,'2026-11-03','2026-11-03'),('Easter',2027,'2027-03-28','2027-03-28'),('Mardi Gras',2027,'2027-02-09','2027-02-09'),('Hanukkah / Chanukah',2027,'2027-12-24','2028-01-01'),('Kwanzaa',2026,'2026-12-26','2027-01-01')]:
            self.assertEqual(event_period(by[name],year),(date.fromisoformat(start),date.fromisoformat(end)))
        self.assertIsNone(event_period(by['Diwali'],2028))

    def test_random_titles_remain_tied_to_one_event_and_theme(self):
        """Keyword aliases are sampled inside their event, not across unrelated holidays."""
        halloween=next(e for e in self.calendar['events'] if e['event_name']=='Halloween')
        calendar={'events':[halloween]}
        specs=[pick_daily_book_specs(calendar,self.state,count=1,today=date(2026,10,20),rng=random.Random(n))[0] for n in range(40)]
        self.assertEqual({s['book_title'] for s in specs},set(halloween['title_keywords']))
        for spec in specs:
            self.assertEqual(spec['event_name'],'Halloween')
            self.assertIn(spec['book_title'],spec['theme'])
            self.assertEqual(spec['title_keyword'],spec['book_title'])

    def test_seasonal_then_evergreen_fallback(self):
        """Undated themes never pretend to be fixed-date holidays."""
        season=next(e for e in self.calendar['events'] if e['event_name']=='Fall Learning Themes')
        spec=pick_daily_book_specs({'events':[season]},self.state,count=1,today=date(2026,10,6),rng=random.Random(1))[0]
        self.assertEqual(spec['selection_mode'],'seasonal_theme')
        evergreen=pick_daily_book_specs({'events':[],'evergreen_topics':self.calendar['evergreen_topics']},self.state,count=4,today=date(2026,6,1),rng=random.Random(3))
        self.assertTrue(all(s['selection_mode']=='evergreen' for s in evergreen))
        self.assertTrue(all(s['book_title'] in {t['keyword'] for t in self.calendar['evergreen_topics']} for s in evergreen))

    def test_cron_passes_keyword_title_and_persists_window(self):
        """Use real specs and verify the full cron wiring without paid generation."""
        state={'generated':[]}
        captured={}
        def generate(**kwargs):
            """Simulate one completed PDF and record requested keyword/context."""
            captured.update(kwargs)
            return {'title':kwargs['book_title']},Path('/tmp/test-keyword-book.pdf')
        with patch.object(cron_job,'validate_providers'),patch.object(cron_job,'fetch_library_state',return_value=None),patch.object(cron_job,'load_state',return_value=state),patch.object(cron_job,'_daily_count',return_value=1),patch.object(cron_job,'today_in_timezone',return_value=date(2026,10,6)),patch.object(cron_job,'generate_book',side_effect=generate),patch.object(cron_job,'deliver_book',return_value=True),patch.object(cron_job,'save_state'),patch.object(cron_job,'commit_state_to_github',return_value=(True,'Saved')),redirect_stdout(io.StringIO()):
            self.assertEqual(cron_job.main(),0)
        record=state['generated'][0]
        self.assertIn(captured['book_title'],{'Bullying Prevention Month','Hispanic Heritage Month'})
        self.assertIn(captured['book_title'],captured['source_context'])
        self.assertEqual(record['title'],captured['book_title'])
        self.assertEqual(record['selection_window_start'],'2026-10-13')
        self.assertEqual(record['selection_window_end'],'2026-10-19')


if __name__=='__main__':
    unittest.main()
