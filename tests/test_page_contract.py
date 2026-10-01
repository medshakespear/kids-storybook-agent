"""Prove printed tasks, precise graphics and final answers cannot drift apart."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from core.creative_generator import validate_design, validate_plan, compact_answers, layout_contract
from core.page_contract import compile_exercise
from core.task_visuals import build_visual, answer_text, icon
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page, exact_page, visual_examples


class PageContractTests(unittest.TestCase):
    """Exercise shared content binding with actual print preflight and computed solutions."""

    def setUp(self):
        """Use the strictest young-reader layout limits."""
        self.config=load_grade_config()['Pre-K-K']

    def compile(self,page,title='Creative Challenge',brief=None):
        """Validate a complete production page without contacting providers."""
        return validate_design(page,15,quality=self.config,expected_title=title,require_coherent=True,brief=brief)

    def test_authored_task_and_answer_use_one_source(self):
        """Question wording is filled once and its criterion appears only in the key."""
        page=self.compile(authored_page())
        self.assertEqual(page['html'].count('Draw your shelter.'),1)
        self.assertNotIn('Accept a design',page['html'])
        self.assertIn('Accept a design',page['answers'])
        self.assertNotIn('data-content',page['html'])
        self.assertIn('height:45mm',page['html'])
        self.assertEqual(page['exercise_binding']['status'],'bound')

    def test_all_exact_mechanics_print_and_compute(self):
        """Every supported puzzle fits and supplies a key without a second AI answer draft."""
        for spec in visual_examples():
            with self.subTest(kind=spec['kind']):
                page=self.compile(exact_page(spec))
                self.assertTrue(answer_text(page).startswith('1.'))
                self.assertEqual(page['answers'],'')
                self.assertEqual(page['visuals'][0]['kind'],spec['kind'])
                self.assertEqual(page['exercise_binding']['mechanic'],spec['kind'])

    def test_plan_task_cannot_change_into_a_different_puzzle(self):
        """The observed pattern-to-maze substitution fails even when the maze itself is valid."""
        maze=visual_examples()[4]
        with self.assertRaisesRegex(ValueError,'planned render_mode and mechanic'):
            self.compile(exact_page(maze),brief={'render_mode':'exact','mechanic':'pattern'})

    def test_exact_graphic_cannot_have_unrelated_instructions(self):
        """Sorting plus seesaw wording is rejected rather than accepted as a printable page."""
        page=exact_page(visual_examples()[5]);page['exercise']['directions']='Look at the seesaws.'
        with self.assertRaisesRegex(ValueError,'verified directions'):
            self.compile(page)
        page=exact_page(visual_examples()[5]);page['html']='<p>Look at the seesaws.</p>'+page['html']
        with self.assertRaisesRegex(ValueError,'ALL printed wording'):
            self.compile(page)

    def test_exact_labels_stay_readable_at_actual_print_size(self):
        """A large empty canvas cannot hide a puzzle whose labels were scaled too small."""
        page=exact_page(visual_examples()[0])
        page['html']=page['html'].replace('width:175mm;height:150mm','width:120mm;height:150mm')
        with self.assertRaisesRegex(ValueError,'labels would be too small'):
            self.compile(page)

    def test_all_new_components_preserve_grade_print_boundaries(self):
        """The shared exercise format fits every grade with its own text floor."""
        for band,cfg in load_grade_config().items():
            for spec in visual_examples():
                with self.subTest(band=band,kind=spec['kind']):
                    page=validate_design(exact_page(spec),cfg['student_font_pt'],quality=cfg,
                                         expected_title='Visual Challenge',require_coherent=True)
                    self.assertEqual(page['exercise_binding']['status'],'bound')

    def test_legacy_parallel_key_cannot_override_shared_answer(self):
        """Invented Right/Left answers cannot silently join a computed sorting key."""
        page=exact_page(visual_examples()[5]);page['answers']='Right, Left, Right'
        with self.assertRaisesRegex(ValueError,'independent answers'):
            self.compile(page)

    def test_required_slots_and_media_are_used_once(self):
        """Missing or duplicated text/graphics are invalid, not silently repaired into other tasks."""
        base=authored_page()
        for html in [base['html'].replace('data-content="question_1"','data-content="question_2"'),
                     base['html']+'<p data-content="directions"></p>',
                     base['html']+'<img data-asset="scene" style="width:10mm;height:10mm"/>',
                     base['html'].replace('<p data-content="directions"></p>','')]:
            with self.subTest(html=html),self.assertRaises(ValueError):
                self.compile(dict(base,html=html))

    def test_closed_pixel_task_does_not_pass_as_authored(self):
        """A shadow answer cannot be guessed from an uncontrolled generated illustration."""
        page=authored_page();page['exercise']['directions']='Match the shadows in the illustration.'
        with self.assertRaisesRegex(ValueError,'Closed visual task'):
            self.compile(page)

    def test_text_reasoning_is_not_confused_with_pixel_dependence(self):
        """Supplied numerical comparisons stay creative authored tasks rather than image puzzles."""
        page=authored_page(mechanic='compare supplies')
        page['exercise']['directions']='Two bags weigh 3 kg and 7 kg. Which bag is heavier?'
        page['exercise']['questions'][0].update(prompt='Circle the heavier bag: 3 kg or 7 kg.',answer='The 7 kg bag.',space_mm=0)
        self.assertIn('7 kg',self.compile(page)['answers'])

    def test_math_prompt_result_and_key_agree(self):
        """Verify both prompt arithmetic and prose key independently of declared answer."""
        page=authored_page(mechanic='addition')
        page['exercise']['questions']=[dict(id='1',prompt='What is 4 + 3?',answer='7',space_mm=20,
                                           calculation=dict(expression='4+3',answer=7))]
        valid=self.compile(page)
        self.assertEqual(valid['calculations'][0]['answer'],7)
        for answer in ['17','A shelter.']:
            bad=deepcopy(page);bad['exercise']['questions'][0]['answer']=answer
            with self.subTest(answer=answer),self.assertRaisesRegex(ValueError,'answer key'):
                self.compile(bad)
        bad=deepcopy(page);bad['exercise']['questions'][0]['calculation']=dict(expression='4+4',answer=8)
        with self.assertRaisesRegex(ValueError,'printed arithmetic'):
            self.compile(bad)
        bad=deepcopy(page);del bad['exercise']['questions'][0]['calculation']
        with self.assertRaisesRegex(ValueError,'requires a calculation'):
            self.compile(bad)

    def test_fraction_and_multistep_math_use_correct_printed_answer(self):
        """Older-grade arithmetic keeps valid mixed-number keys and operation precedence."""
        config=load_grade_config()['5th-6th']
        for prompt,expression,answer,key in [('What is 4 + 3 * 2?','4+3*2',10,'10'),
                                            ('What is 3/4 + 5/8?','3/4+5/8','11/8','1 3/8')]:
            page=authored_page(mechanic='reason with arithmetic')
            page['exercise']['questions']=[dict(id='1',prompt=prompt,answer=key,space_mm=20,
                                               calculation=dict(expression=expression,answer=answer))]
            with self.subTest(expression=expression):
                validated=validate_design(page,11,quality=config,expected_title='Math Studio',require_coherent=True)
                self.assertIn(key,validated['answers'])

    def test_exact_answers_are_generated_from_actual_spec(self):
        """New visual components calculate real displayed choice, pair, size and count answers."""
        specs=visual_examples()
        self.assertEqual(build_visual(specs[0])[1],'1. Choice A.')
        self.assertEqual(build_visual(specs[2])[1],'1. 1: right; 2: left.')
        self.assertEqual(build_visual(specs[3])[1],'1. 1: 3; 2: 5; 3: 2.')
        svg,key=build_visual(specs[1])
        self.assertIn('matching shadows',svg)
        self.assertEqual(len(key.split(',')),3)
        self.assertNotIn('<g fill="#FFFFFF"',icon(dict(shape='ghost',color='black',size='large'),0,0,silhouette=True))

    def test_ambiguous_exact_components_fail(self):
        """Do not accept duplicate pattern choices, identical shadows or false weight inference."""
        pattern,matching,balance,*_=visual_examples()
        pattern['choices']=[pattern['motif'][-1]]*2
        matching['items']=[matching['items'][0]]*2
        balance['rows'][0]['right']=balance['rows'][0]['left']
        for spec in (pattern,matching,balance):
            with self.subTest(kind=spec['kind']),self.assertRaises(ValueError):
                build_visual(spec)

    def test_bound_key_never_gets_independent_condensation(self):
        """Preserve canonical criteria even if a legacy key shortener would have run."""
        page=self.compile(authored_page());page['answers']='x'*310
        with patch('core.creative_generator.ask_json') as ask:
            self.assertEqual(compact_answers(page,1),page)
        ask.assert_not_called()

    def test_production_prompt_has_only_one_content_contract(self):
        """Avoid simultaneously asking the model for incompatible old and new schemas."""
        prompt=layout_contract(15,14,coherent=True)
        self.assertIn('ONE shared source',prompt)
        self.assertIn('data-content',prompt)
        self.assertNotIn('Include calculations: []',prompt)
        self.assertIn('mechanic',prompt)

    def test_repetitive_mechanic_plan_is_rejected(self):
        """Distinct titles alone cannot hide three copies of the same student action."""
        plan=dict(title='Challenge',overview='Overview',art_direction='Bright',character_description='Objects',cover_brief='Cover',
                  pages=[dict(title=f'Task {i}',learning_goal='Reason',activity_concept=f'Concept {i}',
                              layout_brief=f'Layout {i}',render_mode='exact',mechanic='sort') for i in range(3)])
        with self.assertRaisesRegex(ValueError,'same exercise mechanic'):
            validate_plan(plan,3,require_coherent=True)
