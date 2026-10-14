"""Repair missing source-card manifests without replacing retained student tasks."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from core.activity_stimuli import merge_missing_sources, stimulus_capacity
from core.creative_generator import ask_json, validate_design, layout_contract, density_guidance, merge_exact_wording_repair
from core.response_schemas import design_schema, exercise_schema
from core.page_contract import BoundLayout
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page, exact_page, visual_examples


class SourceManifestRecoveryTests(unittest.TestCase):
    """Use real canonical compilation and print checking for both active bands."""

    def page(self):
        """Declare four sources but reference a fifth, matching the reported failure."""
        page=authored_page(mechanic='compare_scenarios')
        page['exercise'].update(directions='Read the fictional planning cards. Compare two useful choices.',
            stimuli=[{'id':'card_'+letter,'text':f'Fictional case {letter.upper()}: Students test their classroom display with visitors.'} for letter in 'abcd'],captions=[])
        page['exercise']['questions']=[{'id':'1','prompt':'Compare two planning choices from the cards.',
            'answer':'Accept an accurate comparison supported by two cards.','space_mm':25}]
        page['html']=('<h1 data-content="title"></h1><p data-content="directions"></p>'
            '<table style="width:175mm;border-collapse:collapse"><tr><td style="width:92mm;vertical-align:top">'
            '<img data-asset="scene" style="width:90mm;height:90mm"/></td><td style="vertical-align:top">'+
            ''.join(f'<p data-content="stimulus_card_{letter}" style="margin:0 0 2mm"></p>' for letter in 'abcde')+
            '</td></tr></table><div data-content="question_1"></div><p>___________ |</p>')
        return page

    def test_fifth_source_is_content_repair_and_retained_tasks_survive(self):
        """Repair missing E using a full source schema, then measure the same exercise."""
        for band in ('3rd-4th','5th-6th'):
            config=dict(load_grade_config()[band],purposeful_activity_layout=False,stimulus_limit=8,
                        context_caption_limit=24,table_caption_limit=36,items_per_page=2)
            raw=self.page();original=deepcopy(raw);good=deepcopy(raw)
            extra={'id':'card_e','text':'Fictional case E: Students revise unclear labels after visitor feedback.'}
            good['exercise']['stimuli'].append(extra)
            good['exercise']['questions'][0]['answer']='An unrelated replacement answer.'
            api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')]) for page in (raw,good)]
            brief={'render_mode':'authored','mechanic':'compare_scenarios'}
            prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                 patch('core.creative_generator.time.sleep'):
                result=ask_json(prompt,lambda page:validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Planning Cards',require_coherent=True,brief=brief),'Activity design 1',
                    response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,2)
            schema=api.chat.completions.create.call_args.kwargs['response_format']['json_schema']['schema']
            self.assertEqual(schema['properties']['exercise']['properties']['stimuli']['maxItems'],8)
            self.assertIn('SOURCE MANIFEST repair',api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])
            self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli']+[extra])
            self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
            self.assertEqual(result['images'],original['images'])
            self.assertIn('height:25mm',result['html'])
            self.assertIn('___________ |',result['html'])
            self.assertEqual(raw,original)

    def test_schema_and_python_share_configured_source_capacity(self):
        """Eight short-card mode is opt-in; an existing four-card profile stays at four."""
        brief={'render_mode':'authored','mechanic':'compare'}
        for limit in (4,8):
            self.assertEqual(stimulus_capacity({'stimulus_limit':limit}),limit)
            schema=exercise_schema(brief,dict(load_grade_config()['3rd-4th'],stimulus_limit=limit))
            self.assertEqual(schema['properties']['stimuli']['maxItems'],limit)
        for limit in (0,9,True,'8'):
            with self.assertRaises(ValueError):stimulus_capacity({'stimulus_limit':limit})

    def test_exact_source_repair_preserves_puzzle_and_recovers_label_size(self):
        """A missing supporting card is supplied once, with real geometry in both grades."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,items_per_page=2)
                raw=exact_page(visual_examples()[5]);raw['exercise']['stimuli']=[]
                raw['exercise']['questions']=[{'id':'2','prompt':'Explain one useful classroom idea from Card A.',
                    'answer':'Accept an explanation of testing clear labels with visitors.','space_mm':15}]
                raw['html']=raw['html'].replace('width:175mm;height:150mm','width:95mm;height:75mm')
                raw['html']+='<p data-content="directions"></p><p data-content="stimulus_card_a"></p><div data-content="question_2"></div>'
                original=deepcopy(raw);good=deepcopy(raw)
                source={'id':'card_a','text':'Fictional Card A: Students test their display labels with classroom visitors.'}
                good['exercise']['stimuli']=[source]
                good['exercise']['visual']['items']=[]  # This unwanted drift must not be adopted.
                good['exercise']['questions'][0]['answer']='Unrelated answer.'
                api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')]) for page in (raw,good)]
                brief={'render_mode':'exact','mechanic':'sort'}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda page:validate_design(page,config['student_font_pt'],quality=config,
                            expected_title='Museum Sorting',require_coherent=True,brief=brief),
                        'Activity design 2',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,2)
                self.assertIn('SOURCE MANIFEST repair',api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])
                self.assertEqual(result['exercise']['stimuli'],[source])
                self.assertEqual(result['exercise']['visual'],original['exercise']['visual'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertIn('height:15mm',result['html'])
                self.assertEqual(result['html'].count(source['text']),1)
                self.assertNotIn('data-content="directions"',result['html'])
                self.assertEqual(raw,original)

    def test_missing_source_is_never_guessed_or_overwritten(self):
        """New text must exist explicitly once; all retained sources remain canonical."""
        raw=self.page()
        for new in ([],[{'id':'card_e','text':''}],
                    [{'id':'card_e','text':'One.'},{'id':'card_e','text':'Two.'}]):
            with self.subTest(new=new),self.assertRaises(ValueError):
                merge_missing_sources(raw,dict(html=raw['html'],exercise={'stimuli':new}))
        changed=deepcopy(raw);changed['exercise']['stimuli'][0]['text']='A changed existing source.'
        changed['exercise']['stimuli'].append({'id':'card_e','text':'A supplied missing source.'})
        result=merge_missing_sources(raw,changed)
        self.assertEqual(result['exercise']['stimuli'][:4],raw['exercise']['stimuli'])

    def test_exact_wording_repairs_cannot_replace_supporting_evidence(self):
        """A later directions correction retains existing source wording and puzzle data."""
        page=exact_page(visual_examples()[5])
        page['exercise']['stimuli']=[{'id':'card_a','text':'Fictional Card A: Visitors test clear labels.'}]
        correction=deepcopy(page)
        correction['exercise']['stimuli'][0]['text']='Different evidence.'
        result=merge_exact_wording_repair(page,correction)
        self.assertEqual(result['exercise']['stimuli'],page['exercise']['stimuli'])
        self.assertEqual(result['exercise']['visual'],page['exercise']['visual'])

    def test_blank_lines_with_table_separators_are_workspace_only(self):
        """Accept blank separators while rejecting words, numeric answers and extra tasks."""
        for value in ('___________ |','| ______ | ______ |'):
            parser=BoundLayout({'title':'Test'});parser.feed('<p>'+value+'</p>')
            self.assertIn(value,''.join(parser.parts))
        for value in ('___ | Answer: 2','___ | Explain your choice','2 | ___'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                BoundLayout({'title':'Test'}).feed('<p>'+value+'</p>')
