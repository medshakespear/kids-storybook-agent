"""Regression checks for age-accessible writing, balanced keys and richer print layouts."""
from collections import Counter
from copy import deepcopy
import unittest
from unittest.mock import patch

from core.pipeline import load_grade_config
from core.reading_generator import (balance_answer_positions, passage_quality_issues,
                                    repair_unit_quality, render_unit)
from core.creative_layout import answer_key_markup
from tests.test_reading_generator import reading_fixture


class ReadingProductQualityTests(unittest.TestCase):
    """Exercise repair boundaries and canonical content alignment without paid APIs."""

    def test_accessibility_signal_accepts_concrete_grade_readings(self):
        """Healthy text does not incur another model call."""
        for band in ('3rd-4th', '5th-6th'):
            unit = reading_fixture(band)
            config = load_grade_config()[band]
            self.assertEqual(passage_quality_issues(unit, config), [])
            with patch('core.reading_generator.ask_json') as ask:
                self.assertEqual(repair_unit_quality(unit, config, 'Test'), unit)
                ask.assert_not_called()

    def test_vague_research_claim_triggers_scoped_passage_rewrite(self):
        """A repair may change paragraphs, never silently replace questions or artwork."""
        original = reading_fixture()
        flagged = deepcopy(original)
        flagged['paragraphs'][0] += ' Researchers found that gardens improve every school.'
        self.assertTrue(passage_quality_issues(flagged, load_grade_config()['3rd-4th']))
        def ask(prompt, validate, *args, **kwargs):
            """Supply a clean passage through the real scoped validator."""
            return validate({'paragraphs': original['paragraphs']})
        with patch('core.reading_generator.ask_json', side_effect=ask):
            repaired = repair_unit_quality(flagged, load_grade_config()['3rd-4th'], 'Test')
        self.assertEqual(repaired, original)
        self.assertEqual(flagged['questions'], original['questions'])

    def test_absolute_safety_and_unlabeled_town_examples_are_flagged(self):
        """Catch the concrete editorial defects seen in a generated Halloween pack."""
        config = load_grade_config()['3rd-4th']
        for extra in ('This completely eliminates the risk of accidental fires.',
                      'The town of Oak Creek tested lights that lasted fifty hours.'):
            unit = reading_fixture()
            unit['paragraphs'][0] += ' '+extra
            self.assertTrue(passage_quality_issues(unit, config))
        labeled = reading_fixture()
        labeled['paragraphs'][0] += ' Imagine the fictional town of Oak Creek planning a festival.'
        self.assertEqual(passage_quality_issues(labeled, config), [])

    def test_answer_relabeling_preserves_correct_text_and_balances_all_units(self):
        """All choices remain intact and the canonical answer always follows its text."""
        answers = []
        for index in range(5):
            original = reading_fixture()
            revised = balance_answer_positions(original, index)
            for before, after in zip(original['questions'], revised['questions']):
                self.assertEqual(before['options'][before['answer']], after['options'][after['answer']])
                self.assertEqual(set(before['options'].values()), set(after['options'].values()))
                self.assertEqual(before['evidence'], after['evidence'])
                answers.append(after['answer'])
        self.assertEqual(sorted(Counter(answers).values()), [6, 6, 6, 7])
        self.assertEqual(reading_fixture()['questions'][0]['answer'], 'B')

    def test_art_is_square_and_key_has_one_row_per_question(self):
        """A square scene keeps its composition; key rows come from the same questions."""
        for band, size in (('3rd-4th', 86), ('5th-6th', 76)):
            unit = reading_fixture(band)
            reading, quiz = render_unit(unit, 1, load_grade_config()[band])
            self.assertIn(f'width:{size}mm;height:{size}mm', reading['html'])
            self.assertIn('Read with a purpose', reading['html'])
            self.assertIn('border-bottom:1mm solid', reading['html'])
            self.assertIn('background-color:'+load_grade_config()[band]['alternate_wash'],quiz['html'])
            self.assertEqual(len(quiz['answer_items']), 5)
            key = answer_key_markup({'content_format': 'reading_qcm', 'pages': [reading, quiz]})
            self.assertEqual(key.count('<strong>'), 5)
            for i, question in enumerate(unit['questions'], 1):
                self.assertIn(f'{i}. {question["answer"]}:</strong>', key)
                self.assertNotIn(question['explanation'], reading['html'])
                self.assertNotIn(question['explanation'], quiz['html'])


if __name__ == '__main__':
    unittest.main()
