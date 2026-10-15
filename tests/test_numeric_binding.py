"""Bind standalone printed integers without losing values, styles, keys or response space."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page
from tests import test_statement_maze_and_artwork as fixtures


class NumericBindingTests(unittest.TestCase):
    """Check both active grades using native generation and real PDF print geometry."""

    def page(self):
        """Keep Gemini's bare colored number badges immediately beside its declared tasks."""
        page=authored_page()
        page['html']=page['html'].replace('width:175mm;height:75mm','width:92mm;height:92mm')
        page['html']=page['html'].replace('<div data-content="question_1"',
            '<span style="background-color:#F3D1A8;color:#4A245E;border-radius:3mm;padding:1mm">1</span><div data-content="question_1"')
        page['exercise']['questions'].append({'id':'2','prompt':'Explain how your shelter lets you water the plant.',
            'answer':'Accept a design detail allowing water to reach the plant.','space_mm':20})
        page['html']+='<strong style="color:#167E80">2</strong><div data-content="question_2"></div>'
        return page

    def validate(self,page,band):
        """Run the production shared-content compiler and WeasyPrint checks."""
        config=fixtures.StatementMazeAndArtworkTests().profile(band)
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title='Plant Shelter Studio',require_coherent=True)

    def test_bare_one_and_two_complete_after_one_provider_response_both_grades(self):
        """Number badges are retained canonical content rather than repeated wording repairs."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.page();original=deepcopy(page)
                config=fixtures.StatementMazeAndArtworkTests().profile(band)
                brief={'render_mode':'authored','mechanic':page['exercise']['mechanic']}
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:self.validate(raw,band),'Activity design 2',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual([c['text'] for c in result['exercise']['captions']],['1','2'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('#F3D1A8',result['html']);self.assertIn('#4A245E',result['html'])
                for height in (45,20): self.assertIn(f'height:{height}mm',result['html'])
                self.assertEqual(page,original)

    def test_adjacent_and_repeated_numbers_are_not_joined_or_deduplicated(self):
        """Distinct printed 1, 2 and 1 values remain three distinct owned text fields."""
        for band in ('3rd-4th','5th-6th'):
            page=self.page()
            page['html']=page['html'].replace('>1</span>','><span>1 </span><span> 2</span><span>1</span></span>',1)
            result=self.validate(page,band)
            self.assertEqual([c['text'] for c in result['exercise']['captions']],['1','2','1','2'])
            self.assertEqual(len({c['id'] for c in result['exercise']['captions']}),4)
            self.assertNotIn('>121<',result['html'])
            self.assertIn('>1</span> </span>',result['html'])
            self.assertIn('<span > <span',result['html'])

    def test_existing_numeric_caption_is_reused_only_if_it_has_no_other_reference(self):
        """A declared numeric value never makes a second independent printed value disappear."""
        for explicit in (False,True):
            page=self.page();page['exercise']['captions']=[{'id':'index','text':'1'}]
            if explicit: page['html']+='<span data-content="caption_index"></span>'
            result=self.validate(page,'3rd-4th')
            values=[c['text'] for c in result['exercise']['captions']]
            self.assertEqual(values.count('1'),2 if explicit else 1)
            self.assertEqual(result['source_layout'].count('data-content="caption_index"'),1)

    def test_repeated_validation_is_stable_and_existing_content_slots_are_untouched(self):
        """Saved source layouts recompile without accumulating new numeric labels."""
        page=self.page();page['exercise']['captions']=[{'id':'fixed','text':'42'}]
        page['html']+='<span data-content="caption_fixed">99</span>'
        first=self.validate(page,'3rd-4th')
        raw={key:deepcopy(first[key]) for key in ('images','exercise')};raw['html']=first['source_layout']
        second=self.validate(raw,'3rd-4th')
        self.assertEqual(first['exercise'],second['exercise'])
        self.assertEqual(first['html'],second['html'])
        self.assertNotIn('99',[c['text'] for c in second['exercise']['captions']])

    def test_numbers_do_not_bypass_math_checks_caption_limits_or_unbound_instructions(self):
        """Registering a numeric token does not authorize a task, expression or incorrect answer."""
        page=self.page();page['exercise']['questions'][0].update(prompt='Calculate 34+23.',answer='58',
            calculation={'expression':'34+23','answer':'58'})
        with self.assertRaisesRegex(ValueError,'declared math answer is incorrect'):
            self.validate(page,'3rd-4th')
        for literal in ('1+2','2 extra tasks','<span>1</span> + <span>2</span>'):
            page=self.page();page['html']+='<p>'+literal+'</p>'
            with self.assertRaisesRegex(ValueError,'Put ALL printed wording'):
                self.validate(page,'3rd-4th')
        page=self.page();page['html']=''.join(f'<span>{n}</span>' for n in range(25))+page['html']
        with self.assertRaisesRegex(ValueError,'Put ALL printed wording'):
            self.validate(page,'3rd-4th')
