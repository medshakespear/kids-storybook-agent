"""Regress numbered reading aliases, counted matching labels and hard math-bound repairs."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.response_schemas import design_schema
from core.calculation_attachment import label_matching_text
from tests import test_complete_student_tasks as fixtures
from tests.test_binding_alias_regressions import matching_page
from tests.test_text_body_vocabulary import text_card_page
from tests.test_student_workbook import workbook_config


class NumberedSourcesHardLimitsTests(unittest.TestCase):
    """Use real shared-content/print checks, mocking only provider completions."""

    def ask(self,replies,band='5th-6th'):
        """Run the production retry/merge logic and return the validated page and API spy."""
        config=workbook_config(band,simple=True);api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(reply)),finish_reason='stop')]) for reply in replies]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(12,12,coherent=True),lambda raw:validate_design(raw,12,quality=config,
                expected_title='Source and Data Practice',require_coherent=True),'Activity design 8',
                response_schema=design_schema({'render_mode':'authored','mechanic':'data_interpretation'},config))
        return result,api

    def test_four_numbered_terms_are_labels_not_a_subtraction_drill(self):
        """Match four terms (1-4) must not acquire a 1-4 calculation in either grade band."""
        for band in ('3rd-4th','5th-6th'):
            page=matching_page()
            page['exercise']['stimuli'][0]['id']='source_1'
            page['html']=page['html'].replace('stimulus_source_text','stimulus_text_1')
            page['exercise']['questions'][0]['prompt']='Match the four numbered terms (1-4) with the four definitions (A-D).'
            page['exercise']['questions'][0]['calculation']={'expression':'1-4','answer':'-3'}
            before=deepcopy(page);result=fixtures.CompleteStudentTaskTests().ask(page,band)
            self.assertNotIn('calculation',result['exercise']['questions'][0])
            self.assertEqual(result['exercise']['questions'][0]['answer'],before['exercise']['questions'][0]['answer'])
            self.assertEqual(result['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertIn('stimulus_source_1',result['source_layout'])
        self.assertIsNone(label_matching_text('Match four terms (1-4) with definitions (A-D), then calculate 9-2.'))
        self.assertIsNone(label_matching_text('Match four terms (1-4) and count how many definitions remain.'))

    def test_hard_literal_intermediate_and_grade_limits_allow_coherent_task_revision(self):
        """An invalid expression cannot be repaired while its oversized printed problem is pinned."""
        cases=[('2275000*0.04','91000','Find four percent of the 2275000 dollar fund.',
                'Find four percent of one thousandth of the 2275000 dollar fund.','2275*0.04','91'),
               ('48.75*12400*8','4836000','Find the total cost of eight orders of 12400 items at 48.75 dollars each.',
                'Find the cost of an 80-item subset of one order at 48.75 dollars each.','48.75*80','3900'),
               ('48.75*12400','604500','Find the cost of 12400 items at 48.75 dollars each.',
                'Find the cost of an 80-item subset of the order at 48.75 dollars each.','48.75*80','3900')]
        for expression,answer,prompt,revised,operation,correct in cases:
            with self.subTest(expression=expression):
                page=text_card_page()
                page['exercise']['questions'][1].update(prompt=prompt,answer=answer,
                    calculation={'expression':expression,'answer':answer})
                correction={'exercise':{'questions':[{'id':'2','prompt':revised,'answer':correct,
                    'calculation':{'expression':operation,'answer':correct},'space_mm':0}]}}
                result,api=self.ask([page,correction])
                self.assertEqual(api.chat.completions.create.call_count,2)
                self.assertEqual(result['exercise']['questions'][1]['prompt'],revised)
                self.assertEqual(result['exercise']['questions'][1]['answer'],correct)
                self.assertEqual(result['exercise']['stimuli'],page['exercise']['stimuli'])
                self.assertEqual(result['images'],page['images'])
                self.assertGreaterEqual(result['exercise']['questions'][1]['space_mm'],35)
                repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
                self.assertNotIn('Correct ONLY exercise.questions[].calculation',repair)

    def test_body_role_repair_never_creates_a_null_or_duplicate_source_caption(self):
        """A repaired generic body slot reads the pinned source instead of registering a caption."""
        page=text_card_page();page['exercise']['stimuli'][0]['id']='civic_intro'
        page['html']=page['html'].replace('stimulus_text_body"></div>',
            'caption_source_text">Conflicting partial draft.</div>')
        correction={'html':page['html'].replace('Conflicting partial draft.',''),
                    'exercise':{'captions':[{'id':'source_text','text':None}]}}
        result,api=self.ask([page,correction])
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertEqual(result['exercise']['stimuli'],page['exercise']['stimuli'])
        self.assertFalse(any(c['id']=='source_text' for c in result['exercise'].get('captions',[])))
        self.assertIn('stimulus_civic_intro',result['source_layout'])
