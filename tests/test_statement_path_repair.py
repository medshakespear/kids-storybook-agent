"""Repair route prerequisites without literal-word false positives or frozen layout retries."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.response_schemas import design_schema
from core.statement_path_repair import merge_repair
from tests import test_statement_maze_and_artwork as fixtures


class StatementPathRepairTests(unittest.TestCase):
    """Exercise actual generation, scoped repairs and real WeasyPrint print geometry."""

    def source_page(self):
        """Remove route metadata while retaining all original facts and the route question/key."""
        page=fixtures.StatementMazeAndArtworkTests().statement_page()
        page['exercise']['directions']='Use the printed connections to follow only factual statements.'
        page['exercise']['questions'][0]['prompt']='Record the full checkpoint route.'
        for card in page['exercise']['stimuli']:
            card['text']=card['text'].split(' If factual,')[0].split(' Return to START.')[0]
            card['text']=card['text'].replace('START - A:','A:').replace('E - FINISH:','E:')
        return page

    def route_update(self,page,begin='START: A',end='FINISH: E',link=None):
        """Add only route annotations while repeating the retained complete source cards."""
        labels=[{'id':'start_mark','text':begin},{'id':'finish_mark','text':end}]
        if link is not None:
            labels.append({'id':'connections','text':link})
        else:
            labels.extend([{'id':'a_links','text':'A: factual → B; opinion → D.'},
                {'id':'b_links','text':'B: factual → C; opinion → D.'},
                {'id':'c_links','text':'C: factual → E; opinion → D.'},
                {'id':'d_links','text':'D: return to START.'}])
        return {'exercise':{'captions':labels,
            'stimuli':deepcopy(page['exercise']['stimuli'])}}

    def generate(self,page,band,responses,*,first_layout_failure=False):
        """Call the production retry loop, optionally starting with its previous layout-only latch."""
        case=fixtures.StatementMazeAndArtworkTests();config=case.profile(band)
        brief={'render_mode':'authored','mechanic':'statement_path'};api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(response)),finish_reason='stop')]) for response in responses]
        checks=0

        def validate(raw):
            """Run actual content and geometry checks after an optional initial geometry defect."""
            nonlocal checks
            checks+=1
            if first_layout_failure and checks==1:
                raise ValueError('Design overflow: expected 1 pages, got 2')
            return validate_design(raw,config['student_font_pt'],quality=config,
                expected_title=case.diagnostic()['title'],require_coherent=True,brief=brief)

        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'), \
             patch('core.layout_recovery.layout_recovery_candidates',return_value=iter(())):
            result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                validate,'Activity design 1',response_schema=design_schema(brief,config))
        return result,api

    def test_endpoints_in_captions_and_arrow_or_move_links_need_no_repair_both_grades(self):
        """Printed endpoint labels are valid outside source cards, and ordinary arrows are connections."""
        for band in ('3rd-4th','5th-6th'):
            for link in ('A → B → C → E','A -> B -> C -> E','Next: B; B ⇒ C; C ⇒ E',
                         'A: move to B; B: advance to C; C: proceed to E',
                         'Checkpoint A → Checkpoint B → Checkpoint C → Checkpoint E'):
                with self.subTest(band=band,link=link):
                    page=self.source_page()
                    page=merge_repair(page,self.route_update(page,'BEGIN at A','END at E',link))
                    page['exercise']['directions']+=' Color the owl illustration after recording your route.'
                    original=deepcopy(page)
                    result,api=self.generate(page,band,[page])
                    self.assertEqual(api.chat.completions.create.call_count,1)
                    self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])
                    self.assertEqual(result['images'],page['images'])
                    self.assertIn('BEGIN at A',result['html']);self.assertIn('END at E',result['html'])
                    self.assertEqual(page,original)

    def test_missing_prerequisites_receive_one_scoped_correction_both_grades(self):
        """A route detail failure requests data additions instead of another full page design."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.source_page();original=deepcopy(page);update=self.route_update(page)
                update['exercise']['questions']=[{'id':'99','prompt':'Discard the old activity.'}]
                update['html']='<p>Replace the workbook.</p>';update['images']=[]
                result,api=self.generate(page,band,[page,update])
                self.assertEqual(api.chat.completions.create.call_count,2)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
                self.assertEqual(result['images'],original['images'])
                for height in (12,22): self.assertIn(f'height:{height}mm',result['html'])
                self.assertNotIn('Replace the workbook',result['html'])
                second=api.chat.completions.create.call_args_list[1].kwargs
                schema=second['response_format']['json_schema']['schema']
                self.assertEqual(set(schema['properties']),{'exercise'})
                self.assertEqual(set(schema['properties']['exercise']['properties']),{'directions','captions','stimuli'})
                self.assertIn('Repair ONLY the missing printed route details',second['messages'][1]['content'])
                self.assertEqual(page,original)

    def test_route_content_repair_clears_a_previous_layout_only_latch(self):
        """Source additions must not be discarded by the earlier HTML-only repair state."""
        page=self.source_page();update=self.route_update(page)
        result,api=self.generate(page,'3rd-4th',[page,{'html':page['html']},update],first_layout_failure=True)
        self.assertEqual(api.chat.completions.create.call_count,3)
        self.assertIn('START: A',result['html']);self.assertIn('FINISH: E',result['html'])
        last=api.chat.completions.create.call_args_list[-1].kwargs
        self.assertEqual(set(last['response_format']['json_schema']['schema']['properties']),{'exercise'})

    def test_repair_changes_only_an_explicit_art_routing_reference(self):
        """A route can move to printed cards without rewriting the question, key or unrelated image activity."""
        case=fixtures.StatementMazeAndArtworkTests()
        page=case.statement_page()
        page['exercise']['questions'][0]['prompt']='Follow the route in the owl illustration and record the checkpoint letters.'
        page['exercise']['directions']+=' Color the owl illustration after recording the route.'
        original=deepcopy(page)
        result,api=self.generate(page,'3rd-4th',[page,{'exercise':{'captions':[],
            'stimuli':page['exercise']['stimuli']}}])
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertEqual(result['exercise']['questions'][0]['prompt'],
            'Follow the route using the printed source cards and route connections and record the checkpoint letters.')
        for field in ('answer','id','space_mm'):
            self.assertEqual(result['exercise']['questions'][0][field],original['exercise']['questions'][0][field])
        self.assertEqual(result['exercise']['questions'][1],original['exercise']['questions'][1])
        self.assertEqual(result['exercise']['directions'],original['exercise']['directions'])

    def test_merge_retains_facts_artwork_questions_and_independent_blank_panels(self):
        """Only additive route labels may surround old facts; no model-proposed task replacement applies."""
        page=self.source_page();page['html']+='<div style="height:18mm;border:1mm solid #167E80"></div>'
        original=deepcopy(page);update=self.route_update(page)
        update['exercise']['stimuli'][0]['text']='Changed historical date: 1999.'
        update['exercise']['stimuli'][1]['text']='Node B: '+page['exercise']['stimuli'][1]['text']+' Next: C.'
        update['exercise']['stimuli'][2]['text']=page['exercise']['stimuli'][2]['text'].lower()
        update['exercise'].update(goal='Discard the goal',mechanic='count',questions=[])
        result=merge_repair(page,update)
        self.assertEqual(result['exercise']['stimuli'][0],original['exercise']['stimuli'][0])
        self.assertIn(original['exercise']['stimuli'][1]['text'],result['exercise']['stimuli'][1]['text'])
        self.assertEqual(result['exercise']['stimuli'][2],original['exercise']['stimuli'][2])
        for key in ('goal','mechanic','questions','render_mode'):
            self.assertEqual(result['exercise'][key],original['exercise'][key])
        self.assertEqual(result['images'],original['images'])
        self.assertIn('height:18mm',result['html'])
        self.assertEqual(result['html'].count('data-content="caption_start_mark"'),1)
        self.assertEqual(page,original)

    def test_image_prompts_cannot_supply_missing_route_links(self):
        """Prerequisites come from printed text; an art prompt with endpoint words cannot satisfy them."""
        page=self.source_page();case=fixtures.StatementMazeAndArtworkTests()
        page['images'][0]['prompt']='START A → B → C → E FINISH on a museum path.'
        with self.assertRaisesRegex(ValueError,'Print explicit next-step links') as caught:
            validate_design(page,12,quality=case.profile('3rd-4th'),
                expected_title=case.diagnostic()['title'],require_coherent=True)
        self.assertEqual(caught.exception.layout_source['exercise']['questions'],page['exercise']['questions'])

    def test_schema_requires_printed_statement_cards_in_the_first_response(self):
        """The initial structured response asks for the source prerequisites rather than omitting them."""
        config=fixtures.StatementMazeAndArtworkTests().profile('3rd-4th')
        schema=design_schema({'render_mode':'authored','mechanic':'statement_path'},config)['properties']['exercise']
        self.assertIn('stimuli',schema['required'])
        self.assertEqual(schema['properties']['stimuli']['minItems'],2)
