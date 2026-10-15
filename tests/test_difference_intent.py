"""Distinguish written comparison tasks from exact picture-difference puzzles."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.difference_intent import requires_exact_differences
from core.exercise_quality import validate_exercises
from core.response_schemas import design_schema
from core.statement_path_repair import merge_repair
from tests import test_statement_path_repair as repairs
from tests import test_statement_maze_and_artwork as fixtures
from tests.coherent_fixtures import authored_page,exact_page,visual_examples


class DifferenceIntentTests(unittest.TestCase):
    """Retain full content and geometry checks; mock only provider responses."""

    def config(self,band):
        """Use the production mixed-activity profile for either active grade band."""
        return fixtures.StatementMazeAndArtworkTests().profile(band)

    def validate(self,page,band,*,title=None,brief=None):
        """Run shared-content binding and real A4 print preflight."""
        config=self.config(band)
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title=title or fixtures.StatementMazeAndArtworkTests().diagnostic()['title'],
            require_coherent=True,brief=brief)

    def test_missing_link_repair_does_not_turn_fact_comparison_into_picture_puzzle(self):
        """Replay missing links followed by 'find differences' in printed route instructions."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=repairs.StatementPathRepairTests().source_page()
                page['exercise']['directions']='Find differences between facts and opinions as you follow the printed route.'
                endpoints=repairs.StatementPathRepairTests().route_update(page)
                endpoints['exercise']['captions']=endpoints['exercise']['captions'][:2]
                page=merge_repair(page,endpoints);original=deepcopy(page)
                with self.assertRaisesRegex(ValueError,'Print explicit next-step links'):
                    self.validate(page,band)
                correction=repairs.StatementPathRepairTests().route_update(page)
                api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(value)),finish_reason='stop')]) for value in (page,correction)]
                config=self.config(band);brief={'render_mode':'authored','mechanic':'statement_path'}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:self.validate(raw,band,brief=brief),'Activity design 1',
                        response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,2)
                for field in ('questions','stimuli','directions','goal'):
                    self.assertEqual(result['exercise'][field],original['exercise'][field])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('A: factual → B',result['html'])
                for height in (12,22): self.assertIn(f'height:{height}mm',result['html'])
                self.assertEqual(page,original)

    def test_text_comparison_is_valid_outside_statement_paths_in_both_grades(self):
        """The distinction applies to written comparison tasks across active grades."""
        for band in ('3rd-4th','5th-6th'):
            for instruction in ('Find the differences between the two written claims.',
                                'Spot the differences in wording between facts and opinions.',
                                'Circle the difference between the two passages.'):
                page=authored_page(mechanic='compare_claims')
                page['exercise']['directions']=instruction
                page['exercise']['passage']='Card A: The fictional museum opened in 1985. Card B: The museum is the best place to visit.'
                page['exercise']['questions'][0].update(prompt='Explain one difference between Card A and Card B.',
                    answer='A is a checkable factual statement. B expresses a personal opinion.',space_mm=30)
                page['images'][0]['prompt']='A fictional museum entrance and visitor information desk. Original welcoming illustration, no text or numbers.'
                page['html']=page['html'].replace('<img data-asset="scene"','<p data-content="passage"></p><img data-asset="scene"')
                page['html']=page['html'].replace('width:175mm;height:75mm','width:92mm;height:92mm')
                result=self.validate(page,band,title='Written Claim Comparison')
                self.assertEqual(result['exercise']['directions'],instruction)
                self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])

    def test_route_repair_cannot_replace_the_original_task_directions(self):
        """Adopt valid route cards while ignoring a replacement picture puzzle or other new task."""
        page=repairs.StatementPathRepairTests().source_page();original=deepcopy(page)
        for directions in ('Spot five differences between the two pictures.',
                           'Invent a different activity with new questions.'):
            correction=repairs.StatementPathRepairTests().route_update(page)
            correction['exercise']['directions']=directions
            repaired=merge_repair(page,correction)
            self.assertEqual(repaired['exercise']['directions'],original['exercise']['directions'])
            for band in ('3rd-4th','5th-6th'): self.validate(repaired,band)
        correction=repairs.StatementPathRepairTests().route_update(page)
        correction['exercise']['directions']=page['exercise']['directions']+' Begin at A; finish at E.'
        self.assertEqual(merge_repair(page,correction)['exercise']['directions'],correction['exercise']['directions'])
        self.assertEqual(page,original)

    def test_picture_puzzles_still_require_exact_rows_even_on_a_valid_statement_path(self):
        """A statement-path label is not an exemption for a second unsupported closed puzzle."""
        for band in ('3rd-4th','5th-6th'):
            for instruction in ('Find the 5 differences in these two rows.',
                                'Spot the differences between the two pictures of factual statements.',
                                'Find differences and explain your opinion.',
                                'Circle the differences in the scenes. Compare the written facts.'):
                page=fixtures.StatementMazeAndArtworkTests().statement_page()
                page['exercise']['questions'][1]['prompt']=instruction
                with self.assertRaisesRegex(ValueError,'Spot-the-difference tasks require an exact'):
                    self.validate(page,band)

    def test_image_briefs_and_unrelated_fields_are_not_student_instructions(self):
        """Neither invisible artwork instructions nor cross-field word adjacency creates a task."""
        for band in ('3rd-4th','5th-6th'):
            page=fixtures.StatementMazeAndArtworkTests().statement_page()
            page['images'][0]['prompt']='Find five differences between the pictures of museum visitors. No printed text.'
            self.validate(page,band)
        page={'exercise_binding':True,'exercise':{'directions':'Find the route.',
            'questions':[{'prompt':'Discuss differences between facts and opinions.'}]},
            'images':[{'id':'scene','prompt':'Spot the differences in these two rows.'}],
            'html':'<img data-asset="scene"><p>Find the route.</p>'}
        self.assertFalse(requires_exact_differences(page))
        legacy={'html':'<p>Find the route.</p><p>Differences in wording matter.</p>',
            'images':[{'id':'scene','prompt':'Spot the differences between pictures.'}]}
        self.assertFalse(requires_exact_differences(legacy))

    def test_numeric_differences_are_not_picture_puzzles(self):
        """Integer and decimal arithmetic retain their existing numerical checks."""
        for wording in ('Find the difference between 14 and 8.',
                        'Find the difference between 12.5 and 7.25.'):
            self.assertFalse(requires_exact_differences({'html':'<p>'+wording+'</p>'}))
        for band in ('3rd-4th','5th-6th'):
            page=authored_page();page['exercise']['questions'][0].update(
                prompt='Find the difference between 14 and 8.',answer='7',
                calculation={'expression':'14-8','answer':'7'})
            with self.assertRaisesRegex(ValueError,'declared math answer is incorrect'):
                self.validate(page,band,title='Difference Practice')

    def test_exact_difference_components_and_legacy_missing_components_remain_checked(self):
        """Genuine computed puzzles pass, while a generic picture puzzle still cannot use AI art."""
        for band in ('3rd-4th','5th-6th'):
            self.validate(exact_page(visual_examples()[-1]),band,title='Picture Changes')
            with self.assertRaisesRegex(ValueError,'Spot-the-difference'):
                validate_exercises({'html':'<p>Spot the differences.</p>','images':[]},self.config(band))
