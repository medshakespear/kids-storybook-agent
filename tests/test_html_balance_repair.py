"""Recover omitted end tags and scope harder structure repairs without changing content."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.html_balance import balance_print_fragment,merge_structural_repair,reject_truncated_tag
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class HtmlBalanceRepairTests(unittest.TestCase):
    """Use native retry code and actual A4 measurement in both active bands."""

    def validate(self,page,band):
        """Compile original tasks, images and response dimensions after HTML normalization."""
        config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,items_per_page=2)
        return validate_design(page,config['student_font_pt'],quality=config,
                               expected_title='Garden Detectives',require_coherent=True)

    def test_trailing_closes_optional_cells_and_void_ends_repair_locally(self):
        """End-tag additions preserve words, source references and image attributes."""
        for markup,expected in (
            ('<div><p>Read &amp; compare.','<div><p>Read &amp; compare.</p></div>'),
            ('<table><tr><td>A<td>B</tr></table>','<table><tr><td>A</td><td>B</td></tr></table>'),
            ('<p>First<p>Second','<p>First</p><p>Second</p>'),
            ('<img data-asset="scene"/></img><br></br>','<img data-asset="scene"/><br>'),
            ('<p><div>Balanced literal wrappers.</div></p>','<p><div>Balanced literal wrappers.</div></p>'),
        ):
            with self.subTest(markup=markup):
                result=balance_print_fragment(markup)
                self.assertEqual(result,expected)
                self.assertEqual(balance_print_fragment(result),result)

    def test_missing_outer_closing_tag_keeps_the_printed_exercise(self):
        """A missing decorative wrapper close needs no model repair."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page();page['html']='<div>'+page['html'];original=deepcopy(page)
                result=self.validate(page,band)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('height:45mm',result['html'])
                self.assertEqual(page,original)

    def test_crossed_tags_get_html_only_repair_in_two_calls(self):
        """A syntax-only correction cannot replace questions, keys or artwork."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
                    '<div><p data-content="directions"></div></p>')
                original=deepcopy(page)
                corrected=page['html'].replace('<div><p data-content="directions"></div></p>',
                    '<div><p data-content="directions"></p></div>')
                api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
                    for raw in (page,{'html':corrected,'images':[],'exercise':{'questions':[]}})]
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(13,12,coherent=True),
                        lambda raw:self.validate(raw,band),'Activity design 2')
                self.assertEqual(api.chat.completions.create.call_count,2)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
                self.assertIn('closing-tag structure ONLY',message)
                schema=api.chat.completions.create.call_args.kwargs['response_format']['json_schema']['schema']
                self.assertEqual(set(schema['properties']),{'html'})
                self.assertEqual(page,original)

    def test_structural_repair_cannot_edit_attributes_or_words(self):
        """Correct end tags never authorize content removal or smaller response panels."""
        original={'html':'<div><strong>Read the record.</div></strong>',
                  'exercise':{'questions':[{'id':'1','space_mm':45}]},'images':[]}
        valid='<div><strong>Read the record.</strong></div>'
        self.assertEqual(merge_structural_repair(original,{'html':valid})['exercise'],original['exercise'])
        for altered in (valid.replace('record','answer'),valid.replace('<strong>','<strong style="height:5mm">')):
            with self.subTest(altered=altered),self.assertRaisesRegex(ValueError,'preserve all start tags'):
                merge_structural_repair(original,{'html':altered})
        for malformed in ('<div><strong>Text</div></strong>','<p>Text</section>'):
            with self.subTest(malformed=malformed),self.assertRaisesRegex(ValueError,'balanced'):
                balance_print_fragment(malformed)
        with self.assertRaisesRegex(ValueError,'incomplete tag'):
            reject_truncated_tag('<p>Read.</p><div')
