"""Regression checks against the sparse and misleading Halloween student pages."""
import unittest
from copy import deepcopy
from core.activity_presentation import prepare_activity_presentation, activity_quality_guidance
from core.task_visuals import build_visual


class ActivityPresentationTests(unittest.TestCase):
    """Keep actual puzzle data, printed titles and computed answers aligned."""
    def setUp(self):
        """Create an intentionally sparse source page like the reported PDF."""
        self.symbol = {'shape': 'star', 'color': 'yellow', 'size': 'large'}
        self.config = {'student_font_pt': 15, 'max_operand': 10}
        self.brief = {'title': 'Count the Spooky Stars', 'render_mode': 'exact', 'mechanic': 'count'}
        self.page = {'html': '<p>draft</p>', 'images': [], 'exercise': {
            'render_mode': 'exact', 'mechanic': 'count', 'goal': 'Count within ten.',
            'visual': {'id': 'stars', 'question': 1, 'kind': 'count', 'rows': [[self.symbol] * 4]},
            'questions': [], 'captions': []}}

    def test_count_has_three_distinct_rows_and_computed_answers(self):
        """Extend practice while keeping every quantity and answer mechanically correct."""
        source = deepcopy(self.page)
        page, brief = prepare_activity_presentation(self.page, self.brief, self.config)
        rows = page['exercise']['visual']['rows']
        self.assertEqual([len(r) for r in rows], [4, 3, 5])
        svg, answer = build_visual(page['exercise']['visual'])
        self.assertIn('1: 4; 2: 3; 3: 5', answer)
        self.assertIn('Count the Stars', brief['title'])
        self.assertIn('width:175mm', page['html'])
        self.assertEqual(self.page, source)

    def test_title_describes_actual_pattern_and_differences(self):
        """Do not describe basic shapes as candy corn or changes as hidden objects."""
        for kind, title, visual in [
            ('pattern', 'Candy Corn Pattern Fun', {'motif': [self.symbol, {**self.symbol, 'shape': 'square'}],
                'choices': [self.symbol, {**self.symbol, 'shape': 'square'}]}),
            ('differences', 'Spot the Hidden Bats', {'items': [self.symbol] * 4,
                'changes': [{'index': 1, 'field': 'color', 'value': 'orange'}]})]:
            page = deepcopy(self.page)
            page['exercise']['mechanic'] = kind
            page['exercise']['visual'] = {'id': 'puzzle', 'question': 1, 'kind': kind, **visual}
            result, brief = prepare_activity_presentation(page, {'title': title, 'mechanic': kind}, self.config)
            self.assertNotEqual(brief['title'], title)
            self.assertEqual(result['title'], brief['title'])

    def test_additional_response_tasks_are_retained(self):
        """Composition cannot remove an extra student question or its workspace."""
        self.page['exercise']['questions'] = [{'id': '2', 'prompt': 'Draw your own star.',
                                             'answer': 'A star drawing.', 'space_mm': 40}]
        page, _ = prepare_activity_presentation(self.page, self.brief, self.config)
        self.assertEqual(page['exercise']['questions'], self.page['exercise']['questions'])
        self.assertIn('question_2', page['html'])

    def test_invalid_puzzles_still_need_repair(self):
        """Presentation must not cover up unsafe or unvalidated puzzle content."""
        self.page['exercise']['visual']['rows'] = [[]]
        page, brief = prepare_activity_presentation(self.page, self.brief, self.config)
        self.assertEqual(page, self.page)
        self.assertEqual(brief, self.brief)

    def test_authored_content_is_preserved_and_guidance_is_specific(self):
        """Creative artwork remains AI-authored with task-specific instructions."""
        self.page['exercise']['render_mode'] = 'authored'
        page, _ = prepare_activity_presentation(self.page, self.brief, self.config)
        self.assertEqual(page, self.page)
        guidance = activity_quality_guidance('Pre-K-K')
        self.assertIn('FACELESS', guidance)
        self.assertIn('THREE', guidance)
        self.assertIn('5-12 words', guidance)


class PrintedActivityTests(unittest.TestCase):
    """Run real PDF geometry and canonical answer binding for the new composition."""
    def test_counting_page_passes_actual_print_checks(self):
        """The fuller sheet must remain one A4 page with readable labels."""
        from core.creative_generator import validate_design
        symbol = {'shape': 'star', 'color': 'yellow', 'size': 'large'}
        raw = {'html': '<h1 data-content="title"></h1>', 'images': [], 'exercise': {
            'render_mode': 'exact', 'mechanic': 'count', 'goal': 'Count within ten.',
            'visual': {'id': 'stars', 'question': 1, 'kind': 'count', 'rows': [[symbol] * 4]},
            'questions': [], 'captions': []}}
        config = {'purposeful_activity_layout': True, 'student_font_pt': 15,
                  'minimum_text_pt': 14, 'items_per_page': 3, 'visual_area_mm2': 10500}
        page = validate_design(raw, 15, quality=config, expected_title='Spooky Counting',
            require_coherent=True, brief={'title': 'Spooky Counting', 'render_mode': 'exact', 'mechanic': 'count'})
        self.assertEqual(page['title'], 'Count the Stars')
        self.assertEqual(page['planned_intent']['title'], page['title'])
        self.assertIn('1: 4; 2: 3; 3: 5', build_visual(page['visuals'][0])[1])

    def test_workspace_reference_does_not_point_to_artwork(self):
        """Replace an incorrect spatial reference without changing the drawing task."""
        page = {'exercise': {'render_mode': 'authored', 'questions': [
            {'prompt': 'Draw your favorite part in the big box above!', 'space_mm': 55}]}}
        result, _ = prepare_activity_presentation(page, {}, {})
        self.assertEqual(result['exercise']['questions'][0]['prompt'],
                         'Draw your favorite part in the answer box!')
        self.assertEqual(result['exercise']['questions'][0]['space_mm'], 55)

    def test_candy_corn_is_real_vector_art(self):
        """Thematic candy corn must be a drawn asset, not a renamed basic shape."""
        from core.task_visuals import icon, symbol
        asset = symbol({'shape': 'candy_corn', 'color': 'yellow', 'size': 'large'})
        svg = icon(asset, 100, 100)
        self.assertIn('#F18A35', svg)
        self.assertIn('#FFFFFF', svg)
