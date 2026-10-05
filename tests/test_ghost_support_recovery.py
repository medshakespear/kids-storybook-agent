"""Keep qualitative support questions separate from arithmetic and preserve exact puzzle layouts."""
from copy import deepcopy
import unittest

from core.calculation_attachment import detach_conceptual_calculation
from core.creative_generator import validate_design
from core.layout_recovery import single_exact_visual_recovery, exact_caption_grid_recovery
from core.pipeline import load_grade_config
from core.question_labels import renumber_open_exact_question
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page, visual_examples


class GhostSupportRecoveryTests(unittest.TestCase):
    """Regress stray 520-310 metadata, reserved labels and dense exact-page captions."""

    def test_qualitative_structure_questions_keep_their_prose_answers(self):
        """No arithmetic answer is manufactured for a clearly nonquantitative choice."""
        for prompt in ['Which ghost support would you recommend?',
                       'Which large ghost pillar should the builder use?',
                       'Which structure is suitable? Explain your reasoning.',
                       'What support would you choose?']:
            question = dict(id='3', prompt=prompt,
                answer='The large ghost monolith provides the necessary load-bearing capacity over the small ghost pillar.',
                calculation=dict(expression='520-310', answer=210), space_mm=25)
            original = deepcopy(question)
            detach_conceptual_calculation(question)
            self.assertNotIn('calculation', question)
            self.assertEqual(question, {k:v for k,v in original.items() if k != 'calculation'})

    def test_quantitative_or_ambiguous_choices_still_require_verification(self):
        """Numeric facts, number words and requested quantities keep their calculation."""
        for prompt in ['Which support holds 520 kilograms instead of 310?',
                       'Which structure has the greater number of pillars?',
                       'Which option uses half the total?',
                       'Which pillar has the remaining amount?', 'Choose the best result.']:
            question = dict(prompt=prompt, answer='The large ghost monolith.',
                            calculation=dict(expression='520-310', answer=210))
            original = deepcopy(question)
            detach_conceptual_calculation(question)
            self.assertEqual(question, original)

    def test_explicit_reasoning_followup_moves_its_slot_with_its_label(self):
        """A choice with a separate explanation action retains its own response panel."""
        exercise = dict(visual=dict(question=1), questions=[dict(id='1',
            prompt='Which ghost support would you recommend? Explain your reasoning.',
            answer='Accept a recommendation supported with a reason.', space_mm=25),
            dict(id='2', prompt='Describe a different solution.', answer='Accept a relevant idea.', space_mm=25)])
        original = deepcopy(exercise)
        html = renumber_open_exact_question(exercise,
            '<div data-content="question_1"></div><div data-content="question_2"></div>')
        self.assertEqual(exercise['questions'][0]['id'], '3')
        self.assertIn('question_3', html)
        self.assertNotIn('question_1', html)
        for key in ['prompt','answer','space_mm']:
            self.assertEqual(exercise['questions'][0][key], original['questions'][0][key])
        exercise = dict(visual=dict(question=1), questions=[dict(id='1',
            prompt='Which pumpkin is larger?', answer='The left pumpkin.', space_mm=25)])
        self.assertEqual(renumber_open_exact_question(exercise, '<p data-content="question_1"></p>'),
                         '<p data-content="question_1"></p>')

    def test_exact_schemas_reserve_puzzle_label_and_budget_for_all_mechanics(self):
        """Constrain the first response for both active grades, leaving authored questions flexible."""
        for band in ['3rd-4th', '5th-6th']:
            config = load_grade_config()[band]
            for kind in ['balance', 'count', 'differences', 'matching', 'maze', 'pattern', 'sort']:
                exercise = design_schema(dict(render_mode='exact', mechanic=kind), config)['properties']['exercise']['properties']
                self.assertEqual(exercise['visual']['properties']['question']['minimum'], 1)
                self.assertEqual(exercise['visual']['properties']['question']['maximum'], 1)
                self.assertNotIn('1', exercise['questions']['items']['properties']['id']['enum'])
                self.assertEqual(exercise['questions']['maxItems'], config['items_per_page'] - 1)
            authored = design_schema(dict(render_mode='authored', mechanic='design shelter'), config)
            questions = authored['properties']['exercise']['properties']['questions']
            self.assertEqual(questions['maxItems'], config['items_per_page'])
            self.assertNotIn('enum', questions['items']['properties']['id'])

    def dense_exact_page(self):
        """Build an exact diagram with contextual captions and additional open responses."""
        page = exact_page(visual_examples()[2])
        labels = ['Garden crop observations', 'Record details carefully', 'Compare your observations',
                  'Look for meaningful similarities', 'Use evidence from the diagram',
                  'Think about possible explanations']
        page['exercise']['captions'] = [dict(id=f'label_{i}',text=text) for i,text in enumerate(labels)]
        page['html'] += ''.join(f'<p data-content="caption_label_{i}"></p>' for i in range(6))
        page['exercise']['questions'] = [dict(id='2',prompt='Explain why collecting observations helps gardeners.',
            answer='Accept a reason relating observations to useful growing decisions.',space_mm=55),
            dict(id='3',prompt='Describe an observation that could help a gardener.',
                 answer='Accept a relevant example.',space_mm=55)]
        page['html'] += '<div data-content="question_2"></div><div data-content="question_3"></div>'
        return page

    def test_caption_grid_preserves_diagram_readability_and_responses(self):
        """Real print geometry measures the compact composition for both active grades."""
        page = self.dense_exact_page()
        original = deepcopy(page)
        for band in ['3rd-4th', '5th-6th']:
            with self.subTest(band=band):
                config = load_grade_config()[band]
                if band == '3rd-4th':
                    stacked = single_exact_visual_recovery(page, config['student_font_pt'], config['visual_area_mm2'])
                    with self.assertRaisesRegex(ValueError, 'Design overflow'):
                        validate_design(stacked, config['student_font_pt'], quality=config,
                            expected_title='Garden Detectives', require_coherent=True)
                candidate = exact_caption_grid_recovery(page, config['student_font_pt'], config['visual_area_mm2'])
                self.assertIsNotNone(candidate)
                result = validate_design(candidate, config['student_font_pt'], quality=config,
                    expected_title='Garden Detectives',require_coherent=True)
                self.assertEqual(result['exercise'], original['exercise'])
                self.assertEqual(result['html'].count('height:55mm'), 2)
                for caption in original['exercise']['captions']:
                    self.assertIn(caption['text'], result['html'])
        self.assertEqual(page, original)


if __name__ == '__main__':
    unittest.main()
