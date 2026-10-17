"""Regress text-comparison intent, eight omitted cards, and mixed canonical wrappers."""
from copy import deepcopy
import re
import unittest

from core.difference_intent import requires_exact_differences
from core.content_binding import bind_formatted_canonical_text
from core.label_bindings import restore_declared_card_group
from core.simple_exercises import check_simple_activity
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page
from tests.test_reading_bindings import plain_text


def ready_page():
    """Use production writing-space floors before comparing retained questions."""
    page=evidence_page()
    for q,space in zip(page['exercise']['questions'],(35,50)):q['space_mm']=space
    return page


def eight_cards_page():
    """Reproduce all eight declared but unprinted c1..c8 source statements."""
    page=ready_page()
    statements=['1. Monday rainfall measured 12 millimeters.','2. Rainy days are the most enjoyable days.',
        '3. Tuesday rainfall measured 8 millimeters.','4. Sunny weather feels much nicer than rain.',
        '5. Wednesday rainfall measured 6 millimeters.','6. Wednesday weather was the best of all.',
        '7. Thursday rainfall measured 4 millimeters.','8. Thursday rain was the most beautiful.']
    page['exercise']['captions']=[{'id':f'c{i}','text':text} for i,text in enumerate(statements,1)]
    page['exercise'].update(mechanic='fact_opinion_classification',directions='Classify all eight printed statements, then explain one opinion.')
    page['exercise']['questions'][0].update(prompt='Classify statements 1 to 8 as Fact or Opinion.',
        answer='1 Fact; 2 Opinion; 3 Fact; 4 Opinion; 5 Fact; 6 Opinion; 7 Fact; 8 Opinion.')
    page['exercise']['questions'][1].update(prompt='Explain why statement 2 expresses an opinion.',
        answer='Most enjoyable is a personal preference that cannot be measured.')
    return page


class WrittenCardsRecoveryTests(unittest.TestCase):
    """Preserve exact content, reject real image puzzles and retain writing geometry."""

    def test_textual_differences_do_not_request_picture_puzzles(self):
        """Declared written cards and conceptual customs remain written comparisons."""
        for instruction in ('Spot the differences between Card A and Card B.',
                            'Find differences between the two written cards.',
                            'Identify differences between two harvest traditions.'):
            page=ready_page();page['exercise']['directions']=instruction
            self.assertFalse(requires_exact_differences(dict(page,exercise_binding=True)))
            check_simple_activity(page['exercise'])
            for band in ('3rd-4th','5th-6th'):
                result=fixtures.CompleteStudentTaskTests().ask(page,band)
                self.assertEqual(result['exercise']['directions'],instruction)
        for instruction in ('Spot differences between the two pictures.',
                            'Find differences between traditions shown in two pictures.'):
            exercise={'render_mode':'authored','directions':instruction,'questions':[]}
            self.assertTrue(requires_exact_differences({'exercise_binding':True,'exercise':exercise}))
            with self.assertRaisesRegex(ValueError,'Simple workbook'):check_simple_activity(exercise)

    def test_all_declared_cards_restore_in_both_bands_after_one_response(self):
        """Omitted reference cards render once, with full questions and response panels."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                raw=eight_cards_page();before=deepcopy(raw)
                page=fixtures.CompleteStudentTaskTests().ask(raw,band)
                self.assertEqual(raw,before)
                self.assertEqual(page['exercise']['captions'],before['exercise']['captions'])
                self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
                self.assertEqual(page['images'],before['images'])
                text=plain_text(page['html'])
                for card in raw['exercise']['captions']:self.assertEqual(text.count(card['text']),1)
                self.assertIn('height:35mm',page['html']);self.assertIn('height:50mm',page['html'])

    def test_nested_wrapper_retains_complete_sibling_text_and_media(self):
        """A known caption can own one whole paragraph without swallowing the others."""
        for band in ('3rd-4th','5th-6th'):
            raw=ready_page();raw['exercise']['captions']=[{'id':'intro','text':'Weather Records'},
                {'id':'details','text':'Measurement Details'}]
            art=re.search(r'<img[^>]+/>',raw['html']).group()
            raw['html']=raw['html'].replace(art,'<div data-content="caption_intro"><p>Weather Records</p><p>Measurement Details</p>'+art+'</div>')
            before=deepcopy(raw);page=fixtures.CompleteStudentTaskTests().ask(raw,band)
            self.assertEqual(raw,before);self.assertEqual(page['images'],before['images'])
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            for text in ('Weather Records','Measurement Details'):self.assertEqual(plain_text(page['html']).count(text),1)

    def test_unrelated_or_ambiguous_fields_remain_protected(self):
        """Do not invent card identities or discard conflicting wording and work areas."""
        exercise=eight_cards_page()['exercise'];blocks={'caption_'+c['id']:c['text'] for c in exercise['captions']}
        markup='<div data-content="question_1"></div>'
        for change in ('partial','short','instruction','image_label','disabled'):
            altered=deepcopy(exercise);options={'simple_exercises_only':True};html=markup
            if change=='partial':html='<p data-content="caption_c1"></p>'+html
            elif change=='short':altered['captions'][0]['text']='Rain'
            elif change=='instruction':altered['captions'][0]['text']='Write a new weather report.'
            elif change=='image_label':html='<img data-asset="c1">'+html
            else:options={}
            self.assertEqual(restore_declared_card_group(html,blocks,altered,options),html,change)
        html='<div data-content="caption_intro"><p>Conflicting wording</p><img data-asset="weather"><div style="height:50mm;border:1px solid blue"></div></div>'
        result=bind_formatted_canonical_text(html,{'caption_intro':'Weather Records'},separate_protected=True)
        self.assertIn('Conflicting wording',result);self.assertIn('height:50mm',result)
        self.assertIn('data-asset="weather"',result)


if __name__=='__main__':unittest.main()
