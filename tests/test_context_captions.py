"""Canonical context labels and bounded local layout retry regressions."""
import json
from types import SimpleNamespace
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import validate_design, ask_json, layout_contract
from core.creative_layout import check_page
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class ContextCaptionTests(unittest.TestCase):
    """Keep expressive headings readable without bypassing canonical content binding."""

    def validate(self,page):
        """Use actual shared-content binding and print preflight for young readers."""
        return validate_design(page,15,quality=load_grade_config()['Pre-K-K'],
                               expected_title='Growing Together',require_coherent=True)

    def caption_page(self):
        """Add a canonical illustration caption to an original drawing task."""
        page=authored_page()
        page['exercise']['captions']=[dict(id='context',text='Plants growing together')]
        page['html']=page['html'].replace('<p data-content="directions">',
                         '<h4 data-content="caption_context"></h4><p data-content="directions">')
        return page

    def test_caption_prints_once_and_stays_out_of_answers(self):
        """A canonical contextual heading participates in normal readable layout checks."""
        raw=self.caption_page();original=deepcopy(raw)
        page=self.validate(raw)
        self.assertEqual(page['html'].count('Plants growing together'),1)
        self.assertNotIn('Plants growing together',page['answers'])
        self.assertEqual(raw,original)
        self.assertEqual(page['exercise']['captions'],original['exercise']['captions'])

    def test_exact_caption_copy_binds_without_another_provider_retry(self):
        """Ordinary HTML headings can recover when they match the declared caption exactly."""
        page=self.caption_page()
        page['html']=page['html'].replace('<h4 data-content="caption_context"></h4>',
                                         '<h4>Plants growing together</h4>')
        self.assertEqual(self.validate(page)['html'].count('Plants growing together'),1)

    def test_undeclared_caption_is_not_silently_adopted(self):
        """Unknown facts remain subject to content repair and educational proofreading."""
        page=authored_page();page['html']='<h4>Ancient Mesoamerican agricultural triad</h4>'+page['html']
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page)

    def test_caption_validation_rejects_malformed_and_missing_content(self):
        """Unknown IDs, excessive text and unused canonical facts cannot pass."""
        for captions in [[dict(id='context',text='x'*121)],
                         [dict(id='context',text='First'),dict(id='context',text='Second')],
                         [dict(id='Bad ID',text='Label')],
                         [dict(id='missing',text='Label')]]:
            with self.subTest(captions=captions),self.assertRaises(ValueError):
                page=self.caption_page();page['exercise']['captions']=captions
                self.validate(page)

    def test_duplicate_reflow_attempts_are_skipped_without_weakening_overflow(self):
        """Unchanged spacing gets three distinct modes, not six duplicate renders."""
        page=dict(html='<div style="height:300mm"></div>',images=[],quality_profile={'minimum_text_pt':14})
        original=deepcopy(page)
        renderer=Mock();renderer.return_value.render.return_value=Mock()
        with patch('core.creative_layout.HTML',renderer), \
             patch('core.creative_layout.check_document',side_effect=ValueError('Design overflow: expected 1 pages, got 2')):
            with self.assertRaisesRegex(ValueError,'could not fit'):
                check_page(page,15)
        self.assertEqual(renderer.call_count,3)
        self.assertEqual(page,original)

    def test_repairs_use_canonical_caption_and_exercise_schemas(self):
        """Both live diagnostics receive schema-consistent instructions without parallel drafts."""
        for diagnostic in ['Put ALL printed wording in exercise fields; unbound wording: Ancient Mesoamerican agricultural triad',
                           'Design overflow: expected 1 pages, got 2']:
            with self.subTest(diagnostic=diagnostic):
                api=Mock()
                api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({})),finish_reason='stop')])
                calls=[]
                def validate(raw):
                    """Emulate the diagnostic once and accept a repaired response."""
                    calls.append(raw)
                    if len(calls)==1: raise ValueError(diagnostic)
                    return raw
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    ask_json(layout_contract(15,14,coherent=True),validate,'Activity design 2')
                correction=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
                if 'unbound' in diagnostic:
                    self.assertIn('exercise.captions',correction)
                    self.assertIn('caption_context',correction)
                else:
                    self.assertIn('with html, images and exercise',correction)
                    self.assertIn('Preserve exercise fields',correction)
                    self.assertNotIn('including images, visuals, answers',correction)
