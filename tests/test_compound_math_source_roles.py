"""Regress multi-result arithmetic repair and generic/lettered reading-body aliases."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.activity_stimuli import normalize_stimulus_ids
from core.creative_generator import ask_json,layout_contract,validate_design
from core.printed_arithmetic import compound_calculation
from core.response_schemas import design_schema
from tests import test_complete_student_tasks as fixtures
from tests.test_text_body_vocabulary import text_card_page
from tests.test_student_workbook import workbook_config


class CompoundMathSourceRoleTests(unittest.TestCase):
    """Use production compilation, print preflight and scoped retry with mocked completions."""

    def test_generic_text_slot_uses_the_retained_event_log_in_both_bands(self):
        """The bare word text is a body role, not a request for a newly invented source."""
        for band in ('3rd-4th','5th-6th'):
            for slot in ('stimulus_text','caption_source_text'):
                page=text_card_page();page['exercise']['stimuli'][0]['id']='event_log'
                page['html']=page['html'].replace('stimulus_text_body',slot)
                before=deepcopy(page);result=fixtures.CompleteStudentTaskTests().ask(page,band)
                self.assertEqual(result['exercise']['stimuli'],before['exercise']['stimuli'])
                self.assertEqual(result['images'],before['images'])
                self.assertNotIn('data-content="'+slot+'"',result['source_layout'])
                self.assertEqual(result['source_layout'].count('stimulus_event_log'),1)

    def test_text_a_accepts_only_a_complete_copy_with_its_retained_source_label(self):
        """A redundant Source A prefix is harmless; conflicting or partial evidence is not."""
        for label in ('Source A','Source A:','Source A.'):
            page={'html':'<p data-content="stimulus_text_a">'+label+' Complete A evidence.</p>',
                'exercise':{'render_mode':'authored','stimuli':[{'id':'source_a','label':'Source A','text':'Complete A evidence.'}]}}
            normalize_stimulus_ids(page,page['exercise'])
            self.assertIn('stimulus_source_a',page['html'])
        page={'html':'<p data-content="stimulus_text_a">Wrong A evidence.</p>',
            'exercise':{'render_mode':'authored','stimuli':[{'id':'source_a','label':'Source A','text':'Complete A evidence.'}]}}
        before=deepcopy(page);normalize_stimulus_ids(page,page['exercise']);self.assertEqual(page,before)

    def test_compound_detector_never_accepts_executable_or_verbal_expressions(self):
        """Recognize multiple arithmetic results without changing the arithmetic evaluator."""
        self.assertTrue(compound_calculation('(412-345) and 412*100/(345+412+288)'))
        for expression in ('412-345','412 and read the key','__import__(1) and 2+3','x+1 and 2+3'):
            self.assertFalse(compound_calculation(expression))

    def test_compound_math_repair_revises_the_question_not_just_its_answer(self):
        """Keep the retained source, art, other question and writing space through repair."""
        page=text_card_page();page['exercise']['stimuli'][0]['text']='Harvest records: Maple 345 kg; Oak 412 kg; Pine 288 kg.'
        page['exercise']['questions'][0].update(prompt='Which crop has the largest harvest?',answer='Oak, with 412 kg.')
        page['exercise']['questions'][1].update(prompt='Find the difference between Oak and Maple and the percentage of the total harvest represented by Oak.',
            answer='67 kg; about 39.43 percent.',calculation={'expression':'(412-345) and 412*100/(345+412+288)','answer':'67'})
        correction={'exercise':{'questions':[{'id':'2','prompt':'Find the combined mass of one Oak harvest plus two Maple harvests and two Pine harvests.',
            'answer':'1678 kg.','calculation':{'expression':'412+2*(345+288)','answer':'1678'},'space_mm':0}]}}
        api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(reply)),finish_reason='stop')]) for reply in (page,correction)]
        config=workbook_config('5th-6th',simple=True)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(12,12,coherent=True),lambda p:validate_design(p,12,quality=config,
                expected_title='Harvest Data',require_coherent=True),'Activity design 6',
                response_schema=design_schema({'render_mode':'authored','mechanic':'data_interpretation'},config))
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertEqual(result['exercise']['questions'][1]['prompt'],correction['exercise']['questions'][0]['prompt'])
        self.assertEqual(result['exercise']['questions'][1]['answer'],'1678 kg.')
        self.assertEqual(result['exercise']['stimuli'],page['exercise']['stimuli'])
        self.assertEqual(result['images'],page['images'])
        self.assertGreaterEqual(result['exercise']['questions'][1]['space_mm'],35)
        repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('ONE focused computed outcome',repair)
        self.assertNotIn('Correct ONLY exercise.questions[].calculation',repair)
