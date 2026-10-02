"""Regress exact-task raw wording, caption-direction and unknown-slot retry loops."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design, merge_exact_wording_repair
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page, visual_examples


class ExactWordingRecoveryTests(unittest.TestCase):
    """Keep factual context and real additional actions; never use captions for puzzle instructions."""

    def validate(self, page):
        """Compile canonical tasks and measure a first/second-grade page."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
            expected_title='Sorting Studio',require_coherent=True)

    def page(self):
        """Return a valid sorting tool with exact shapes, bins and computed answer."""
        return exact_page(visual_examples()[5])

    def ask(self, replies):
        """Use the actual production repair loop with simulated Gemini responses."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(p)),finish_reason='stop')]) for p in replies]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 2',
                response_schema=design_schema({'render_mode':'exact','mechanic':'sort'},load_grade_config()['1st-2nd']))
        return result,api

    def test_reported_raw_instruction_gets_content_repair_not_caption_only_merge(self):
        """The correction can remove unsupported parallel instructions without being pinned to them."""
        raw=self.page()
        raw['html']='<p>Help Little Raven and Pip sort cultural artifacts into the correct baskets!</p>'+raw['html']
        original=deepcopy(raw)
        good=self.page()
        result,api=self.ask([raw,good])
        self.assertEqual(raw,original)
        self.assertEqual(result['exercise']['visual'],good['exercise']['visual'])
        self.assertNotIn('cultural artifacts',result['html'])
        self.assertEqual(api.chat.completions.create.call_count,2)
        message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('EXACT-PUZZLE CONTENT/BINDING repair',message)
        self.assertNotIn('Repair ONLY this existing printable layout',message)
        schema=api.chat.completions.create.call_args.kwargs['response_format']['json_schema']['schema']
        self.assertIn('visual',schema['properties']['exercise']['properties'])

    def test_task_directions_cannot_become_caption_directions(self):
        """Catch the wrong caption correction before unknown-slot and stale-caption errors."""
        raw=self.page()
        raw['html']='<p>Help Pip sort these pictures into baskets!</p>'+raw['html']
        bad=self.page()
        bad['exercise']['captions']=[{'id':'directions','text':'Help Pip sort these pictures into baskets!'}]
        bad['html']='<p data-content="directions"></p>'+bad['html']
        good=self.page()
        result,api=self.ask([raw,bad,good])
        self.assertEqual(api.chat.completions.create.call_count,3)
        self.assertNotIn('caption_directions',result['html'])
        self.assertEqual(result['exercise']['visual'],good['exercise']['visual'])
        self.assertIn('Exact captions must not contain task directions',
            api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])

    def test_unknown_directions_slot_uses_full_shared_contract(self):
        """An exact page cannot repair a nonexistent directions field through HTML alone."""
        raw=self.page();raw['html']='<p data-content="directions"></p>'+raw['html']
        result,api=self.ask([raw,self.page()])
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertNotIn('data-content="directions"',result['source_layout'])
        self.assertIn('EXACT-PUZZLE CONTENT/BINDING repair',api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])

    def test_wording_repair_pins_graphic_data_and_protects_additional_questions(self):
        """Even a drifting model response cannot silently replace a correct exact puzzle."""
        original=self.page()
        question={'id':'2','prompt':'Invent a new shape and draw it.',
            'answer':'Accept an original drawn shape.','space_mm':20}
        original['exercise']['questions']=[question]
        original['html']+='<div data-content="question_2"></div>'
        changed=deepcopy(original);changed['exercise']['visual']['items']=[]
        repaired=merge_exact_wording_repair(original,changed)
        self.assertEqual(repaired['exercise']['visual'],original['exercise']['visual'])
        changed['exercise']['questions']=[]
        with self.assertRaisesRegex(ValueError,'preserve existing additional'):
            merge_exact_wording_repair(original,changed)

    def test_valid_context_and_extra_action_remain_printed_and_answered(self):
        """Context labels and independent creativity must not be deleted with parallel puzzle directions."""
        page=self.page()
        page['exercise']['captions']=[{'id':'context','text':'A colorful classroom sorting studio'}]
        page['exercise']['questions']=[{'id':'2','prompt':'Invent a new shape and draw it.',
            'answer':'Accept an original drawn shape.','space_mm':20}]
        page['html']='<p data-content="caption_context"></p>'+page['html']+'<div data-content="question_2"></div>'
        result=self.validate(page)
        self.assertIn('A colorful classroom sorting studio',result['html'])
        self.assertIn('Invent a new shape',result['html'])
        self.assertIn('Accept an original drawn shape',result['answers'])
        self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])


if __name__=='__main__':
    unittest.main()
