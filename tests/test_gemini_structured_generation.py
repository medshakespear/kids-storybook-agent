"""Exercise schema requests and a complete repaired 12-page PDF without live API billing."""
from copy import deepcopy
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, merge_prompt_repair, validate_design
from core.pipeline import generate_book, load_grade_config
from core.response_schemas import design_schema, plan_schema, visual_schema
from core.layout_recovery import multiple_illustration_recovery
from tests.coherent_fixtures import authored_page, visual_examples
from tests.test_creative_design import cover_fixture, attach_creative_test_art


def completion(value):
    """Return the same completion shape as the OpenAI-compatible Gemini endpoint."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)),finish_reason='stop')])


class GeminiStructuredGenerationTests(unittest.TestCase):
    """Prove prevention and retained-data repair through actual compilation and PDF layout."""

    def test_plan_and_page_schemas_require_core_fields(self):
        """Null manifests and missing render modes cannot satisfy production request schemas."""
        plan = plan_schema(10)
        self.assertEqual(plan['properties']['pages']['minItems'],10)
        self.assertIn('render_mode',plan['properties']['pages']['items']['required'])
        page = design_schema({'render_mode':'authored','mechanic':'invent'},load_grade_config()['5th-6th'])
        self.assertEqual(page['required'],['html','images','exercise'])
        self.assertEqual(page['properties']['images']['type'],'array')
        self.assertEqual(page['properties']['images']['minItems'],1)
        self.assertIn('directions',page['properties']['exercise']['required'])
        self.assertNotIn('visual',page['properties']['exercise']['properties'])
        for band,cfg in load_grade_config().items():
            directions=design_schema({'render_mode':'authored','mechanic':'invent'},cfg)['properties']['exercise']['properties']['directions']
            limit=180 if cfg['student_font_pt']>=14 else 350
            self.assertIn(f'at most {limit} characters',directions['description'])
        for spec in visual_examples():
            schema = visual_schema(spec['kind'])
            self.assertEqual(schema['properties']['kind']['enum'],[spec['kind']])
            self.assertEqual(schema['properties']['question']['type'],'integer')
            self.assertFalse(schema['additionalProperties'])

    def test_real_sdk_sends_schema_to_gemini_compatible_endpoint(self):
        """Check serialized SDK requests rather than only a mocked create call."""
        import httpx
        from openai import OpenAI
        page = authored_page()
        schema = design_schema({'render_mode':'authored','mechanic':'design shelter'},load_grade_config()['5th-6th'])
        requests = []
        def handle(request):
            """Capture the outbound JSON and return a simulated endpoint completion."""
            requests.append(json.loads(request.content))
            return httpx.Response(200,json={'id':'fixture','object':'chat.completion','created':0,'model':'fixture',
                'choices':[{'index':0,'message':{'role':'assistant','content':json.dumps(page)},'finish_reason':'stop'}]})
        api = OpenAI(api_key='test-key',base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
                     http_client=httpx.Client(transport=httpx.MockTransport(handle)),max_retries=0)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
            result=ask_json(layout_contract(11,11,coherent=True),lambda raw:validate_design(raw,11,
                quality=load_grade_config()['5th-6th'],expected_title='Plant Studio',require_coherent=True),
                'Activity design 1',response_schema=schema)
        self.assertEqual(requests[0]['response_format']['type'],'json_schema')
        self.assertEqual(requests[0]['response_format']['json_schema']['schema'],schema)
        self.assertEqual(result['exercise']['mechanic'],'design shelter')

    def test_equivalent_number_formatting_is_preserved_but_changed_value_is_rejected(self):
        """Display shortening must not alter mathematical quantities or their multiplicity."""
        page=authored_page()
        page['exercise']['questions'][0]['prompt']='A kit costs $12.00. Buy 2 kits. What is the total?'
        fixed=merge_prompt_repair(page,{'exercise':{'questions':[{'id':'1','prompt':'Each kit costs $12. Buy 2 kits. Find the total.'}]}},'1')
        self.assertEqual(fixed['exercise']['questions'][0]['answer'],page['exercise']['questions'][0]['answer'])
        with self.assertRaisesRegex(ValueError,'numeric value'):
            merge_prompt_repair(page,{'exercise':{'questions':[{'id':'1','prompt':'Each kit costs $12. Buy 3 kits. Find the total.'}]}},'1')

    def test_readable_upper_grade_prompt_over_220_characters_is_accepted_intact(self):
        """A complete task is governed by grade-level density and measured fit, not a universal cap."""
        cfg=load_grade_config()['5th-6th']
        page=authored_page()
        prompt=('Design a shelter for this plant using a transparent roof, an opening for watering and a stable base. '
                'Label the three features. Explain how your design provides sunlight, allows watering and remains '
                'stable when placed on the classroom windowsill.')
        page['exercise']['questions'][0].update(prompt=prompt,space_mm=25,
            answer='Accept a stable design with a transparent roof and watering opening; labels and explanation address all three features.')
        self.assertGreater(len(prompt),220)
        result=validate_design(page,11,quality=cfg,expected_title='Plant Studio',require_coherent=True)
        self.assertEqual(result['exercise']['questions'][0]['prompt'],prompt)

    def test_multi_asset_reflow_retains_all_images_and_response_space(self):
        """A repaired gallery preserves purposeful secondary art and the canonical tasks."""
        cfg=load_grade_config()['1st-2nd']
        page=authored_page()
        page['images'] += [{'id':'tools','prompt':'An original watering can on white, no text.'}]
        page['html'] += '<img data-asset="tools" style="width:25mm;height:25mm"/>'
        rebuilt=multiple_illustration_recovery(page,13,10000)
        self.assertIsNotNone(rebuilt)
        validated=validate_design(rebuilt,14,quality=cfg,expected_title='Plant Studio',require_coherent=True)
        self.assertEqual(validated['images'],page['images'])
        self.assertEqual(validated['exercise']['questions'],page['exercise']['questions'])
        self.assertEqual(validated['source_layout'].count('data-asset="tools"'),1)

    def test_full_twelve_page_pipeline_recovers_prompt_manifest_layout_and_math(self):
        """Run real plan validation, scoped repairs, artwork embedding and final PDF assembly."""
        cfg=load_grade_config();count=cfg['5th-6th']['activity_pages']
        self.assertEqual(count+2,12)
        briefs=[dict(title=f'Studio Mission {i}',learning_goal=f'Investigate design feature {i}.',
                      activity_concept=f'Invent a useful solution for plant challenge {i}.',
                      layout_brief=f'Original composition {i}.',render_mode='authored',mechanic=f'challenge {i}')
                for i in range(1,count+1)]
        plan=dict(title='Plant Inventors',overview='Investigate and create useful plant designs.',
                  art_direction='Teal and coral with crisp expressive outlines.',
                  character_description='Original friendly plant and gardening tools.',
                  cover_brief='A large cheerful plant and the Plant Inventors title.',pages=briefs)
        pages=[authored_page(mechanic=f'challenge {i}') for i in range(1,count+1)]
        short='A kit costs $12.00. Buy 2 kits. Find the total.'
        pages[0]['exercise']['questions'][0].update(prompt='Consider this classroom purchasing scenario carefully. '*14+short,
            answer='$24',space_mm=20,calculation={'expression':'12*2','answer':'24'})
        bad={'exercise':{'questions':[{'id':'1','prompt':'A kit costs $12. Buy 3 kits. Find the total.'}]}}
        good={'exercise':{'questions':[{'id':'1','prompt':'Each kit costs $12. Buy 2 kits. Find the total.'}]}}
        manifest=deepcopy(pages[1]['images']);pages[1]['images']=None
        pages[2]['html']='<div style="padding-top:200mm">'+pages[2]['html']+'</div>'
        pages[3]['exercise']['questions'][0].update(prompt='Calculate 12 + 8.',answer='21',space_mm=20,
                                                  calculation={'expression':'12+8','answer':'21'})
        replies=[plan,cover_fixture(),pages[0],bad,good,pages[1],{'images':manifest},*pages[2:],
                 {'pages':[{'page_number':i,'issues':[]} for i in range(1,count+1)]}]
        api=Mock();api.chat.completions.create.side_effect=[completion(r) for r in replies]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'DESIGN_WORKERS':'1'}), \
             patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.text_worker_limit',return_value=1), \
             patch('core.creative_generator.time.sleep'), \
             patch('core.pipeline.text_provider_names',return_value=['gemini']), \
             patch('core.pipeline.image_provider_name',return_value='cloudflare'), \
             patch('core.pipeline.generate_activity_images',side_effect=attach_creative_test_art):
            pack,path=generate_book(theme='Plant invention',grade_band='5th-6th',grade_config=cfg,output_dir=folder)
            self.assertTrue(path.is_file())
            self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
            self.assertEqual(pack['page_count'],12)
            self.assertEqual(pack['content_checks']['status'],'passed')
            self.assertEqual(pack['pages'][0]['exercise']['questions'][0]['prompt'],good['exercise']['questions'][0]['prompt'])
            self.assertEqual(pack['pages'][1]['images'][0]['id'],'scene')
            self.assertEqual(pack['pages'][3]['exercise']['questions'][0]['answer'],'20')
            requests=api.chat.completions.create.call_args_list
            self.assertEqual(len(requests),len(replies))
            for index in (0,1,2,3,4,5,6,7):
                self.assertEqual(requests[index].kwargs['response_format']['type'],'json_schema')
            repair_messages=requests[4].kwargs['messages']
            self.assertEqual(len(repair_messages),2)
            self.assertIn('numeric_tokens_to_preserve',repair_messages[1]['content'])
            self.assertNotIn('data-asset',repair_messages[1]['content'])
            self.assertIn('12.00',repair_messages[1]['content'])


if __name__=='__main__':
    unittest.main()
