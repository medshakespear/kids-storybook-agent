"""Separate canonical text from protected sibling elements without losing content."""
from copy import deepcopy
import unittest

from core.content_binding import bind_formatted_canonical_text
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class CanonicalPrefixBindingTests(unittest.TestCase):
    """Exercise local recovery in both active grades and real print preflight."""

    def test_instruction_before_art_preserves_one_asset_and_answer(self):
        """A raw instruction and artwork may share a normal flow container."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page(); original=deepcopy(page)
                page['html']=page['html'].replace('<p data-content="directions"></p>','').replace(
                    '<img data-asset="scene"',
                    '<div><strong>Help a plant grow.</strong> Invent a shelter that lets sunlight reach it.'
                    '<img data-asset="scene"').replace('height:75mm"/>','height:75mm"/></div>')
                result=validate_design(page,12,quality=load_grade_config()[band],
                                       expected_title='Garden Detectives',require_coherent=True)
                self.assertEqual(result['exercise'],original['exercise'])
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(result['html'].count('data-asset="scene"'),1)
                self.assertEqual(result['html'].count(original['exercise']['directions']),1)
                self.assertEqual(result['html'].count('height:45mm'),1)

    def test_blank_workspaces_survive_prefix_binding(self):
        """Bordered, dimensioned and underline-only panels remain intact."""
        for panel in ('<span style="display:block;height:10mm;border:0.4mm solid #167E80"></span>',
                      '<span style="border-bottom:0.4mm solid #167E80">_____</span>'):
            for band in ('3rd-4th','5th-6th'):
                with self.subTest(panel=panel,band=band):
                    page=authored_page(); original=deepcopy(page['exercise'])
                    page['html']=page['html'].replace('<p data-content="directions"></p>',
                        '<div>'+page['exercise']['directions']+panel+'</div>')
                    result=validate_design(page,12,quality=load_grade_config()[band],
                                           expected_title='Garden Detectives',require_coherent=True)
                    self.assertEqual(result['exercise'],original)
                    self.assertIn('border',result['html'])
                    self.assertEqual(result['html'].count(original['directions']),1)
                    if 'height:10mm' in panel: self.assertIn('height:10mm',result['html'])
                    else: self.assertIn('_____',result['html'])

    def test_following_explicit_slot_is_retained(self):
        """A following question still prints once with its existing response space."""
        page=authored_page();original=deepcopy(page['exercise'])
        page['html']=page['html'].replace('<p data-content="directions"></p>','').replace(
            '<div data-content="question_1"',
            '<div>'+page['exercise']['directions']+'<div data-content="question_1"')+'</div>'
        result=validate_design(page,12,quality=load_grade_config()['3rd-4th'],
                               expected_title='Garden Detectives',require_coherent=True)
        self.assertEqual(result['exercise'],original)
        self.assertEqual(result['html'].count('height:45mm'),1)

    def test_extra_text_after_protected_panel_is_still_rejected(self):
        """Local separation cannot hide an independent instruction after a blank panel."""
        page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<div>'+page['exercise']['directions']+'<span style="height:5mm"></span>'
            '<span>Now count the stars.</span></div>')
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            validate_design(page,12,quality=load_grade_config()['3rd-4th'],
                            expected_title='Garden Detectives',require_coherent=True)

    def test_partial_ambiguous_and_question_prefixes_are_not_recovered(self):
        """Only a unique full non-question block can be safely split."""
        for blocks,text in (({'directions':'Read the story.'},'Read'),
                            ({'directions':'Read.','caption_a':'Read.'},'Read.'),
                            ({'question_1':'1. Read.'},'1. Read.')):
            with self.subTest(blocks=blocks):
                layout='<div>'+text+'<span style="height:5mm"></span></div>'
                self.assertNotIn('data-content',bind_formatted_canonical_text(layout,blocks))
