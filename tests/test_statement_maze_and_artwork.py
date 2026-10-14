"""Replay the museum mismatch and verify safe routing-tool selection and exact-art recovery."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design,validate_plan
from core.exact_artwork_layout import exact_artwork_layout
from core.maze_intent import is_statement_maze
from core.page_contract import BoundLayout,validate_brief
from core.pipeline import load_grade_config
from core.response_schemas import design_schema,plan_schema
from tests.coherent_fixtures import authored_page,exact_page,visual_examples
from tests.test_plan_mechanics import plan_for


class StatementMazeAndArtworkTests(unittest.TestCase):
    """Use the real compiler and PDF geometry; only provider responses are mocked."""

    def diagnostic(self):
        """Read the actual failed generated page without private transport metadata."""
        return json.loads((Path(__file__).parent/'fixtures'/'museum_statement_maze.json').read_text())

    def profile(self,band):
        """Apply the production varied-workbook settings for either active grade."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
            stimulus_limit=8,context_caption_limit=24,table_caption_limit=36,items_per_page=2)

    def ask_once(self,page,config,title,brief):
        """Run the actual scoped generation/recovery path on one provider response."""
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                    expected_title=title,require_coherent=True,brief=brief),
                'Activity design 6',response_schema=design_schema(brief,config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        return result

    def test_uploaded_semantic_mismatch_is_rejected_before_layout_retries(self):
        """Do not print a star maze as though it contains the authored statement checkpoints."""
        raw=self.diagnostic();original=deepcopy(raw)
        self.assertTrue(is_statement_maze(raw['page']['exercise']))
        for band in ('3rd-4th','5th-6th'):
            config=self.profile(band)
            with self.assertRaisesRegex(ValueError,'Statement-path task cannot use the geometric maze tool'):
                validate_design(raw['page'],config['student_font_pt'],quality=config,
                    expected_title=raw['title'],require_coherent=True)
            page=deepcopy(raw['page']);page['_recovery_config']=config;page['_recovery_title']=raw['title']
            self.assertIsNone(exact_artwork_layout(page,config['minimum_text_pt'],config['visual_area_mm2']))
        self.assertEqual(raw,original)

    def test_planner_selects_authored_representation_without_regenerating_the_concept(self):
        """Correct tool selection before any graphic or numbered student activity exists."""
        raw=self.diagnostic();plan=plan_for(['maze']);brief=plan['pages'][0]
        brief.update(title=raw['title'],learning_goal=raw['page']['exercise']['goal'],
            activity_concept=raw['page']['exercise']['captions'][0]['text'])
        original=deepcopy(plan);api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(plan)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
            result=ask_json('Plan the original activities.',lambda raw:validate_plan(raw,1,require_coherent=True),
                'Creative plan',response_schema=plan_schema(1))
        self.assertEqual(api.chat.completions.create.call_count,1)
        corrected=result['pages'][0]
        self.assertEqual((corrected['render_mode'],corrected['mechanic']),('authored','statement_path'))
        for field in ('title','learning_goal','activity_concept','layout_brief'):
            self.assertEqual(corrected[field],original['pages'][0][field])
        schema=design_schema(corrected,self.profile('3rd-4th'))['properties']['exercise']['properties']
        self.assertNotIn('visual',schema);self.assertIn('directions',schema)
        self.assertEqual(plan,original)
        for goal in ('Trace the museum wall maze and count stars.',
                     'Learn museum facts, then trace the geometric maze to the exit.'):
            b={'render_mode':'exact','mechanic':'maze','learning_goal':goal,'activity_concept':'Trace the route.'}
            validate_brief(b,planning=True);self.assertEqual(b['render_mode'],'exact')

    def statement_page(self):
        """Provide a complete fictional reasoning path with explicit printed checkpoints."""
        raw=self.diagnostic();page=authored_page(mechanic='statement_path')
        sources=[('start','START - A: The fictional museum opened in 1985. If factual, go to B; if opinion, go to D.'),
                 ('floor','B: Exhibits span three floors. If factual, go to C; if opinion, go to D.'),
                 ('ticket','C: Admission costs ten dollars. If factual, go to E; if opinion, go to D.'),
                 ('opinion','D: The museum has the best gift shop. Return to START.'),
                 ('exit','E - FINISH: The gift shop is on the left.')]
        page['exercise'].update(goal=raw['page']['exercise']['goal'],
            directions='Fictional museum challenge: begin at A and follow verifiable factual checkpoints to FINISH.',
            stimuli=[{'id':sid,'text':text} for sid,text in sources],
            questions=[{'id':'1','prompt':'Record the fact-only route from START to FINISH.',
                        'answer':'A, B, C, E.','space_mm':12},deepcopy(raw['page']['exercise']['questions'][0])])
        page['images']=deepcopy(raw['page']['images'])
        page['html']=('<h1 data-content="title" style="color:#167E80;background-color:#EAF5F2;padding:2mm"></h1>'
            '<p data-content="name"></p><p data-content="directions"></p>'+
            ''.join(f'<p data-content="stimulus_{sid}" style="margin:0 0 1mm;padding:1mm;border:0.3mm solid #167E80"></p>' for sid,_ in sources)+
            '<img data-asset="owl_reporter" style="width:92mm;height:92mm"/>'
            '<div data-content="question_1"></div><div data-content="question_2"></div>')
        return page

    def test_corrected_authored_path_prints_all_checkpoints_and_both_responses_both_grades(self):
        """The replacement has printed branches and a route key, not a mislabeled star diagram."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.statement_page();original=deepcopy(page)
                result=self.ask_once(page,self.profile(band),self.diagnostic()['title'],
                    {'render_mode':'authored','mechanic':'statement_path'})
                self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(result['html'].count('data-asset="owl_reporter"'),1)
                self.assertNotIn('data-visual',result['html'])
                for card in original['exercise']['stimuli']: self.assertIn(card['text'],result['html'])
                for height in (12,22): self.assertIn(f'height:{height}mm',result['html'])
                self.assertEqual(page,original)

    def exact_page_with_art(self,referenced=False):
        """Supply a legitimate geometric puzzle with a retained owl manifest and small SVG labels."""
        page=exact_page(visual_examples()[4])
        page['html']=page['html'].replace('width:175mm;height:150mm','width:140mm;height:95mm')
        page['exercise']['captions']=[{'id':'heading','text':'Museum Navigator'},
            {'id':'fact','text':'Maps show the position of rooms.'}]
        page['exercise']['questions']=[{'id':'2','prompt':'Describe one way a map helps a museum visitor.',
            'answer':'Accept an example of using a map to locate a room.','space_mm':22}]
        page['html']+='<p data-content="caption_heading"></p><p data-content="caption_fact"></p><div data-content="question_2"></div>'
        page['images']=deepcopy(self.diagnostic()['page']['images'])
        if referenced: page['html']+='<img data-asset="owl_reporter" style="width:42mm;height:42mm"/>'
        return page

    def test_authored_path_cannot_use_ai_pixels_or_omit_its_printed_source_cards(self):
        """The authored exception to the maze gate requires an actual printed text route."""
        for missing_sources in (False,True):
            page=self.statement_page();config=self.profile('3rd-4th')
            if missing_sources:
                page['exercise']['stimuli']=[]
                import re
                page['html']=re.sub(r'<p data-content="stimulus_[^"]+"[^>]*></p>','',page['html'])
            else:
                page['exercise']['questions'][0]['prompt']='Follow the fact-only route in the owl illustration.'
            with self.assertRaisesRegex(ValueError,'Statement-path task needs complete printed source cards'):
                validate_design(page,12,quality=config,expected_title=self.diagnostic()['title'],require_coherent=True)

    def test_valid_exact_puzzle_retains_every_image_and_readable_label_after_one_response(self):
        """Both small-label and missing-art errors recover without another provider rewrite."""
        for band in ('3rd-4th','5th-6th'):
            for referenced in (False,True):
                with self.subTest(band=band,referenced=referenced):
                    page=self.exact_page_with_art(referenced);original=deepcopy(page)
                    result=self.ask_once(page,self.profile(band),'Museum Navigator',
                        {'render_mode':'exact','mechanic':'maze'})
                    for field in ('visual','questions','captions','goal'):
                        self.assertEqual(result['exercise'][field],original['exercise'][field])
                    self.assertEqual(result['images'],original['images'])
                    for field,value in (('data-asset','owl_reporter'),('data-visual','trail')):
                        self.assertEqual(result['html'].count(f'{field}="{value}"'),1)
                    self.assertIn('height:22mm',result['html'])
                    self.assertEqual(page,original)

    def test_art_recovery_refuses_unknown_wording_duplicates_and_independent_work_panels(self):
        """A missing image cannot justify hiding text or deleting existing writing surfaces."""
        for extra in ('<p>Write a new unkeyed answer.</p>',
                      '<div style="height:10mm;border:1mm solid #167E80"></div>',
                      '<img data-asset="owl_reporter" style="width:42mm;height:42mm"/>'):
            page=self.exact_page_with_art(True);page['html']+=extra
            config=self.profile('3rd-4th');page['_recovery_config']=config;page['_recovery_title']='Museum Navigator'
            self.assertIsNone(exact_artwork_layout(page,12,8000))

    def test_single_bullet_is_retained_but_unbound_words_and_symbol_sequences_still_fail(self):
        """A formatting marker needs no fictional caption; substantive text remains canonical."""
        parser=BoundLayout({'title':'Title'});parser.feed('<span>•</span>');parser.close()
        self.assertIn('•',''.join(parser.parts))
        for value in ('• Make a new answer.','••','A B C'):
            with self.assertRaisesRegex(ValueError,'Put ALL printed wording'):
                parser=BoundLayout({'title':'Title'});parser.feed('<span>'+value+'</span>')
