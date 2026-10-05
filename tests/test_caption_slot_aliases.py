"""Resolve declared caption aliases without inventing wording or replacing tasks."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.content_binding import canonical_content_slot
from core.creative_generator import ask_json, layout_contract, merge_layout_repair, validate_design
from core.page_contract import BoundLayout
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page, visual_examples


class CaptionSlotAliasTests(unittest.TestCase):
    """Regress c_arch versus caption_c_arch through production binding and layout recovery."""

    def page(self):
        """Build one exact puzzle with six short factual captions and bare caption IDs."""
        page = exact_page(visual_examples()[0])
        captions = [('c_arch','Arch observations'),('c_arch2','Curve observations'),
                    ('c_arch3','Shape observations'),('c_desc','Look at the colors'),
                    ('c_desc2','Look at the sizes'),('c_desc3','Look at the repeated motif')]
        page['exercise']['captions'] = [dict(id=cid,text=text) for cid,text in captions]
        page['html'] += ''.join(f'<p data-content="{cid}"></p>' for cid,_ in captions)
        return page

    def validate(self, page, band):
        """Compile the shared exercise and measure real A4 print geometry."""
        config = load_grade_config()[band]
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title='Pattern Observers',require_coherent=True)

    def test_declared_bare_caption_ids_print_once_for_both_active_grades(self):
        """Bare caption IDs resolve to retained text while unknown names remain unknown."""
        page = self.page(); original = deepcopy(page)
        for band in ['3rd-4th','5th-6th']:
            with self.subTest(band=band):
                result = self.validate(page,band)
                self.assertEqual(result['exercise'], original['exercise'])
                for caption in page['exercise']['captions']:
                    self.assertEqual(result['html'].count(caption['text']),1)
        self.assertEqual(page,original)
        self.assertEqual(canonical_content_slot('c_arch',{'caption_c_arch':'Arch'}),'caption_c_arch')
        self.assertEqual(canonical_content_slot('unknown',{'caption_c_arch':'Arch'}),'unknown')
        self.assertEqual(canonical_content_slot('title',{'title':'Title','caption_title':'Caption'}),'title')

    def test_alias_and_canonical_slot_share_duplicate_protection(self):
        """Resolving an alias cannot create a second independent copy of a caption."""
        parser = BoundLayout({'caption_c_arch':'Arch observations'})
        with self.assertRaisesRegex(ValueError,'already printed'):
            parser.feed('<p data-content="c_arch"></p><p data-content="caption_c_arch"></p>')

    def test_unused_caption_suggestions_are_ignored_but_referenced_new_wording_is_rejected(self):
        """Apply only layout and existing labels; never adopt unused invented content."""
        page = self.page()
        correction = dict(html=page['html'],exercise=dict(captions=[dict(id='new_label',text='Invented context')]))
        result = merge_layout_repair(page,correction)
        self.assertEqual(result['exercise'],page['exercise'])
        correction['html'] += '<p data-content="new_label"></p>'
        with self.assertRaisesRegex(ValueError,'complete wording already printed'):
            merge_layout_repair(page,correction)

    def test_equivalent_caption_rename_can_use_a_bare_id(self):
        """A layout retry reuses original canonical text without adding another caption."""
        page = self.page()
        correction = dict(html=page['html'].replace('data-content="c_arch"','data-content="arch_heading"'),
            exercise=dict(captions=[dict(id='arch_heading',text='Arch observations')]))
        merged = merge_layout_repair(page,correction)
        self.assertIn('data-content="caption_c_arch"',merged['html'])
        self.assertEqual(merged['exercise'],page['exercise'])
        self.validate(merged,'3rd-4th')
        correction['exercise']['captions'][0]['text'] = 'An invented historical claim'
        with self.assertRaises(ValueError):
            merge_layout_repair(page,correction)

    def test_whitespace_variation_does_not_replace_original_wording(self):
        """Case/spacing differences can compare equal while the original text stays pinned."""
        page = self.page()
        correction = dict(html=page['html'],exercise=dict(captions=[dict(id='c_arch',text='  ARCH   observations ')]))
        result = merge_layout_repair(page,correction)
        self.assertEqual(result['exercise'],page['exercise'])
        correction['exercise']['captions'][0]['text'] = 'Different facts'
        with self.assertRaisesRegex(ValueError,'cannot change existing caption wording'):
            merge_layout_repair(page,correction)

    def test_overflow_with_bare_captions_recovers_after_one_provider_response(self):
        """Caption spelling defects no longer prevent the measured exact-layout fallback."""
        page = self.page()
        page['html'] = page['html'].replace('padding:2mm','height:240mm;padding:2mm')
        for band in ['3rd-4th','5th-6th']:
            api = Mock()
            api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
            config = load_grade_config()[band]
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'test')), \
                 patch('core.creative_generator.time.sleep'):
                result = ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                    lambda raw:self.validate(raw,band),'Activity design 1',
                    response_schema=design_schema(dict(render_mode='exact',mechanic='pattern'),config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(result['exercise'],page['exercise'])


if __name__ == '__main__':
    unittest.main()
