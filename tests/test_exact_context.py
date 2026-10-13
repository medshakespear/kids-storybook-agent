"""Recover exact-page context without removing independent student work."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from core.exact_context import normalize_exact_context
from core.page_contract import compile_exercise
from core.pipeline import load_grade_config
from tests.coherent_fixtures import exact_page, visual_examples


class ExactContextTests(unittest.TestCase):
    """Use real computed graphics and canonical content binding for both active bands."""

    def test_long_factual_intro_and_empty_directions_bind_locally(self):
        """All source words and the additional question survive caption splitting."""
        for band in ('3rd-4th','5th-6th'):
            page=exact_page(visual_examples()[5])
            intro=('These fictional museum cards include different shapes and colors. '
                   'The classroom display uses clear groups so visitors can see how objects share features.')
            question={'id':'2','prompt':'Describe one useful feature of the display.',
                      'answer':'Accept a feature that helps visitors understand the groups.','space_mm':25}
            page['exercise'].update(captions=[{'id':'intro','text':intro}],questions=[question])
            page['html']+='<p data-content="directions"></p><p data-content="caption_intro"></p><h2>Activity Sorting Task</h2><div data-content="question_2"></div>'
            original=deepcopy(page['exercise']['visual'])
            compile_exercise(page,load_grade_config()[band],'Museum Groups')
            joined=' '.join(c['text'] for c in page['exercise']['captions'] if c['id'].startswith('intro_part'))
            self.assertEqual(joined,intro)
            self.assertEqual(page['exercise']['questions'],[question])
            self.assertEqual(page['exercise']['visual'],original)
            self.assertIn('Activity Sorting Task',page['html'])
            self.assertIn('height:25mm',page['html'])
            self.assertNotIn('data-content="directions"',page['source_layout'])

    def test_empty_slot_with_art_or_workspace_still_requires_repair(self):
        """An absent direction field never licenses deleting artwork or a writing area."""
        exercise={'render_mode':'exact'}
        for markup in ('<p data-content="directions">Explain your choice.</p>',
                       '<div data-content="directions" style="height:25mm"></div>',
                       '<p data-content="directions"><img data-visual="groups"/></p>',
                       '<img data-content="directions" data-asset="scene"/>',
                       '<p data-content="directions" style="border:1mm solid #000000"></p>'):
            with self.subTest(markup=markup):
                self.assertEqual(normalize_exact_context(deepcopy(exercise),markup),markup.replace('/>', '>'))

    def test_long_instruction_or_missing_caption_is_not_invented(self):
        """Only explicit complete factual context is eligible for lossless splitting."""
        for text in ('Draw the objects and write a sentence about every object. '*4,None,''):
            page=exact_page(visual_examples()[5]);page['exercise']['captions']=[{'id':'intro','text':text}]
            markup='<p data-content="caption_intro"></p>'
            result=normalize_exact_context(page['exercise'],markup)
            self.assertEqual(page['exercise']['captions'],[{'id':'intro','text':text}])
            self.assertIn('caption_intro',result)

    def test_caption_budget_and_collisions_are_not_bypassed(self):
        """Splitting cannot create excessive captions or duplicate identifiers."""
        intro='These objects have different features. '*5
        for extras in ([{'id':f'label{i}','text':f'Label {i}'} for i in range(5)],
                       [{'id':'intro_part1','text':'An existing label'}]):
            exercise={'render_mode':'exact','captions':[{'id':'intro','text':intro}]+extras}
            original=deepcopy(exercise)
            normalize_exact_context(exercise,'<p data-content="caption_intro"></p>')
            self.assertEqual(exercise,original)

    def test_real_generation_flow_repairs_binding_and_small_labels_in_one_call(self):
        """Both grades preserve the puzzle and context through actual measured recovery."""
        from core.creative_generator import ask_json, validate_design, layout_contract, density_guidance
        from core.response_schemas import design_schema
        for band in ('3rd-4th','5th-6th'):
            config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                        stimulus_limit=4,context_caption_limit=24,items_per_page=2)
            page=exact_page(visual_examples()[5])
            page['html']=page['html'].replace('width:175mm;height:150mm','width:90mm;height:50mm')
            intro='These fictional exhibit cards have different features. Visitors use the clear groups to compare shapes and notice how the objects are alike.'
            page['exercise']['captions']=[{'id':'intro','text':intro}]
            page['html']+='<p data-content="directions"></p><p data-content="caption_intro"></p><h2>Activity Sorting Task</h2>'
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
            brief={'render_mode':'exact','mechanic':'sort'}
            prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
                result=ask_json(prompt,lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                    expected_title='Museum Groups',require_coherent=True,brief=brief),'Activity design 2',
                    response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            retained=' '.join(c['text'] for c in result['exercise']['captions'] if c['id'].startswith('intro_part'))
            self.assertEqual(retained,intro)
            self.assertEqual(result['exercise']['visual'],page['exercise']['visual'])
