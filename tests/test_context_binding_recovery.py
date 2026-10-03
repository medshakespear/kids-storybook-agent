"""Regress unbound punctuation, factual paragraphs and literal exact-task duplicates."""
from copy import deepcopy
import unittest
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import exact_page, visual_examples


class ContextBindingRecoveryTests(unittest.TestCase):
    """Use actual canonical binding and measured PDF geometry for retained content."""
    def setUp(self):
        """Build a computed sort page that already has a guaranteed answer key."""
        self.page=exact_page(visual_examples()[5])
        self.config=load_grade_config()['3rd-4th']

    def validate(self,page):
        """Compile the shared task and its complete printable page."""
        return validate_design(page,12,quality=self.config,expected_title='Pattern Studio',require_coherent=True)

    def test_standalone_punctuation_is_not_unbound_task_wording(self):
        """A separator colon contributes no new instruction or question."""
        self.page['html'] += '<p>:</p>'
        result=self.validate(self.page)
        self.assertIn(':',result['html'])
        self.assertEqual(result['exercise']['questions'],[])

    def test_complete_factual_context_keeps_every_word_in_bounded_fields(self):
        """A paragraph becomes canonical text without truncation or AI paraphrasing."""
        text=('Weavers use geometric motifs to organize repeating bands. Each band can show a different '
              'arrangement of colors and shapes. A pattern contains a unit that appears again in the same order.')
        self.page['html'] += f'<p style="margin:0 0 3mm;font-size:12pt">{text}</p>'
        source=deepcopy(self.page)
        result=self.validate(self.page)
        captions=result['exercise']['captions']
        self.assertEqual(' '.join(c['text'] for c in captions),text)
        self.assertTrue(all(len(c['text'])<=120 for c in captions))
        self.assertEqual(result['exercise']['visual'],source['exercise']['visual'])
        self.assertEqual(self.page,source)

    def test_commands_and_solutions_are_not_promoted_to_context(self):
        """Recovery cannot hide a new action or an answer in decorative captions."""
        for text in ['Count the pumpkins in each basket.', 'The solution is three groups.']:
            page=deepcopy(self.page);page['html']+=f'<p>{text}</p>'
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'Put ALL printed wording'):
                self.validate(page)

    def test_nested_context_does_not_swallow_a_following_task(self):
        """Whole-paragraph recovery leaves a separate undeclared task for semantic repair."""
        self.page['html'] += '<div><p>Weavers use repeating motifs.</p><p>Draw your own band.</p></div>'
        with self.assertRaisesRegex(ValueError,'Put ALL printed wording'):
            self.validate(self.page)

    def test_literal_duplicate_is_removed_but_real_extension_is_preserved(self):
        """The computed instruction owns its answer; additional student work keeps its slot."""
        duplicate={'id':'1','prompt':'Sort the pictures by shape.','answer':'Use the shape groups.','space_mm':0}
        extra={'id':'2','prompt':'Draw a new picture for one group.','answer':'Accept a shape-group drawing.','space_mm':20}
        self.page['exercise']['questions']=[duplicate,extra]
        self.page['html'] += '<p data-content="question_1"></p><div data-content="question_2"></div>'
        result=self.validate(self.page)
        self.assertEqual(result['exercise']['questions'],[extra])
        self.assertIn('2. Draw a new picture',result['html'])
        self.assertEqual(result['visuals'][0]['question'],1)

    def test_duplicate_with_independent_work_area_is_not_silently_removed(self):
        """Even identical wording cannot justify deleting explicit additional response space."""
        self.page['exercise']['questions']=[{'id':'1','prompt':'Sort the pictures by shape.',
                                            'answer':'Use shape groups.','space_mm':25}]
        self.page['html'] += '<div data-content="question_1"></div>'
        with self.assertRaisesRegex(ValueError,'reserved label 1'):
            self.validate(self.page)
