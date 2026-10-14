"""Bind source headings and enlarge retained art without discarding independent workspace."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.content_binding import source_heading
from core.creative_generator import ask_json, layout_contract, validate_design
from core.layout_recovery import retained_artwork_growth
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class SourceHeadingArtGrowthTests(unittest.TestCase):
    """Check complete labels and retained measured layouts for both grades."""

    def test_placard_heading_and_small_art_with_extra_workspace_need_one_response(self):
        """Growing artwork cannot drop the source, key or an independent blank panel."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,items_per_page=2)
                page=authored_page(mechanic='interpret_source')
                page['exercise']['stimuli']=[{'id':'placard','text':'Fictional museum placard: The plant shelter admits sunlight and allows watering.'}]
                page['exercise']['questions'][0]['space_mm']=25
                page['html']=page['html'].replace('<p data-content="directions"></p>',
                    '<p data-content="directions"></p><h3>Museum Placard</h3><p data-content="stimulus_placard"></p>')
                page['html']=page['html'].replace('width:175mm;height:75mm','width:74mm;height:75mm')
                page['html']+='<div style="height:15mm;border:0.4mm solid #167E80"></div>'
                original=deepcopy(page);api=Mock()
                api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                brief={'render_mode':'authored','mechanic':'interpret_source'}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title='Museum Evidence',require_coherent=True),
                        'Activity design 2',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(result['html'].count('Museum Placard'),1)
                self.assertIn('height:15mm',result['html'])
                self.assertIn('height:25mm',result['html'])
                self.assertNotIn('width:74mm;height:75mm',result['html'])

    def test_complete_source_labels_only(self):
        """A label cannot authorize appended directions, claims or an answer."""
        for text in ('Museum Placard','Exhibit Label:','Student Notes','Source Excerpt'):
            self.assertTrue(source_heading(text))
        for text in ('Museum Placard: Write your answer.','Museum Placard: 74 cm','Source Card: Count three items.'):
            self.assertFalse(source_heading(text))
        page=authored_page();page['html']+='<p>Museum Placard: Explain the answer.</p>'
        self.assertIsNone(retained_artwork_growth(page,12,8000))
