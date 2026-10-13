"""Keep mixed exact pages on the same declared caption profile through recovery."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from core.creative_generator import ask_json, validate_design, layout_contract, density_guidance
from core.pipeline import load_grade_config
from core.response_schemas import exercise_schema, design_schema
from core.page_contract import compile_exercise
from core.content_binding import validate_caption_budget
from tests.coherent_fixtures import exact_page, visual_examples


class MixedExactCaptionProfileTests(unittest.TestCase):
    """Labels remain bounded, readable, and tied to the original computed puzzle."""

    def config(self, band):
        """Use the production opt-in mixed profile without changing global grades."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    context_caption_limit=24,stimulus_limit=4,table_caption_limit=36,items_per_page=2)

    def page(self):
        """Return eight short factual labels and a too-small sorting graphic."""
        page=exact_page(visual_examples()[5])
        page['html']=page['html'].replace('width:175mm;height:150mm','width:90mm;height:50mm')
        page['exercise']['captions']=[{'id':f'label{i}','text':f'Exhibit {i}'} for i in range(8)]
        labels=''.join(f'<span data-content="caption_label{i}" style="margin-right:2mm"></span>' for i in range(8))
        page['html']='<p>'+labels+'</p>'+page['html']
        return page

    def test_schema_and_validation_use_mixed_exact_limit(self):
        """Only opt-in mixed exact pages expand capacity; legacy exact pages retain six."""
        brief={'render_mode':'exact','mechanic':'sort'}
        for band in ('3rd-4th','5th-6th'):
            config=self.config(band)
            self.assertEqual(exercise_schema(brief,config)['properties']['captions']['maxItems'],32)
            legacy=dict(config);legacy.pop('stimulus_limit')
            self.assertEqual(exercise_schema(brief,legacy)['properties']['captions']['maxItems'],14)
            page=self.page()
            compile_exercise(page,config,'Museum Sorting',defer_visual_sizing=True)
            self.assertEqual(page['_caption_context_limit'],24)
            self.assertEqual(len(page['exercise']['captions']),8)
            with self.assertRaisesRegex(ValueError,'at most six'):
                compile_exercise(self.page(),legacy,'Museum Sorting',defer_visual_sizing=True)

    def test_small_label_failure_retains_real_profile_and_recovers_without_extra_completion(self):
        """A compile-time sizing error must not send recovery back to the six-caption profile."""
        for band in ('3rd-4th','5th-6th'):
            config=self.config(band);raw=self.page();original=deepcopy(raw)
            with self.assertRaisesRegex(ValueError,'Exact visual labels') as failure:
                validate_design(raw,config['student_font_pt'],quality=config,
                                expected_title='Museum Sorting',require_coherent=True)
            self.assertEqual(failure.exception.layout_source['_recovery_config'],config)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            brief={'render_mode':'exact','mechanic':'sort'}
            prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
                result=ask_json(prompt,lambda page:validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Museum Sorting',require_coherent=True,brief=brief),'Activity design 1',
                    response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
            self.assertEqual(result['exercise']['visual'],original['exercise']['visual'])
            self.assertEqual(raw,original)

    def test_limits_and_instruction_guards_still_apply(self):
        """Expanded factual-label capacity cannot license unlimited context or duplicate tasks."""
        with self.assertRaises(ValueError):
            validate_caption_budget([{'id':f'c{i}','text':'Context'} for i in range(25)],context_limit=24)
        page=self.page();page['exercise']['captions'][0]['text']='Sort the objects and write a new sorting rule.'
        with self.assertRaisesRegex(ValueError,'Exact captions must not contain task directions'):
            compile_exercise(page,self.config('3rd-4th'),'Museum Sorting',defer_visual_sizing=True)

    def test_binding_repair_schema_preserves_expanded_capacity_and_original_context(self):
        """A later binding defect must not recreate the old fourteen-entry repair schema."""
        config=self.config('3rd-4th');raw=self.page()
        raw['html']=raw['html'].replace('width:90mm;height:50mm','width:175mm;height:150mm')
        raw['html']+='<p>Museum corner</p>'
        good=deepcopy(raw)
        good['exercise']['captions'].append({'id':'corner','text':'Museum corner'})
        good['html']=good['html'].replace('<p>Museum corner</p>','<p data-content="caption_corner"></p>')
        api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')]) for page in (raw,good)]
        brief={'render_mode':'exact','mechanic':'sort'}
        prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(prompt,lambda page:validate_design(page,config['student_font_pt'],quality=config,
                expected_title='Museum Sorting',require_coherent=True,brief=brief),'Activity design 1',
                response_schema=design_schema(brief,config))
        self.assertEqual(api.chat.completions.create.call_count,2)
        schema=api.chat.completions.create.call_args.kwargs['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['exercise']['properties']['captions']['maxItems'],32)
        self.assertEqual(result['exercise']['captions'][:8],raw['exercise']['captions'])
        self.assertIn('Museum corner',result['html'])
