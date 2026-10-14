"""Render the one declared computed puzzle without deleting other student content."""
from copy import deepcopy
import json
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.exact_visual_slots import normalize_exact_visual_slots
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from core.task_visuals import page_visuals
from tests.coherent_fixtures import exact_page, visual_examples


class ExactVisualSlotTests(unittest.TestCase):
    """Validate both grades with real SVG geometry and mocked provider responses."""

    def test_missing_and_duplicate_diagrams_need_one_response(self):
        """Recover the known puzzle while retaining its key, extra question and work panel."""
        for band in ('3rd-4th','5th-6th'):
            for mode in ('missing','duplicate'):
                with self.subTest(band=band,mode=mode):
                    config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                        stimulus_limit=8,context_caption_limit=24,items_per_page=2)
                    page=exact_page(visual_examples()[5]);original=deepcopy(page['exercise']['visual'])
                    page['exercise']['questions']=[{'id':'2','prompt':'Describe one useful way to organize a classroom display.',
                        'answer':'Accept a relevant organization idea.','space_mm':15}]
                    if mode=='missing':
                        page['html']=re.sub(r'<img\b[^>]*>', '',page['html'])
                    else:
                        page['html']+='<div><img data-visual="groups" style="width:45mm;height:45mm"/></div>'
                    page['html']+='<div data-content="question_2"></div><div style="height:10mm;border:0.4mm solid #167E80"></div>'
                    original_page=deepcopy(page);brief={'render_mode':'exact','mechanic':'sort'}
                    api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                    with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                         patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                         patch('core.creative_generator.time.sleep'):
                        result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                            lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                                expected_title='Museum Sorting',require_coherent=True,brief=brief),
                            'Activity design 2',response_schema=design_schema(brief,config))
                    self.assertEqual(api.chat.completions.create.call_count,1)
                    self.assertEqual(result['html'].count('data-visual="groups"'),1)
                    self.assertEqual(result['exercise']['visual'],original)
                    self.assertEqual(result['exercise']['questions'],original_page['exercise']['questions'])
                    self.assertIn('height:15mm',result['html'])
                    self.assertIn('height:10mm',result['html'])
                    self.assertEqual(page,original_page)

    def test_unknown_or_malformed_refs_are_not_silently_replaced(self):
        """Do not discard an unknown diagram, an asset image or invalid functional attributes."""
        page=exact_page(visual_examples()[5]);page['visuals']=[page['exercise']['visual']]
        visuals=page_visuals(page)
        for markup in ('<img data-visual="unknown" style="width:45mm;height:45mm"/>',
                       '<img data-visual="groups" data-asset="scene" style="width:45mm;height:45mm"/>',
                       '<img data-visual="groups" data-visual="groups" style="width:45mm;height:45mm"/>'):
            self.assertEqual(normalize_exact_visual_slots(markup,visuals,12,8000),markup)
        asset='<img data-asset="scene" style="width:45mm;height:45mm"/>'
        result=normalize_exact_visual_slots(asset,visuals,12,8000)
        self.assertIn('data-asset="scene"',result)
        self.assertIn('data-visual="groups"',result)
