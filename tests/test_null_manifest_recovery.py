"""Recover null image manifests without replacing canonical exercises or inventing placeholder art."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design, merge_manifest_repair
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page, exact_page, visual_examples


class NullManifestRecoveryTests(unittest.TestCase):
    """Existing exact graphics and genuinely missing authored prompts need different recovery paths."""

    def validate(self,page):
        """Run shared exercise compilation and real younger-grade print checks."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Creative Garden',require_coherent=True)

    def ask(self,responses):
        """Run mocked provider responses through the production recovery loop."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in responses]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 1')
        return result,api

    def test_exact_graphic_with_null_or_missing_images_normalizes_locally(self):
        """A complete computed graphic needs no fictional raster prompts or provider retry."""
        for missing in [False,True]:
            page=exact_page(visual_examples()[3])
            if missing: page.pop('images')
            else: page['images']=None
            original=deepcopy(page)
            result=self.validate(page)
            self.assertEqual(result['images'],[])
            self.assertEqual(result['visuals'][0]['rows'],original['exercise']['visual']['rows'])
            self.assertEqual(page,original)

    def test_authored_page_requests_only_missing_prompts_and_preserves_layout(self):
        """The recovery response cannot change existing canonical tasks or image slots."""
        original=authored_page();original['images']=None
        correction={'images':authored_page()['images'],'html':'<p>Wrong task</p>',
                    'exercise':{'questions':[]}}
        result,api=self.ask([original,correction])
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['source_layout'],original['html'])
        self.assertEqual(result['images'],correction['images'])
        message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('Recover ONLY missing illustration prompts',message)
        self.assertIn('Return ONLY images',message)
        self.assertIn('["scene"]',message)
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_repeated_null_response_keeps_original_recovery_scope(self):
        """A second null gets the same narrow recovery instead of regenerating the activity."""
        original=authored_page();original['images']=None
        corrected={'images':authored_page()['images']}
        result,api=self.ask([original,{'images':None},corrected])
        self.assertEqual(result['source_layout'],original['html'])
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(api.chat.completions.create.call_count,3)

    def test_no_existing_image_slots_can_receive_real_prompts_and_added_art(self):
        """An authored text layout gains visible AI art while keeping all original task fields."""
        original=authored_page();original['images']=None
        original['html']=original['html'].replace('<img data-asset="scene" style="width:175mm;height:75mm"/>','')
        correction={'images':authored_page()['images'],'html':authored_page()['html']}
        result,api=self.ask([original,correction])
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertIn('data-asset="scene"',result['html'])
        self.assertIn('height:45mm',result['html'])
        self.assertIn('Also return html',api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])

    def test_null_manifest_with_existing_art_slot_is_not_cleared_on_exact_page(self):
        """Normalize null to empty only when no purposeful raster image is referenced."""
        page=exact_page(visual_examples()[3]);page['images']=None
        page['html']+='<img data-asset="scene" style="width:20mm;height:20mm"/>'
        with self.assertRaisesRegex(ValueError,'Illustration manifest images'):
            self.validate(page)

    def test_recovery_cannot_make_up_missing_prompts_or_accept_empty_art(self):
        """No placeholder image prompts or blank visual manifests are synthesized locally."""
        page=authored_page();page['images']=None
        for images in [None,[],[{'id':'scene'}],[{'id':'scene','prompt':''}]]:
            with self.subTest(images=images),self.assertRaisesRegex(ValueError,'manifest recovery'):
                merge_manifest_repair(page,{'images':images})
