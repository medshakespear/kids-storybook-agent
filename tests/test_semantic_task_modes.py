"""Select authored modes for semantic tasks and resolve explicit card-prefix mistakes."""
from copy import deepcopy
import unittest

from core.content_binding import canonical_content_slot
from core.creative_generator import validate_design
from core.page_contract import validate_brief
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class SemanticTaskModeTests(unittest.TestCase):
    """Keep real picture puzzles exact and preserve every explicitly supplied statement."""

    def test_fact_opinion_sort_is_authored_before_schema_selection(self):
        """Only tool metadata changes; Gemini retains the intended sorting exercise."""
        brief={'render_mode':'exact','mechanic':'sort','learning_goal':'Distinguish facts from opinions.',
               'activity_concept':'Sort four museum statements under fact or opinion.',
               'layout_brief':'Use two colored statement columns.','mechanic_constraints':{'attribute':'shape'}}
        original=deepcopy(brief);validate_brief(brief,planning=True)
        self.assertEqual(brief['render_mode'],'authored')
        self.assertEqual(brief['mechanic'],'sort')
        self.assertNotIn('mechanic_constraints',brief)
        for field in ('learning_goal','activity_concept','layout_brief'):
            self.assertEqual(brief[field],original[field])
        for band in ('3rd-4th','5th-6th'):
            schema=design_schema(brief,dict(load_grade_config()[band],stimulus_limit=8))
            self.assertEqual(schema['properties']['exercise']['properties']['render_mode']['enum'],['authored'])
            self.assertNotIn('visual',schema['properties']['exercise']['properties'])

    def test_claim_and_definition_matching_use_authored_tools(self):
        """Source-to-meaning matching cannot be rendered by a picture/shadow generator."""
        for goal in ('Match visitor claims to objective measurement records.',
                     'Match vocabulary terms to their definitions.'):
            with self.subTest(goal=goal):
                brief={'render_mode':'exact','mechanic':'matching','learning_goal':goal,
                       'activity_concept':goal,'layout_brief':'Arrange the text cards in columns.'}
                validate_brief(brief,planning=True)
                self.assertEqual(brief['render_mode'],'authored')

    def test_source_card_sorting_works_with_a_broad_learning_goal(self):
        """Explicit textual student actions select authored mode even without named categories."""
        brief={'render_mode':'exact','mechanic':'sort','learning_goal':'Practice critical reasoning.',
               'activity_concept':'Sort four museum statements into two categories.',
               'layout_brief':'Create Fact and Opinion columns.'}
        validate_brief(brief,planning=True)
        self.assertEqual(brief['render_mode'],'authored')

    def test_real_visual_tasks_and_completed_diagrams_are_not_replaced(self):
        """Ordinary shape sorting remains computed and generated diagrams are never discarded."""
        brief={'render_mode':'exact','mechanic':'sort','learning_goal':'Sort shapes by color.',
               'activity_concept':'Group bright shapes into two disjoint color groups.',
               'layout_brief':'Use large picture tokens.','mechanic_constraints':{'attribute':'color'}}
        original=deepcopy(brief);validate_brief(brief,planning=True)
        self.assertEqual(brief,original)
        brief['activity_concept']='Group shapes by color. Discuss facts and opinions as an optional extension.'
        validate_brief(brief,planning=True)
        self.assertEqual(brief['render_mode'],'exact')
        finished={'render_mode':'exact','mechanic':'sort','goal':'Facts and opinions.',
                  'visual':{'kind':'sort'}}
        validate_brief(finished)
        self.assertEqual(finished['render_mode'],'exact')
        self.assertIn('visual',finished)

    def test_declared_caption_cards_accept_a_mistaken_source_prefix(self):
        """Only existing unique card text can resolve the wrong slot namespace."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page(mechanic='sort')
                page['exercise'].update(directions='Sort each supplied statement as fact or opinion.',stimuli=[],
                    captions=[{'id':'fact_card_1','text':'The fictional museum opens at 9 am.'},
                              {'id':'opinion_card_1','text':'The fictional museum is the most exciting place.'}])
                page['exercise']['questions'][0].update(prompt='Label each statement fact or opinion. Explain one choice.',
                    answer='fact_card_1: fact; opinion_card_1: opinion. Accept an explanation of checkability or preference.',space_mm=25)
                page['html']=page['html'].replace('<p data-content="directions"></p>',
                    '<p data-content="directions"></p><p data-content="stimulus_fact_card_1"></p>'
                    '<p data-content="stimulus_opinion_card_1"></p>')
                original=deepcopy(page);config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                    context_caption_limit=24,stimulus_limit=8,items_per_page=2)
                result=validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Fact or Opinion Studio',require_coherent=True)
                self.assertEqual(result['exercise'],original['exercise'])
                for card in original['exercise']['captions']:
                    self.assertEqual(result['html'].count(card['text']),1)
                self.assertEqual(page,original)

    def test_unknown_ambiguous_and_real_source_slots_keep_their_identity(self):
        """Do not substitute a label for missing evidence or override an actual source."""
        self.assertEqual(canonical_content_slot('stimulus_fact_card_1',{'caption_fact_card_1':'Given text'}),
                         'caption_fact_card_1')
        self.assertEqual(canonical_content_slot('stimulus_missing',{'caption_other':'Other'}),'stimulus_missing')
        self.assertEqual(canonical_content_slot('stimulus_a',{'caption_a':'A','caption_stimulus_a':'Different'}),'stimulus_a')
        self.assertEqual(canonical_content_slot('stimulus_a',{'stimulus_a':'Source','caption_a':'Label'}),'stimulus_a')
