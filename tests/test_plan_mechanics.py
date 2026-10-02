"""Recover planner vocabulary without discarding precise educational checks."""
from copy import deepcopy
import unittest

from core.creative_generator import validate_plan, validate_design
from core.page_contract import validate_brief
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page, exact_page, visual_examples


def plan_for(mechanics, mode='exact', goals=None):
    """Build distinct briefs for testing mechanic-level repetition rules."""
    return dict(title='Creative Challenges', overview='Original tasks', art_direction='Colorful panels',
                character_description='Friendly objects', cover_brief='Bright cover',
                pages=[dict(title=f'Task {i}', learning_goal=(goals or ['Reason']*len(mechanics))[i],
                            activity_concept=f'Original concept {i}', layout_brief=f'Composition {i}',
                            render_mode=mode, mechanic=mechanic) for i,mechanic in enumerate(mechanics)])


class PlannerMechanicTests(unittest.TestCase):
    """Preserve intended tools and permit genuinely different open activities."""

    def test_common_aliases_normalize_without_mutating_input(self):
        """Usual model synonyms should not cost another generation attempt."""
        raw=plan_for(['Counting','picture-sorting','Pattern Completion','spot the differences'])
        original=deepcopy(raw)
        result=validate_plan(raw,4,require_coherent=True)
        self.assertEqual([p['mechanic'] for p in result['pages']],['count','sort','pattern','differences'])
        self.assertEqual(raw,original)

    def test_open_tasks_recover_authored_mode_and_keep_concepts(self):
        """A mislabeled craft is still the same craft after normalization."""
        raw=plan_for(['drawing','coloring','craft','collage'])
        result=validate_plan(raw,4,require_coherent=True)
        for source,page in zip(raw['pages'],result['pages']):
            self.assertEqual(page['render_mode'],'authored')
            for key in ('title','learning_goal','activity_concept','layout_brief'):
                self.assertEqual(page[key],source[key])

    def test_distinct_authored_drawings_can_share_label(self):
        """Broad creativity labels are not evidence of duplicate student work."""
        self.assertEqual(len(validate_plan(plan_for(['drawing']*4,'authored'),4,require_coherent=True)['pages']),4)

    def test_repetition_checks_exact_goal_after_alias_normalization(self):
        """Synonyms cannot conceal three copies of the same exact objective."""
        with self.assertRaisesRegex(ValueError,'same exercise mechanic and learning goal'):
            validate_plan(plan_for(['sort','sorting','picture_sorting']),3,require_coherent=True)
        result=validate_plan(plan_for(['count']*3,goals=['Count to five','Group by tens','Compare quantities']),3,require_coherent=True)
        self.assertEqual(len(result['pages']),3)

    def test_unknown_closed_puzzle_remains_rejected(self):
        """A jigsaw cannot become decorative art with an invented answer."""
        with self.assertRaisesRegex(ValueError,'Unsupported exact mechanic'):
            validate_plan(plan_for(['jigsaw']),1,require_coherent=True)

    def test_matching_alias_preserves_precise_rule_in_printed_page(self):
        """Shadow matching fills its mode from the declared alias and still computes its key."""
        brief=dict(render_mode=' EXACT ',mechanic='Shadow Matching')
        validate_brief(brief,planning=True)
        self.assertEqual(brief['mechanic_constraints'],{'mode':'shadow'})
        spec=visual_examples()[1];spec['kind']='shadow_matching';spec.pop('mode')
        raw=exact_page(spec)
        page=validate_design(raw,15,quality=load_grade_config()['Pre-K-K'],
                             expected_title='Shadow Challenge',require_coherent=True,brief=brief)
        self.assertEqual(page['visuals'][0]['kind'],'matching')
        self.assertEqual(page['visuals'][0]['mode'],'shadow')
        self.assertEqual(page['exercise_binding']['status'],'bound')

    def test_alias_constraint_cannot_be_overridden_by_visual(self):
        """A planned shape sort must not silently become a color sort."""
        brief=dict(render_mode='exact',mechanic='shape sorting');validate_brief(brief,planning=True)
        spec=visual_examples()[5];spec['attribute']='color'
        with self.assertRaisesRegex(ValueError,'planned exact matching/sorting rule'):
            validate_design(exact_page(spec),15,quality=load_grade_config()['Pre-K-K'],
                            expected_title='Sort Challenge',require_coherent=True,brief=brief)

    def test_complete_open_design_recovers_without_dropping_visual(self):
        """Only complete open questions with no precise graphic can recover authored mode."""
        raw=authored_page(mechanic='drawing');raw['exercise']['render_mode']='exact'
        page=validate_design(raw,15,quality=load_grade_config()['Pre-K-K'],expected_title='Garden Design',require_coherent=True)
        self.assertEqual(page['exercise']['render_mode'],'authored')
        bad=deepcopy(raw);bad['exercise']['visual']=visual_examples()[0]
        with self.assertRaisesRegex(ValueError,'Unsupported exact mechanic'):
            validate_design(bad,15,quality=load_grade_config()['Pre-K-K'],expected_title='Garden Design',require_coherent=True)

    def test_malformed_constraints_fail_as_content_errors(self):
        """Reject mismatched or structured constraint values before repetition grouping."""
        for mechanic,constraints in [('count',{'mode':'shadow'}),('sort',{'attribute':['shape']}),
                                     ('matching',{'mode':'unknown'})]:
            with self.subTest(mechanic=mechanic),self.assertRaisesRegex(ValueError,'constraints'):
                validate_brief(dict(render_mode='exact',mechanic=mechanic,mechanic_constraints=constraints),planning=True)
