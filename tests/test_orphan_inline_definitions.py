"""Recover redundant inline closes and complete formatted definitions without task drift."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.authored_wording import merge_authored_wording
from core.content_binding import definition_label
from core.creative_generator import ask_json,layout_contract,validate_design
from core.html_balance import balance_print_fragment,structural_signature
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class OrphanInlineDefinitionTests(unittest.TestCase):
    """Use actual A4 checks for both grades and strict content-preservation negatives."""

    def config(self,band):
        """Use the real mixed-mode print profile."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
            stimulus_limit=8,context_caption_limit=24,items_per_page=2)

    def test_orphan_span_and_complete_definition_need_no_second_response(self):
        """Nothing about the exercises, assets or independent writing panels is removed."""
        definition='Can be proven true or false with evidence.'
        for band in ('3rd-4th','5th-6th'):
            for known in (False,True):
                with self.subTest(band=band,known=known):
                    page=authored_page();page['exercise']['captions']=([{'id':'fact_definition','text':definition}] if known else [])
                    page['html']=page['html'].replace('<p data-content="directions"></p>',
                        '<div><div><div><div><p data-content="directions"></span></p></div></div></div></div>')
                    page['html']+='<div><p><span style="display:inline-block;width:90mm">'+definition+'</span></p>'
                    page['html']+='<div style="height:10mm;border:0.4mm solid #167E80"></div></div>'
                    original=deepcopy(page);config=self.config(band)
                    api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                    brief={'render_mode':'authored','mechanic':page['exercise']['mechanic']}
                    with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                         patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                         patch('core.creative_generator.time.sleep'):
                        result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                            lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                                expected_title='Garden Detectives',require_coherent=True),
                            'Activity design 8',response_schema=design_schema(brief,config))
                    self.assertEqual(api.chat.completions.create.call_count,1)
                    self.assertEqual(result['html'].count(definition),1)
                    self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                    self.assertEqual(result['images'],original['images'])
                    self.assertIn('height:45mm',result['html'])
                    self.assertIn('height:10mm',result['html'])
                    if known: self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
                    self.assertEqual(page,original)

    def test_dimensioned_complete_text_can_bind_verbatim_in_scoped_repair(self):
        """Text-only formatting must not make a retained full sentence disappear from evidence."""
        text='The fictional display includes two models with clear measurement records.'
        page=authored_page();page['html']+='<p><span style="width:90mm;display:inline-block">'+text+'</span></p>'
        correction=deepcopy(page)
        correction['exercise']['captions']=[{'id':'record_context','text':text}]
        correction['html']=correction['html'].replace('<p><span style="width:90mm;display:inline-block">'+text+'</span></p>',
            '<p data-content="caption_record_context"></p>')
        result=merge_authored_wording(page,correction)
        self.assertIn({'id':'record_context','text':text},result['exercise']['captions'])
        correction['exercise']['captions'][0]['text']='The fictional display includes different records.'
        with self.assertRaisesRegex(ValueError,'complete wording already printed'):
            merge_authored_wording(page,correction)

    def test_orphan_inline_closes_preserve_signature_but_crossed_structures_still_fail(self):
        """No invented openings, missing media or structural parent changes are accepted."""
        original='<div><p>Read &amp; compare.</span></p><img data-asset="scene"/><div style="height:25mm"></div></div>'
        result=balance_print_fragment(original)
        self.assertEqual(structural_signature(result),structural_signature(original))
        self.assertNotIn('</span>',result)
        for bad in ('<div><strong>Text</div></strong>','<p>Text</section>'):
            with self.assertRaisesRegex(ValueError,'balanced'): balance_print_fragment(bad)
        for bad in ('Can be proven true. Write an extra answer.','Can be proven with 3 measurements.',
                    'Can be proven?','The answer is true.'):
            self.assertFalse(definition_label(bad))
