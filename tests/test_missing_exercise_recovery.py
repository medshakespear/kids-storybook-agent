"""Recover omitted shared task objects without dropping print or correctness checks."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, merge_exercise_repair, validate_design
from core.activity_generator import ActivityGenerationError
from core.pipeline import load_grade_config
from core.task_visuals import answer_text
from tests.coherent_fixtures import authored_page, exact_page, visual_examples


class MissingExerciseRecoveryTests(unittest.TestCase):
    """Regress four consecutive missing-exercise responses in the daily run."""

    def ask(self, responses):
        """Run mocked provider JSON through actual shared task and print validation."""
        api = Mock()
        api.chat.completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)), finish_reason='stop')]) for raw in responses]
        def validate(page):
            """Check complete lower-grade page content, artwork and printable dimensions."""
            return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                                   expected_title='Creative Garden',require_coherent=True)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result = ask_json(layout_contract(14,13,coherent=True),validate,'Activity design 1')
        return result,api

    def test_authored_exercise_only_repair_retains_original_assets_and_layout(self):
        """A compact task recovery cannot overwrite unrelated artwork or layout."""
        page = authored_page()
        exercise = page.pop('exercise')
        original = deepcopy(page)
        result,api = self.ask([page,{'exercise':exercise,'images':[], 'html':'<p>Wrong task</p>'}])
        self.assertEqual(result['exercise'],exercise)
        self.assertEqual(result['source_layout'],original['html'])
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(page,original)
        message = api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('Return ONLY {"exercise":{...}}',message)
        self.assertIn('"render_mode":"authored"',message)
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_exact_exercise_repair_still_computes_puzzle_and_key(self):
        """A missing specification is recoverable without generating inaccurate puzzle pixels."""
        page = exact_page(visual_examples()[3])
        exercise = page.pop('exercise')
        page['exercise'] = None
        result,api = self.ask([page,{'exercise':exercise}])
        self.assertEqual(result['exercise']['visual']['rows'],exercise['visual']['rows'])
        self.assertTrue(answer_text(result).startswith('1.'))
        self.assertEqual(result['images'],[])
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_null_repair_is_not_accepted_as_a_success(self):
        """Incomplete model replies remain bounded failures rather than blank worksheets."""
        page = authored_page(); page.pop('exercise')
        with self.assertRaisesRegex(ActivityGenerationError,'Exercise recovery must return'):
            self.ask([page,{'exercise':None},{'exercise':None},{'exercise':None}])

    def test_task_recovery_cannot_skip_math_validation(self):
        """Adding a schema object does not approve an incorrect calculation."""
        page = authored_page(); exercise = page.pop('exercise')
        question = exercise['questions'][0]
        question.update(prompt='Calculate 12 - 8',answer='20',calculation={'expression':'12+8','answer':20})
        repaired = merge_exercise_repair(page,{'exercise':exercise})
        with self.assertRaisesRegex(ValueError,'does not solve the printed arithmetic'):
            validate_design(repaired,14,quality=load_grade_config()['1st-2nd'],
                            expected_title='Creative Garden',require_coherent=True)

    def test_repair_rejects_non_object_exercise(self):
        """An encoded string or list is not treated as a canonical specification."""
        for exercise in (None,[], '{}',{}):
            with self.assertRaisesRegex(ValueError,'Exercise recovery must return'):
                merge_exercise_repair(authored_page(),{'exercise':exercise})


if __name__ == '__main__':
    unittest.main()
