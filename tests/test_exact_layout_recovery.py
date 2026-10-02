"""Fit validated computed diagrams without lowering readability or deleting content."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.layout_recovery import single_exact_visual_recovery
from core.pipeline import load_grade_config
from core.task_visuals import answer_text
from tests.coherent_fixtures import authored_page,exact_page,visual_examples


class ExactLayoutRecoveryTests(unittest.TestCase):
    """Regress overflow followed by undersized pattern artwork in young grades."""

    def page(self):
        """Create a correct exact puzzle inside an excessively tall decorative panel."""
        page=exact_page(visual_examples()[0])
        page['html']=page['html'].replace('padding:2mm','height:240mm;padding:2mm')
        page['exercise']['questions']=[{'id':'2','prompt':'Draw your own friendly pumpkin.',
            'answer':'Accept an original drawing.','space_mm':25}]
        page['html']+='<div data-content="question_2"></div>'
        return page

    def validate(self,page):
        """Run canonical content, diagram text size and full physical page preflight."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_local_exact_recomposition_preserves_puzzle_key_and_response_space(self):
        """A tall decoration can be replaced while all student actions remain printable."""
        page=self.page();original=deepcopy(page)
        candidate=single_exact_visual_recovery(page,13,10000)
        self.assertIsNotNone(candidate)
        result=self.validate(candidate)
        baseline=exact_page(original['exercise']['visual'])
        baseline['visuals']=[original['exercise']['visual']]
        self.assertTrue(answer_text(result).startswith(answer_text(baseline)))
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertIn('height:25mm',result['html'])
        self.assertEqual(page,original)

    def test_production_retry_can_recover_exact_layout_after_bad_repair(self):
        """The shared retry path reaches the SVG fallback when illustration fallback declines."""
        page=self.page()
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 2')
        self.assertEqual(result['exercise']['questions'][0]['space_mm'],25)
        self.assertLessEqual(api.chat.completions.create.call_count,2)

    def test_untracked_working_panels_and_new_wording_still_decline(self):
        """Never make a page fit by dropping independent student content."""
        for markup in ['<div style="height:40mm"></div>','<p>Draw another five pumpkins.</p>']:
            page=self.page();page['html']+=markup
            with self.subTest(markup=markup):
                self.assertIsNone(single_exact_visual_recovery(page,13,10000))

    def test_invalid_diagram_is_not_replaced_with_a_different_puzzle(self):
        """An invalid motif must be corrected separately, preserving its learning goal."""
        page=self.page();page['exercise']['visual']['motif']=[{'shape':'corn','color':'yellow'}]*2
        self.assertIsNone(single_exact_visual_recovery(page,13,10000))

    def test_small_illustration_can_grow_beyond_old_scale_cap(self):
        """A printable 4800mm2 image grows to the required area without an AI repair."""
        page=authored_page()
        page['html']=page['html'].replace('width:175mm;height:75mm','width:80mm;height:60mm')
        original=deepcopy(page)
        result=self.validate(page)
        self.assertNotIn('width:80mm;height:60mm',result['html'])
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertIn('height:45mm',result['html'])
        self.assertEqual(result['images'],original['images'])


if __name__=='__main__':
    unittest.main()
