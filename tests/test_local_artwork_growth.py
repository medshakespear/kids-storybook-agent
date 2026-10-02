"""Modest artwork resizing and layout repair preserve complete canonical exercises."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from weasyprint import HTML
from core.creative_generator import ask_json, layout_contract, validate_design
from core.creative_layout import check_document, check_visual_quality, document_markup, fragment, data_only_fetcher
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class LocalArtworkGrowthTests(unittest.TestCase):
    """Recover the reported 4125-to-6000mm2 shortfall only when a readable page still fits."""

    def validate(self,page):
        """Run upper-grade content and measured print checks."""
        cfg=load_grade_config()['5th-6th']
        return validate_design(page,11,quality=cfg,expected_title='Design Lab',require_coherent=True)

    def test_reported_area_shortfall_grows_locally_and_survives_final_markup(self):
        """One image enlargement preserves canonical wording, answers and response space."""
        page=authored_page();page['html']=page['html'].replace('width:175mm;height:75mm','width:75mm;height:55mm')
        original=deepcopy(page)
        result=self.validate(page)
        self.assertNotIn('width:75mm;height:55mm',result['html'])
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['images'],original['images'])
        self.assertIn('height:45mm',result['html'])
        doc=HTML(string=document_markup([fragment(result,True)],11),url_fetcher=data_only_fetcher).render()
        check_document(doc,1);check_visual_quality(doc,result['quality_profile'])
        self.assertEqual(page,original)

    def test_resize_that_overflows_does_not_shrink_response_space(self):
        """If enlargement cannot fit, the original page remains a repairable quality failure."""
        page=authored_page();page['html']=page['html'].replace('width:175mm;height:75mm','width:75mm;height:55mm')
        page['html']='<div style="height:145mm"></div>'+page['html']
        original=deepcopy(page)
        with self.assertRaises(ValueError): self.validate(page)
        self.assertEqual(page,original)

    def test_tiny_thumbnail_is_not_promoted_to_a_main_illustration(self):
        """Large required scaling still asks for a genuine art-led composition."""
        page=authored_page();page['html']=page['html'].replace('width:175mm;height:75mm','width:30mm;height:30mm')
        with self.assertRaisesRegex(ValueError,'Visuals are too small'): self.validate(page)

    def test_layout_only_response_cannot_delete_art_or_change_questions(self):
        """An overflow repair contributes HTML only, even if the provider returns drifting fields."""
        original=authored_page()
        original['html']='<div style="height:300mm"></div>'+original['html']
        correction=authored_page();correction['images']=None
        correction['exercise']['questions'][0].update(prompt='An unrelated question',answer='Wrong criterion',space_mm=0)
        api=Mock()
        def response(page):
            """Build a complete mock JSON chat response without provider credentials."""
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        api.chat.completions.create.side_effect=[response(original),response(correction)]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 1')
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['images'],original['images'])
        self.assertIn('Draw your shelter.',result['html'])
        self.assertIn('height:45mm',result['html'])
        message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('ONLY the corrected HTML',message)

    def test_fourth_distinct_content_repair_is_bounded_and_available(self):
        """Three defects need not end a unit before its fourth corrected response can be checked."""
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{}'),finish_reason='stop')])
        seen=[]
        def validate(raw):
            """Emulate three distinct validly serialized defects, then a successful correction."""
            seen.append(raw)
            if len(seen)<=3: raise ValueError(f'Content defect {len(seen)}')
            return raw
        with patch.dict('os.environ',{'DESIGN_VALIDATION_ATTEMPTS':'4'}), \
             patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            self.assertEqual(ask_json('Return JSON',validate,'Activity design 1'),{})
        self.assertEqual(api.chat.completions.create.call_count,4)
