"""Regression checks for age-accessible writing, balanced keys and richer print layouts."""
from collections import Counter
from copy import deepcopy
import unittest
from unittest.mock import patch

from core.pipeline import load_grade_config
from core.reading_generator import (balance_answer_positions, passage_quality_issues,
                                    repair_unit_quality, render_unit, render_cover, workbook_colors)
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

    def test_cover_uses_large_art_and_short_text_at_print_bounds(self):
        """The maximum cover copy and larger image fit beside the required store logo."""
        from core.creative_layout import check_page
        for band in ('3rd-4th','5th-6th'):
            config = load_grade_config()[band]
            plan = {'title':'Discover the World Through Close Reading and Ideas'[:52],
                    'overview':'Explore original themed texts, build vocabulary, and practise making thoughtful choices with passage evidence.'[:110]}
            page = render_cover(plan,band,config,5)
            check_page(page,config['student_font_pt'],cover=True)
            self.assertIn('height:160mm',page['html'])
            self.assertIn('5 readings',page['html'])
            self.assertIn('Answer key',page['html'])

    def test_cover_has_curved_background_and_no_description(self):
        """Cover decoration is trusted SVG and the overview never prints."""
        from core.creative_layout import cover_fragment, document_markup, check_document, data_only_fetcher
        from weasyprint import HTML
        plan = {'title':'Stand Up Together', 'overview':'THIS DESCRIPTION MUST NOT PRINT', 'topics':['Children playing outdoors.']}
        config = load_grade_config()['3rd-4th']
        page = render_cover(plan,'3rd-4th',config,5)
        markup = document_markup([cover_fragment(page,True)],config['student_font_pt'])
        self.assertNotIn(plan['overview'],markup)
        self.assertIn('reading-cover',markup)
        self.assertIn('data:image/svg+xml;base64,',markup)
        check_document(HTML(string=markup,url_fetcher=data_only_fetcher).render(),1)

    def test_answer_schedule_has_no_runs_and_varied_pages(self):
        """Keys stay balanced while every complete set has at least three letters."""
        import random
        from core.reading_generator import answer_position_schedule
        for seed in range(50):
            schedule=answer_position_schedule(25,random.Random(seed))
            self.assertEqual(sorted(Counter(schedule).values()),[6,6,6,7])
            self.assertTrue(all(len(set(schedule[i:i+5]))>=3 for i in range(0,25,5)))
            self.assertFalse(any(schedule[i]==schedule[i+1]==schedule[i+2] for i in range(23)))

    def test_scene_removes_text_prone_display_requests(self):
        """Keep scene context while replacing surfaces that invite garbled lettering."""
        from core.reading_generator import illustration_scene
        scene=illustration_scene('Two friends beside colorful posters and a chalkboard in a classroom.')
        self.assertIn('Two friends',scene)
        self.assertIn('plain undecorated surfaces',scene)
        self.assertNotIn('colorful posters',scene)
        self.assertNotIn('a chalkboard',scene)

    def test_bullying_definitions_and_report_prerequisites_trigger_repair(self):
        """Repeated behavior is not mandatory and evidence cannot delay adult help."""
        config=load_grade_config()['3rd-4th']
        for extra in ('Bullying must happen repeatedly over and over.',
                      'For bullying use a four-step plan: step one find a witness, step two write notes.'):
            unit=reading_fixture();unit['paragraphs'][0]+=' '+extra
            self.assertTrue(passage_quality_issues(unit,config))

    def test_safe_optional_documentation_is_not_a_reporting_prerequisite(self):
        """Numbered safe plans and explicit prohibitions do not force another rewrite."""
        config = load_grade_config()['3rd-4th']
        for extra in (
            'Bullying can happen again. Use a three-step plan. Step one tell a trusted adult promptly. '
            'Step two take notes only if safe. Notes are optional after seeking help.',
            'Bullying can happen again. Never collect evidence before reporting. Tell an adult promptly.',
        ):
            unit = reading_fixture()
            unit['paragraphs'][0] += ' '+extra
            self.assertEqual(passage_quality_issues(unit, config), [])
        unsafe = reading_fixture()
        unsafe['paragraphs'][0] += (' Bullying can happen again. First collect evidence before reporting. '
                                  'You can also tell an adult.')
        self.assertTrue(passage_quality_issues(unsafe, config))

    def test_short_accessible_rewrite_expands_without_another_rewrite(self):
        """Both bands retain the corrected wording while a separate addition restores length."""
        for band in ('3rd-4th', '5th-6th'):
            with self.subTest(band=band):
                original = reading_fixture(band)
                flagged = deepcopy(original)
                flagged['paragraphs'][0] += ' Researchers found that gardens improve every school.'
                short = [' '.join(p.split()[:62]) for p in reading_fixture()['paragraphs']]
                def ask(prompt, validate, *args, **kwargs):
                    """Return a substantive short rewrite through the real validator."""
                    return validate({'paragraphs': short})
                with patch('core.reading_generator.ask_json', side_effect=ask) as request, \
                     patch('core.reading_generator.expand_short_passage', return_value=original['paragraphs']) as expand:
                    repaired = repair_unit_quality(flagged, load_grade_config()[band], 'Reading 3')
                self.assertEqual(request.call_count, 1)
                expand.assert_called_once()
                retained = expand.call_args.args[0]
                self.assertEqual(retained['questions'], flagged['questions'])
                self.assertEqual(repaired['paragraphs'], original['paragraphs'])
                self.assertEqual(flagged['paragraphs'][0], original['paragraphs'][0]+' Researchers found that gardens improve every school.')

    def test_accessibility_expansion_cannot_reintroduce_unsafe_advice(self):
        """The final expanded text is checked again before evidence or PDF generation."""
        from core.activity_generator import ActivityGenerationError
        original = reading_fixture()
        original['paragraphs'][0] += ' Researchers found that gardens improve every school.'
        short = [' '.join(p.split()[:62]) for p in reading_fixture()['paragraphs']]
        unsafe = reading_fixture()['paragraphs']
        unsafe[0] += ' Bullying can happen again. First collect evidence before reporting.'
        def ask(prompt, validate, *args, **kwargs):
            """Run the scoped validator for the safe intermediate draft."""
            return validate({'paragraphs': short})
        with patch('core.reading_generator.ask_json', side_effect=ask), \
             patch('core.reading_generator.expand_short_passage', return_value=unsafe):
            with self.assertRaisesRegex(ActivityGenerationError, 'accessibility expansion'):
                repair_unit_quality(original, load_grade_config()['3rd-4th'], 'Reading 3')

    def test_reading_pairs_have_distinct_coordinated_colors(self):
        """Five units vary their accent while upper-grade fills remain restrained."""
        config = load_grade_config()['3rd-4th']
        self.assertEqual(len({workbook_colors(config,n)[0] for n in range(1,6)}),5)
        self.assertEqual(workbook_colors(config,1),workbook_colors(config,6))

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
            self.assertIn('background-color:'+workbook_colors(load_grade_config()[band],1)[3],quiz['html'])
            self.assertEqual(len(quiz['answer_items']), 5)
            key = answer_key_markup({'content_format': 'reading_qcm', 'pages': [reading, quiz]})
            self.assertEqual(key.count('<strong>'), 5)
            for i, question in enumerate(unit['questions'], 1):
                self.assertIn(f'{i}. {question["answer"]}:</strong>', key)
                self.assertNotIn(question['explanation'], reading['html'])
                self.assertNotIn(question['explanation'], quiz['html'])


if __name__ == '__main__':
    unittest.main()
