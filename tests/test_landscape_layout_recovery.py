"""Fit artwork and full-width writing areas together without reducing either contract."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.layout_recovery import layout_recovery_candidates
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class LandscapeRecoveryTests(unittest.TestCase):
    """Regress the overflow -> repeatedly undersized artwork repair loop."""

    def page(self):
        """Create a middle-grade reading/design sheet with two meaningful drawing tasks."""
        page=authored_page()
        page['exercise']['directions']='Read the garden observations and design a solution.'
        page['exercise']['passage']=(
            'Students planted beans in two trays. They kept the soil and water the same. '
            'One tray stood beside a sunny window while the other stood in a shaded corner. '
            'After a week, the class measured the plants and compared their leaves. '
            'They recorded their observations before changing anything.')
        page['exercise']['questions']=[
            dict(id='1',prompt='Draw a shelter that allows sunlight and watering.',
                 answer='Accept a shelter providing sunlight and watering access.',space_mm=45),
            dict(id='2',prompt='Draw how you would change the garden to help plants grow.',
                 answer='Accept a useful change with a clear benefit for plant growth.',space_mm=45)]
        page['html']=page['html'].replace('<img data-asset=', '<p data-content="passage"></p><img data-asset=')
        page['html']+='<div data-content="question_2"></div>'
        return page

    def validate(self,page):
        """Measure real WeasyPrint bounds, readable typography and meaningful visual area."""
        return validate_design(page,13,quality=load_grade_config()['3rd-4th'],
            expected_title='Garden Investigators',require_coherent=True)

    def test_wider_composition_fits_when_square_recovery_does_not(self):
        """Keep the same reading, questions, artwork and both 45mm response areas."""
        page=self.page();original=deepcopy(page)
        candidates=list(layout_recovery_candidates(page,12,8000))
        self.assertEqual(len(candidates),3)
        recovered = self.validate(candidates[0])
        self.assertEqual(recovered['exercise'], original['exercise'])
        self.assertEqual(recovered['html'].count('height:45mm'), 2)
        for candidate in candidates[1:]:
            result=self.validate(candidate)
            self.assertEqual(result['exercise'],original['exercise'])
            self.assertEqual(result['images'],original['images'])
            self.assertEqual(result['html'].count('height:45mm'),2)
            self.assertEqual(result['quality_profile']['visual_area_mm2'],8000)
            self.assertIn('Students planted beans',result['html'])
        self.assertEqual(page,original)

    def test_production_tries_alternative_after_first_recovery_fails(self):
        """A correct dense worksheet succeeds after one model response, not repeated tiny art rewrites."""
        page=list(layout_recovery_candidates(self.page(),12,8000))[0]
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(13,12,coherent=True),self.validate,'Activity design 2',
                response_schema=design_schema({'render_mode':'authored','mechanic':'design shelter'},load_grade_config()['3rd-4th']))
        self.assertEqual(api.chat.completions.create.call_count,1)
        self.assertEqual(result['exercise'],page['exercise'])
        self.assertEqual(result['images'],page['images'])
        self.assertEqual(result['html'].count('height:45mm'), 2)
        self.assertEqual(result['quality_profile']['visual_area_mm2'], 8000)

    def test_untracked_space_and_unbound_tasks_are_not_discarded_for_fit(self):
        """Candidate generation must not erase independently authored actions or work panels."""
        for extra in ['<div style="height:40mm"></div>','<p>Write another explanation.</p>']:
            page=self.page();page['html']+=extra
            with self.subTest(extra=extra):
                self.assertEqual(list(layout_recovery_candidates(page,12,8000)),[])


if __name__=='__main__':
    unittest.main()
