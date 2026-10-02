"""Recover responsive image CSS locally while retaining printable geometry checks."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.creative_layout import clean_style
from core.image_dimensions import normalize_image_dimensions
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page, exact_page, visual_examples
from core.task_visuals import answer_text


class ImageDimensionTests(unittest.TestCase):
    """Check auto/missing heights, physical units, exact aspect ratios and unsafe styles."""

    def validate(self,page):
        """Run real canonical-content and measured first/second-grade print checks."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
            expected_title='Garden Detectives',require_coherent=True)

    def test_missing_and_auto_height_recover_without_changing_tasks_or_assets(self):
        """Each malformed image style receives sufficient physical artwork space."""
        for style in ['width:175mm', 'width:175mm;height:auto', 'width:100%;height:100%', '']:
            raw=authored_page();raw['html']=raw['html'].replace('width:175mm;height:75mm',style)
            original=deepcopy(raw)
            result=self.validate(raw)
            self.assertEqual(result['exercise'],original['exercise'])
            self.assertEqual(result['images'],original['images'])
            self.assertIn('height:',result['html'])
            self.assertEqual(result['exercise']['questions'][0]['space_mm'],45)
            self.assertEqual(raw,original)

    def test_units_and_capitalization_normalize_to_mm(self):
        """Centimetres, pixels, points and uppercase MM are interpreted consistently."""
        for height,expected in [('7.5cm','75mm'),('75MM','75mm'),('216pt','76.2mm'),('288px','76.2mm'),('3in','76.2mm')]:
            source=f'<img data-asset="scene" style="width:175mm;height:{height};border:1mm solid teal"/>'
            result=normalize_image_dimensions(source,{},10000,clean_style)
            self.assertIn('height:'+expected,result)
            self.assertIn('border:1mm solid teal',result)

    def test_exact_auto_height_preserves_intrinsic_aspect_and_computed_answer(self):
        """Use SVG geometry rather than an illustration-size guess for exact diagrams."""
        page=exact_page(visual_examples()[0])
        page['html']=page['html'].replace('height:150mm','height:auto')
        original=deepcopy(page)
        result=self.validate(page)
        self.assertEqual(result['exercise']['visual'],original['exercise']['visual'])
        self.assertTrue(answer_text(result))
        self.assertNotIn('height:auto',result['html'])

    def test_negative_zero_resources_and_duplicate_attributes_remain_rejected(self):
        """Dimension recovery must not hide content or weaken image/CSS validation."""
        for source in ['<img data-asset="scene" style="height:0mm"/>',
                       '<img data-asset="scene" style="height:-20mm"/>',
                       '<img data-asset="scene" style="width:0%"/>',
                       '<img data-asset="scene" style="background:url(https://example.com/x)"/>',
                       '<img data-asset="scene" style="height:auto" style="height:80mm"/>']:
            with self.subTest(source=source),self.assertRaises(ValueError):
                normalize_image_dimensions(source,{},10000,clean_style)

    def test_production_missing_height_needs_one_completion(self):
        """A valid activity does not spend a model repair call on responsive image geometry."""
        raw=authored_page();raw['html']=raw['html'].replace('height:75mm','height:auto')
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 3',
                response_schema=design_schema({'render_mode':'authored','mechanic':'design shelter'},load_grade_config()['1st-2nd']))
        self.assertEqual(api.chat.completions.create.call_count,1)
        self.assertEqual(result['images'],raw['images'])
        self.assertNotIn('height:auto',result['html'])


if __name__=='__main__':
    unittest.main()
