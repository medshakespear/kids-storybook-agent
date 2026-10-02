"""Empty illustration lists and redundant wrapper heights need focused, content-preserving repair."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from weasyprint import HTML
from core.creative_generator import ask_json, layout_contract, validate_design
from core.creative_layout import reflow_outer_panels, document_markup, fragment, check_document, data_only_fetcher
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page, exact_page, visual_examples


class EmptyManifestPanelTests(unittest.TestCase):
    """Restore useful art and fit natural-flow panels while preserving canonical work areas."""

    def validate(self,page):
        """Run actual upper-grade binding and measured print layout."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
                               expected_title='Upstander Studio',require_coherent=True)

    def test_authored_empty_list_uses_narrow_manifest_recovery(self):
        """The [] case behaves like null while retaining every original exercise field."""
        page=authored_page();page['images']=[]
        page['html']=page['html'].replace('<img data-asset="scene" style="width:175mm;height:75mm"/>','')
        corrected={'images':authored_page()['images'],'html':authored_page()['html']}
        api=Mock()
        def response(raw):
            """Supply mock JSON responses without live credentials."""
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        api.chat.completions.create.side_effect=[response(page),response(corrected)]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 2')
        self.assertEqual(result['exercise'],page['exercise'])
        self.assertEqual(result['images'],corrected['images'])
        self.assertIn('Recover ONLY missing illustration prompts',api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_empty_list_with_existing_slots_keeps_layout_during_prompt_repair(self):
        """Undeclared references caused by [] need prompts for those slots, not a new activity."""
        original=authored_page();original['images']=[]
        correction={'images':authored_page()['images'],'html':'<p>Unrelated replacement</p>'}
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')]) for raw in [original,correction]]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 2')
        self.assertEqual(result['source_layout'],original['html'])
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['images'],correction['images'])

    def test_exact_empty_list_remains_valid_without_recovery(self):
        """An existing computed graphic already supplies purposeful visual content."""
        page=exact_page(visual_examples()[3])
        self.assertEqual(self.validate(page)['images'],[])

    def test_oversized_outer_panel_fits_without_shrinking_response_or_art(self):
        """Only redundant outer height disappears; drawing space and all canonical task fields survive."""
        page=authored_page();page['html']='<div style="height:300mm;min-height:290mm;padding:4mm;background-color:#e8f4fa">'+page['html']+'</div>'
        original=deepcopy(page)
        result=self.validate(page)
        self.assertNotIn('height:300mm',result['html'])
        self.assertNotIn('min-height:290mm',result['html'])
        self.assertIn('height:45mm',result['html'])
        self.assertIn('height:75mm',result['html'])
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['images'],original['images'])
        doc=HTML(string=document_markup([fragment(result,True)],11),url_fetcher=data_only_fetcher).render()
        check_document(doc,1)
        self.assertEqual(page,original)

    def test_unidentified_work_space_and_blank_panels_keep_their_heights(self):
        """A dimensioned panel without an independent canonical response area must remain untouched."""
        markup='<div style="height:300mm"><img data-asset="scene" style="width:80mm;height:75mm"/><p>Draw here.</p></div>'
        self.assertEqual(reflow_outer_panels(markup),markup)
        markup='<div style="height:300mm"></div>'
        self.assertEqual(reflow_outer_panels(markup),markup)

    def test_already_fitting_panel_keeps_requested_layout(self):
        """Local normalization is a fallback, not a redesign of healthy pages."""
        page=authored_page();page['html']='<div style="min-height:230mm">'+page['html']+'</div>'
        result=self.validate(page)
        self.assertIn('min-height:230mm',result['html'])
