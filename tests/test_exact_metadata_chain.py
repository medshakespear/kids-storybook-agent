"""Regress reserved IDs, long captions and caption instructions on one exact page."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from core.creative_generator import ask_json, layout_contract, validate_design, exact_wording_requires_content_repair
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page, visual_examples


class ExactMetadataChainTests(unittest.TestCase):
    """Repair independent metadata defects without discarding real student work."""
    def setUp(self):
        """Use a known computed sorting puzzle with a genuine additional drawing task."""
        self.config = load_grade_config()['1st-2nd']
        self.page = exact_page(visual_examples()[5])
        self.extra = {'id':'2','prompt':'Draw a new picture for one shape group.',
                      'answer':'Accept a drawing belonging to one shape group.','space_mm':20}
        self.page['exercise']['questions'] = [deepcopy(self.extra)]
        self.page['html'] += '<div data-content="question_2"></div>'

    def validate(self, page):
        """Run the actual canonical compiler and printable geometry checks."""
        return validate_design(page,14,quality=self.config,expected_title='Sorting Studio',require_coherent=True)

    def test_three_reported_defects_follow_preserving_content_repair(self):
        """A sequence of corrections keeps the exact puzzle and valid extension intact."""
        raw = deepcopy(self.page)
        raw['exercise']['questions'].insert(0, {'id':'1','prompt':'Sort the pictures by shape.',
                                              'answer':'Use the pictured shape groups.','space_mm':0})
        raw['html'] += '<p data-content="question_1"></p>'
        long = {'id':'caption_ledger_desc','text':'Each ledger entry records the category of the pictured item. '*4}
        raw['exercise']['captions'] = [long]
        raw['html'] += '<p data-content="caption_caption_ledger_desc"></p>'
        label_fixed = deepcopy(self.page)
        label_fixed['exercise']['captions'] = [deepcopy(long)]
        label_fixed['html'] += '<p data-content="caption_caption_ledger_desc"></p>'
        instruction = deepcopy(label_fixed)
        instruction['exercise']['captions'][0]['text'] = 'Sort the pictures into the matching shape groups.'
        good = deepcopy(label_fixed)
        good['exercise']['captions'][0]['text'] = 'Each pictured item belongs to one shape group.'
        api = Mock()
        api.chat.completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(p)),finish_reason='stop')])
            for p in (raw,label_fixed,instruction,good)]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result = ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 2',
                             response_schema=design_schema({'render_mode':'exact','mechanic':'sort'},self.config))
        self.assertEqual(api.chat.completions.create.call_count,4)
        self.assertEqual(result['exercise']['visual'], self.page['exercise']['visual'])
        self.assertEqual(result['exercise']['questions'], [self.extra])
        self.assertIn('2. Draw a new picture', result['html'])
        for call in api.chat.completions.create.call_args_list[1:]:
            self.assertIn('EXACT-PUZZLE CONTENT/BINDING repair', call.kwargs['messages'][-1]['content'])

    def test_explanation_gets_unused_label_without_changing_the_task(self):
        """A distinct reasoning action is not a duplicate of the sorting puzzle."""
        page = deepcopy(self.page)
        page['exercise']['questions'] = [{'id':'1','prompt':'Explain why grouping similar shapes is useful.',
                                         'answer':'Accept a relevant organization benefit.','space_mm':20}]
        page['html'] = page['html'].replace('question_2','question_1')
        result = self.validate(page)
        self.assertEqual(result['exercise']['questions'][0], {**page['exercise']['questions'][0],'id':'2'})
        self.assertIn('2. Explain why',result['html'])

    def test_separate_arithmetic_gets_its_own_label_and_verified_key(self):
        """A numerical follow-up remains independently checked after renumbering."""
        page = deepcopy(self.page)
        page['exercise']['questions'] = [{'id':'1','prompt':'What is 6 + 4?', 'answer':'10',
            'space_mm':20,'calculation':{'expression':'6+4','answer':10}}]
        page['html'] = page['html'].replace('question_2','question_1')
        result = self.validate(page)
        self.assertEqual(result['exercise']['questions'][0]['id'], '2')
        self.assertEqual(result['calculations'][0]['question'], '2')
        self.assertIn('2. 10', result['answers'])

    def test_descriptive_caption_is_not_an_imperative(self):
        """Mentioning counting in a factual sentence must not be mistaken for a new task."""
        page = deepcopy(self.page)
        page['exercise']['captions'] = [{'id':'context','text':'Groups help students count the items in a collection.'}]
        page['html'] += '<p data-content="caption_context"></p>'
        result = self.validate(page)
        self.assertIn('Groups help students count', result['html'])

    def test_metadata_defects_are_not_layout_only_repairs(self):
        """The repair scope permits correcting invalid wording while keeping the puzzle fixed."""
        for error in ['Exercise caption caption_ledger_desc must be nonempty text <= 120 characters',
                      'Exercise question IDs must not duplicate visual question numbers: reserved label 1',
                      'Exact captions must not contain task directions']:
            self.assertTrue(exact_wording_requires_content_repair(self.page,error))
