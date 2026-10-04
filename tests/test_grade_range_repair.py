"""Preserve worksheet layout and other tasks when arithmetic exceeds the grade limit."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from core.creative_generator import ask_json, layout_contract, validate_design, merge_range_repair
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class GradeRangeRepairTests(unittest.TestCase):
    """Test scoped range correction followed by real artwork/layout recovery."""
    def setUp(self):
        """Use a valid upper-grade computation exceeding the configured result maximum."""
        self.config=load_grade_config()['5th-6th']
        self.page=authored_page()
        self.page['exercise']['questions'][0].update(prompt='What is 500 * 30?',answer='15000',
            calculation={'expression':'500*30','answer':15000},space_mm=20)
        self.correction={'exercise':{'questions':[{'id':'1','prompt':'What is 500 * 10?',
            'answer':'5000','calculation':{'expression':'500*10','answer':5000},'space_mm':0}]}}

    def validate(self,page):
        """Verify canonical arithmetic and actual printable geometry."""
        return validate_design(page,11,quality=self.config,expected_title='Garden Challenge',require_coherent=True)

    def test_range_diagnostic_identifies_question_result_and_limit(self):
        """The repair sees an actionable error rather than an unspecified page defect."""
        with self.assertRaisesRegex(ValueError,'Question 1: Arithmetic result.*0 to 10000, got 15000'):
            self.validate(self.page)

    def test_merge_preserves_layout_art_and_original_response_space(self):
        """Only the numerical task changes even if the model tries to change the whole page."""
        original=deepcopy(self.page)
        correction=deepcopy(self.correction);correction.update(html='',images=[])
        result=merge_range_repair(self.page,correction,'1')
        self.assertEqual(result['html'],original['html'])
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(result['exercise']['questions'][0]['space_mm'],20)
        self.assertEqual(self.page,original)
        self.validate(result)

    def test_production_repairs_range_then_recovers_undersized_art(self):
        """The reported math-to-art loop uses two responses and retains its corrected task."""
        raw=deepcopy(self.page)
        raw['html']=raw['html'].replace('width:175mm;height:75mm','width:80mm;height:48mm')
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(reply)),finish_reason='stop')])
            for reply in [raw,self.correction]]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 3',
                response_schema=design_schema({'render_mode':'authored','mechanic':'design shelter'},self.config))
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertEqual(result['images'],raw['images'])
        self.assertEqual(result['exercise']['questions'][0]['space_mm'],20)
        self.assertEqual(result['exercise']['questions'][0]['answer'],'5000')
        self.assertEqual(result['quality_profile']['visual_area_mm2'],6000)
        schema=api.chat.completions.create.call_args_list[1].kwargs['response_format']['json_schema']['schema']
        self.assertEqual(set(schema['properties']),{'exercise'})

    def test_incorrect_or_still_oversized_repair_is_rejected(self):
        """Scoping cannot bypass the normal arithmetic correctness and range checks."""
        for prompt,expression,value in [('What is 500 * 30?','500*30',15000),
                                         ('What is 500 * 10?','500*10',4000)]:
            correction=deepcopy(self.correction)
            correction['exercise']['questions'][0].update(prompt=prompt,answer=str(value),
                calculation={'expression':expression,'answer':value})
            with self.assertRaises(ValueError):
                self.validate(merge_range_repair(self.page,correction,'1'))
