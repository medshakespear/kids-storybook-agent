"""Regress named source aliases, neutral count headers and written math contexts."""
from copy import deepcopy
import unittest

from core.activity_stimuli import normalize_stimulus_ids
from core.simple_exercises import check_simple_activity
from core.table_captions import prepare_table_captions
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page


class SourceLettersAndMathContextTests(unittest.TestCase):
    """Recover only explicit identities and preserve real evidence and student actions."""

    def test_four_text_aliases_bind_to_the_corresponding_declared_cards(self):
        """Text A-D are aliases for A-D, never a reason to invent replacement sources."""
        page={'html':''.join(f'<p data-content="stimulus_text_{letter}"></p>' for letter in 'abcd'),
              'exercise':{'render_mode':'authored','captions':[],
                          'stimuli':[{'id':'card_'+letter,'text':f'Complete source {letter.upper()} contains its own evidence.'} for letter in 'abcd']}}
        originals=deepcopy(page['exercise']['stimuli'])
        normalize_stimulus_ids(page,page['exercise'])
        self.assertEqual(page['exercise']['stimuli'],originals)
        for letter in 'abcd':self.assertIn('stimulus_card_'+letter,page['html'])
        once=deepcopy(page);normalize_stimulus_ids(page,page['exercise']);self.assertEqual(page,once)

    def test_aliases_remain_strict_when_identity_or_prefilled_evidence_conflicts(self):
        """Do not steal a used source, pick between two A records or swallow artwork."""
        for case in ('used','ambiguous','conflicting','duplicate','media','missing_letter','competing_alias'):
            page={'html':'<p data-content="stimulus_text_a"></p>',
                'exercise':{'render_mode':'authored','captions':[],
                    'stimuli':[{'id':'card_a','text':'Original A evidence.'}]}}
            if case=='used':page['html']+='<p data-content="stimulus_card_a"></p>'
            elif case=='ambiguous':page['exercise']['stimuli'].append({'id':'source_a','text':'Different A evidence.'})
            elif case=='conflicting':page['html']=page['html'].replace('></p>','>Different evidence.</p>')
            elif case=='duplicate':page['html']*=2
            elif case=='media':page['html']=page['html'].replace('></p>','><img data-asset="scene"/></p>')
            elif case=='missing_letter':page['html']=page['html'].replace('text_a','text_b')
            elif case=='competing_alias':page['html']+='<p data-content="stimulus_reading_a"></p>'
            before=deepcopy(page);normalize_stimulus_ids(page,page['exercise']);self.assertEqual(page,before,case)

    def test_named_source_recovery_runs_in_one_completion_in_both_bands(self):
        """Use real binding and A4 layout, with every source and key retained."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page()
            for old,new in (('note_a','card_a'),('note_b','card_b')):
                next(s for s in raw['exercise']['stimuli'] if s['id']==old)['id']=new
                raw['html']=raw['html'].replace('stimulus_'+old,'stimulus_text_'+new[-1])
            before=deepcopy(raw);result=fixtures.CompleteStudentTaskTests().ask(raw,band)
            self.assertEqual(result['exercise']['stimuli'],before['exercise']['stimuli'])
            for old,new in zip(before['exercise']['questions'],result['exercise']['questions']):
                self.assertEqual(old['prompt'],new['prompt']);self.assertEqual(old['answer'],new['answer'])
            self.assertNotIn('stimulus_text_',result['html'])

    def test_empty_count_header_is_organizational_but_data_cells_are_not_inferred(self):
        """Count may label a column; no student response or numeric total is generated."""
        page={'exercise':{'render_mode':'authored','captions':[]},
              'html':'<table><tr><th data-content="caption_th_count"></th></tr><tr><td></td></tr></table>'}
        prepare_table_captions(page)
        self.assertEqual(page['exercise']['captions'],[{'id':'th_count','text':'Count'}])
        self.assertIn('<td',page['html'])
        for tag in ('td','p'):
            page={'exercise':{'render_mode':'authored','captions':[]},
                  'html':f'<table><tr><{tag} data-content="caption_th_count"></{tag}></tr></table>'}
            before=deepcopy(page);prepare_table_captions(page);self.assertEqual(page,before)

    def test_planning_allows_reasoning_idioms_and_math_about_craft_materials(self):
        """Written calculations about materials need no drawing or crafting from students."""
        for concept in ('Students draw conclusions from the supplied data.',
                        'Students construct equations to solve cultural heritage word problems.',
                        'Students craft a written explanation of their calculation.',
                        'Solve word problems about the cost of templates.',
                        'Calculate the area of templates from the printed measurements.'):
            check_simple_activity({'render_mode':'authored','mechanic':'word_problems',
                'activity_concept':concept,'learning_goal':'Use printed data.'},planning=True)
        for concept in ('Students draw a cultural symbol.',
                        'Students construct equations and then paint a poster.',
                        'Solve word problems. Complete the drawing template.',
                        'Calculate costs and then use templates to create a banner.'):
            with self.assertRaisesRegex(ValueError,'Simple workbook'):
                check_simple_activity({'render_mode':'authored','mechanic':'word_problems',
                    'activity_concept':concept},planning=True)
