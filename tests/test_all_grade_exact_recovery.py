"""Run exact-puzzle content and sizing recovery through every supported grade band."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from core.creative_generator import ask_json, layout_contract, validate_design
from core.layout_recovery import single_exact_visual_recovery
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page, visual_examples


class AllGradeExactRecoveryTests(unittest.TestCase):
    """Use real SVG labels and WeasyPrint geometry with each grade's unchanged limits."""
    def setUp(self):
        """Load all four grade profiles once for the parameterized checks."""
        self.configs=load_grade_config()

    def validate(self,page,config):
        """Apply canonical bindings, font floors, artwork floors and A4 geometry."""
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title='Puzzle Studio',require_coherent=True)

    def small_page(self,visual):
        """Create too-small exact art plus a separate action sharing the visual's label."""
        page=exact_page(deepcopy(visual))
        page['html']=page['html'].replace('width:175mm;height:150mm','width:70mm;height:40mm')
        page['exercise']['questions']=[{'id':'1','prompt':'How could you invent a new picture for this puzzle?',
            'answer':'Accept an original relevant picture idea.','space_mm':20}]
        page['html']+='<div data-content="question_1"></div>'
        return page

    def test_all_tools_recover_across_all_grade_profiles(self):
        """Each supported puzzle can grow from tiny labels without dropping the extension."""
        for band,config in self.configs.items():
            for visual in visual_examples():
                with self.subTest(band=band,mechanic=visual['kind']):
                    page=self.small_page(visual);original=deepcopy(page)
                    recovered=single_exact_visual_recovery(page,config['minimum_text_pt'],config['visual_area_mm2'])
                    self.assertIsNotNone(recovered)
                    result=self.validate(recovered,config)
                    question=result['exercise']['questions'][0]
                    self.assertEqual(question['id'],'2')
                    self.assertEqual(question['space_mm'],20)
                    self.assertEqual(question['prompt'],original['exercise']['questions'][0]['prompt'])
                    self.assertEqual(result['exercise']['visual'],original['exercise']['visual'])
                    self.assertEqual(page,original)

    def test_production_routes_small_label_error_to_local_recovery_for_all_grades(self):
        """One model response per grade suffices for a valid tiny-label sizing defect."""
        for band,config in self.configs.items():
            with self.subTest(band=band):
                page=self.small_page(visual_examples()[5])
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda draft:self.validate(draft,config),'Activity design 4',
                        response_schema=design_schema({'render_mode':'exact','mechanic':'sort'},config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(result['exercise']['questions'][0]['id'],'2')

    def test_direct_validation_still_rejects_unreadable_labels(self):
        """Sizing deferral is only a recovery preparation step, never a release bypass."""
        for band,config in self.configs.items():
            with self.subTest(band=band),self.assertRaisesRegex(ValueError,'Exact visual labels would be too small'):
                self.validate(self.small_page(visual_examples()[5]),config)

    def test_semantic_and_structural_defects_are_not_bypassed(self):
        """Invalid puzzle data and untracked workspaces still prevent lossless recomposition."""
        page=self.small_page(visual_examples()[5]);page['exercise']['visual']['items']=[]
        self.assertIsNone(single_exact_visual_recovery(page,13,10000))
        page=self.small_page(visual_examples()[5]);page['html']+='<div style="height:30mm"></div>'
        self.assertIsNone(single_exact_visual_recovery(page,13,10000))
