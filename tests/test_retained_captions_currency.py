"""Regress omitted retained context, generic source labels and exact monetary metadata."""
from copy import deepcopy
from fractions import Fraction
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design,merge_layout_repair
from core.response_schemas import design_schema
from core.math_result_recovery import repair_calculation_metadata
from core.reading_bindings import declare_reading_headings
from tests import test_complete_student_tasks as fixtures
from tests.test_text_body_vocabulary import text_card_page
from tests.test_reading_bindings import plain_text
from tests.test_student_workbook import workbook_config


class RetainedCaptionsCurrencyTests(unittest.TestCase):
    """Use measured page validation and preserve ambiguous wording for semantic review."""

    def test_omitted_pottery_context_is_printed_once_without_new_content(self):
        """A retained contextual statement is recoverable without inventing a diagram label."""
        for band in ('3rd-4th','5th-6th'):
            page=text_card_page()
            page['exercise']['captions']=[{'id':'pottery_tradition','text':'Pottery traditions are shared through family teaching.'}]
            # Restore the context before the actual source/art region.
            page['html']=page['html'].replace('<div data-content="stimulus_text_body">',
                '<table style="width:180mm"><tr><td><div data-content="stimulus_text_body">').replace('</div><img',
                '</div></td></tr></table><img',1)
            before=deepcopy(page);result=fixtures.CompleteStudentTaskTests().ask(page,band)
            self.assertEqual(result['exercise']['captions'],before['exercise']['captions'])
            self.assertEqual(plain_text(result['html']).count(before['exercise']['captions'][0]['text']),1)
            self.assertEqual(result['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(result['images'],before['images'])

    def test_source_label_is_neutral_or_uses_only_its_immediately_adjacent_source(self):
        """Multiple source records do not require choosing an arbitrary subject-specific heading."""
        exercise={'render_mode':'authored','stimuli':[{'id':'card_a','text':'A retained source.'},
            {'id':'cedar_source','label':'Cedar Reading','text':'A cedar source.'}]}
        declare_reading_headings('<h3 data-content="caption_source_label"></h3><p data-content="stimulus_cedar_source"></p>',
            exercise,{'student_workbook':True})
        self.assertEqual(exercise['captions'],[{'id':'source_label','text':'Cedar Reading'}])
        exercise.pop('captions')
        declare_reading_headings('<h3 data-content="caption_source_label"></h3><div>Other content</div>',
            exercise,{'student_workbook':True})
        self.assertEqual(exercise['captions'],[{'id':'source_label','text':'Source'}])

    def test_known_labeled_source_wrapper_keeps_the_complete_body_and_graphic(self):
        """A known source with a label may wrap a redundant body beside an illustration."""
        for band in ('3rd-4th','5th-6th'):
            page=text_card_page(mixed=True)
            page['html']=page['html'].replace('stimulus_text_body','stimulus_text_card')
            before=deepcopy(page);result=fixtures.CompleteStudentTaskTests().ask(page,band)
            self.assertEqual(plain_text(result['html']).count(before['exercise']['stimuli'][0]['text']),1)
            self.assertEqual(result['html'].count('data-asset="weather"'),1)
            self.assertEqual(result['images'],before['images'])

    def test_currency_metadata_is_exact_without_rewriting_ambiguous_prose(self):
        """The reported expression equals 36675; independently review any remaining prose."""
        page={'exercise':{'questions':[{'id':'2','prompt':'Find the total revenue from both crops.',
            'answer':'Crop A earns 18125 and crop B earns 18550; total revenue should be checked.',
            'space_mm':50,'calculation':{'expression':'1450*12.50+2120*8.75','answer':'73325/2'}}]}}
        before=deepcopy(page);result=repair_calculation_metadata(page,'2')
        q=result['exercise']['questions'][0]
        self.assertEqual(Fraction(q['calculation']['answer']),36675)
        for key in ('prompt','answer','space_mm'):self.assertEqual(q[key],before['exercise']['questions'][0][key])
        self.assertEqual(page,before)
        self.assertIsNone(repair_calculation_metadata(result,'2'))

    def test_exercise_repair_computes_metadata_then_scopes_the_ambiguous_key(self):
        """Do arithmetic locally before asking the model to correct only the prose solution."""
        raw=text_card_page();raw['exercise']['stimuli'][0]['text']='Crop A: 1450 units at $12.50 each. Crop B: 2120 units at $8.75 each.'
        raw['exercise']['questions'][0].update(prompt='Which crop has more units?',answer='Crop B.')
        raw['exercise']['questions'][1].update(prompt='One tenth of the combined revenue is donated. What is the donation?',
            answer='Crop A earns 18125; Crop B earns 18550; donation 3666.25.',
            calculation={'expression':'(1450*12.50+2120*8.75)/10','answer':'3666.25'})
        correction={'exercise':{'questions':[{'id':'2','answer':'3667.5 dollars.'}]}}
        api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(reply)),finish_reason='stop')]) for reply in (raw,correction)]
        config=workbook_config('5th-6th',simple=True)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(12,12,coherent=True),lambda page:validate_design(page,12,quality=config,
                expected_title='Revenue Practice',require_coherent=True),'Exercise repair 7',
                response_schema=design_schema({'render_mode':'authored','mechanic':'data_interpretation'},config))
        self.assertEqual(api.chat.completions.create.call_count,2)
        question=result['exercise']['questions'][1]
        self.assertEqual(Fraction(question['calculation']['answer']),Fraction('3667.5'))
        self.assertEqual(question['answer'],'3667.5 dollars.')
        self.assertEqual(question['prompt'],raw['exercise']['questions'][1]['prompt'])
        self.assertEqual(result['exercise']['stimuli'],raw['exercise']['stimuli'])
        self.assertEqual(result['images'],raw['images'])

    def test_unreferenced_bad_caption_suggestions_do_not_block_html_only_repair(self):
        """Discard unused repair suggestions without admitting malformed referenced captions."""
        raw=text_card_page();before=deepcopy(raw)
        correction={'html':raw['html'],'exercise':{'captions':[{'id':'A Very Long Unused Heading Identifier','text':'Unrelated words'}]}}
        result=merge_layout_repair(raw,correction)
        self.assertEqual(result['exercise'],before['exercise'])
        self.assertEqual(result['html'],before['html'])
