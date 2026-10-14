"""Recover nonprinting null artifacts without weakening text or visual contracts."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.pipeline import load_grade_config
from core.print_tags import normalize_print_markup
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class NullPrintMetadataTests(unittest.TestCase):
    """Check both grades with real PDF geometry and mocked provider responses."""

    def test_null_metadata_and_tiny_art_recover_from_one_response(self):
        """Blank fields survive and the same illustration meets the measured art floor."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,items_per_page=2)
                page=authored_page();original=deepcopy(page)
                page['html']=('<p>Name: _____________________ \x00 \x00</p><p>\x00 \x00</p>'+
                    page['html'].replace('width:175mm;height:75mm','width:28.5mm;height:28.7mm'))
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                brief={'render_mode':'authored','mechanic':page['exercise']['mechanic']}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title='Garden Design',require_coherent=True),
                        'Activity design 2',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertNotIn('\x00',result['html'])
                self.assertEqual(result['html'].count('Name:'),1)
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertIn('height:45mm',result['html'])
                self.assertNotIn('width:28.5mm',result['html'])

    def test_only_null_text_artifacts_change(self):
        """Keep words, entities, attributes and workspace; never join split words."""
        markup='<p>Plant\x00care &amp; growth.</p><div style="height:25mm"></div>'
        normalized=normalize_print_markup(markup)
        self.assertIn('Plant care &amp; growth.',normalized)
        self.assertIn('height:25mm',normalized)
        self.assertEqual(normalize_print_markup(normalized),normalized)
        self.assertIn('data-content="bad\x00slot"',normalize_print_markup('<p data-content="bad\x00slot"></p>'))

    def test_nulls_do_not_authorize_extra_instructions(self):
        """Additional wording still fails canonical binding after removing corrupt bytes."""
        config=dict(load_grade_config()['3rd-4th'],purposeful_activity_layout=False,stimulus_limit=8)
        page=authored_page();page['html']='<p>\x00 Now write an unrelated answer. \x00</p>'+page['html']
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            validate_design(page,config['student_font_pt'],quality=config,
                expected_title='Garden Design',require_coherent=True)
