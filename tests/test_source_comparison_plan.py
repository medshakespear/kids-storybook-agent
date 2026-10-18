"""Written-source comparisons must survive planning without admitting picture puzzles."""
from copy import deepcopy
import unittest

from core.creative_generator import validate_plan
from core.simple_exercises import check_simple_activity
from tests.test_book_types import mixed_plan


class SourceComparisonPlanTests(unittest.TestCase):
    """Exercise the production planner and the shared student-instruction guard."""

    def test_source_comparison_page_nine_is_not_a_picture_puzzle(self):
        """Sources need not already be authored for an explicit written comparison plan."""
        for concept in (
            'Identify similarities and differences using two printed written sources.',
            'Read two accounts. Identify similarities and differences.',
            'Compare two sources and list differences in their perspectives.',
            'Compare two written cards. Spot differences between Card A and Card B.',
        ):
            with self.subTest(concept=concept):
                plan=mixed_plan()
                plan['pages'][8].update(title='Source Comparison',render_mode='authored',
                    mechanic='compare_sources',learning_goal='Compare written evidence.',activity_concept=concept)
                original=deepcopy(plan)
                result=validate_plan(plan,10,require_coherent=True,require_variety=True,
                    student_workbook=True,simple_exercises_only=True)
                self.assertEqual(result['pages'][8]['activity_concept'],concept)
                self.assertEqual(plan,original)

    def test_real_picture_tasks_still_fail_despite_source_context(self):
        """A source-comparison title or nearby reading cannot excuse an image puzzle."""
        for concept in (
            'Read two sources. Spot differences between the two pictures.',
            'Compare written sources and find differences in these two rows.',
            'Find differences between two pictures of written sources.',
            'Read two accounts. Spot differences in shapes.',
            'Spot the differences.',
        ):
            with self.subTest(concept=concept),self.assertRaisesRegex(ValueError,'picture spot-the-difference'):
                check_simple_activity(dict(title='Source Comparison',render_mode='authored',
                    mechanic='compare_sources',activity_concept=concept),planning=True)

    def test_planner_fields_cannot_create_a_command_by_concatenation(self):
        """An incomplete goal and independent concept are not a spot-difference command."""
        check_simple_activity(dict(render_mode='authored',mechanic='compare_sources',
            learning_goal='Identify',activity_concept='Differences between sources support discussion.'),planning=True)
        with self.assertRaisesRegex(ValueError,'picture spot-the-difference'):
            check_simple_activity(dict(render_mode='authored',mechanic='compare_sources',
                learning_goal='Read two sources.',activity_concept='Spot differences.'),planning=True)

    def test_printed_source_comparison_uses_the_same_rule(self):
        """Authored instructions retain explicit written intent before source binding."""
        check_simple_activity(dict(render_mode='authored',mechanic='compare_sources',
            directions='Read both passages. Identify similarities and differences.',questions=[]))
