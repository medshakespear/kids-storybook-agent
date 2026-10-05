"""Regress exact fractional results and saturated-caption diagram binding."""
from copy import deepcopy
import unittest
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from core.content_binding import validate_caption_budget
from core.creative_generator import validate_design, merge_layout_repair, ask_json, layout_contract
from core.math_result_recovery import repair_declared_result
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class BeltResultRecoveryTests(unittest.TestCase):
    """Preserve tasks and their arithmetic while repairing bounded metadata."""

    def page(self):
        """Build a small authored worksheet with the reported arithmetic and labels."""
        page = authored_page()
        page['exercise']['questions'] = [dict(id='3', prompt='Calculate 325 * 7 / 20.',
            answer='114 items from a batch of 325.', space_mm=25,
            calculation=dict(expression='325*7/20', answer=114))]
        page['html'] = page['html'].replace('question_1', 'question_3')
        page['exercise']['captions'] = [dict(id=f'context_{i}', text=f'Batch label {i}') for i in range(6)]
        page['html'] += '<table><tr>' + ''.join(
            f'<td data-content="caption_context_{i}"></td>' for i in range(6)) + '</tr></table>'
        page['html'] += '<p>Belt A</p>'
        return page

    def test_result_and_full_caption_manifest_for_both_active_bands(self):
        """The real print validator retains art, answers and response space for both bands."""
        original = self.page()
        for band in ['3rd-4th', '5th-6th']:
            with self.subTest(band=band):
                page = repair_declared_result(original, '3')
                result = validate_design(page, 12, quality=load_grade_config()[band],
                    expected_title='Garden Detectives', require_coherent=True)
                question = result['exercise']['questions'][0]
                self.assertEqual(question['answer'], '455/4 items from a batch of 325.')
                self.assertEqual(question['calculation']['answer'], '455/4')
                self.assertEqual(question['space_mm'], 25)
                self.assertEqual(result['images'], original['images'])
                self.assertEqual(len(result['exercise']['captions']), 7)
                self.assertIn('Belt A', result['html'])
        self.assertEqual(original, self.page())

    def test_arithmetic_then_overflow_recovers_without_another_provider_call(self):
        """Run the chained error through production retries and real print measurement."""
        for band in ['3rd-4th', '5th-6th']:
            with self.subTest(band=band):
                page = self.page()
                page['html'] = page['html'].replace('height:75mm', 'height:300mm')
                api = Mock()
                api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)), finish_reason='stop')])
                def validate(raw):
                    """Measure the worksheet against the selected grade requirements."""
                    return validate_design(raw, 12, quality=load_grade_config()[band],
                        expected_title='Garden Detectives', require_coherent=True)
                with patch('core.creative_generator.text_provider_names', return_value=['gemini']), \
                     patch('core.creative_generator.text_client', return_value=(api, 'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result = ask_json(layout_contract(12, 12, coherent=True), validate, 'Activity design 1',
                        response_schema=design_schema(dict(render_mode='authored', mechanic='design shelter'), load_grade_config()[band]))
                self.assertEqual(api.chat.completions.create.call_count, 1)
                self.assertEqual(result['exercise']['questions'][0]['answer'], '455/4 items from a batch of 325.')
                self.assertIn('Belt A', result['html'])
                self.assertEqual(result['images'], page['images'])
                self.assertEqual(result['exercise']['questions'][0]['space_mm'], 25)

    def test_layout_alias_uses_retained_marker_without_new_caption_data(self):
        """Resolve an empty caption_belt_a only from an existing, unique Belt A caption."""
        original = self.page()
        original['exercise']['captions'].append(dict(id='diagram_label_1', text='Belt A'))
        original['html'] = original['html'].replace('<p>Belt A</p>', '<p data-content="caption_diagram_label_1"></p>')
        correction = dict(html=original['html'].replace('caption_diagram_label_1', 'caption_belt_a'))
        result = merge_layout_repair(original, correction)
        self.assertIn('caption_diagram_label_1', result['html'])
        self.assertEqual(result['exercise'], original['exercise'])
        unknown = merge_layout_repair(original, dict(html='<p data-content="caption_belt_b"></p>'))
        self.assertIn('caption_belt_b', unknown['html'])

    def test_equation_key_keeps_the_operation_and_exact_fraction(self):
        """An explicit copy of the operation identifies its result without guessing prose."""
        page = self.page()
        page['exercise']['questions'][0]['answer'] = '325*7/20 = 114 items.'
        result = repair_declared_result(page, '3')
        self.assertEqual(result['exercise']['questions'][0]['answer'], '325*7/20 = 455/4 items.')
        page['exercise']['questions'][0]['answer'] = '325+7 = 114 items.'
        self.assertIsNone(repair_declared_result(page, '3'))

    def test_caption_budgets_remain_bounded(self):
        """Diagram exceptions cannot introduce unlimited prose or identifiers."""
        captions = self.page()['exercise']['captions']
        labels = [dict(id=f'belt_{i}', text=f'Belt {i}') for i in range(1, 9)]
        validate_caption_budget(captions + labels)
        for extra in [dict(id='context_extra', text='Another paragraph'), dict(id='belt_9', text='Belt 9')]:
            with self.assertRaises(ValueError):
                validate_caption_budget(captions + labels + [extra])


if __name__ == '__main__':
    unittest.main()
