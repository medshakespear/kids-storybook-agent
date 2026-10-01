"""Regress numeric notation and model CSS failures from live cron logs."""
import json
import unittest
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.creative_layout import reveal_print_content
from core.exercise_quality import calculate,normalize_calculation
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page
from tests.test_creative_design import cover_fixture


class ModelNotationTests(unittest.TestCase):
    """Normalize safe syntax locally and preserve strict checks for actual content defects."""

    def setUp(self):
        """Use upper-grade configuration matching the reported activity."""
        self.config=load_grade_config()['5th-6th']

    def validate(self,page):
        """Run production shared-exercise and measured layout validation."""
        return validate_design(page,11,quality=self.config,expected_title='Museum Math',require_coherent=True)

    def math_page(self,prompt,expression,answer,key):
        """Create one contextual question with a canonical numeric result."""
        page=authored_page(mechanic='plan a museum visit')
        page['exercise']['questions']=[dict(id='1',prompt=prompt,answer=key,space_mm=20,
                                           calculation=dict(expression=expression,answer=answer))]
        return page

    def test_numeric_notation_is_exact_and_safe(self):
        """Percent suffixes and display punctuation preserve their exact numerical meaning."""
        for expression,result in [('15%*200',30),('$12.50 + $7.25',Fraction('19.75')),
                                  ('£1,200 - £20',1180),('3 × (4 + 2)',18),
                                  ('3 x (4 + 2)',18),('8 · 3',24),('50%+25%',Fraction('0.75'))]:
            with self.subTest(expression=expression):
                self.assertEqual(calculate(normalize_calculation(expression)),result)

    def test_normalization_never_guesses_equations_or_executes_code(self):
        """Unknowns, word formulas, ambiguous grouping and executable syntax remain invalid."""
        for expression in ['x+8=20','total_cost','15% of 200','10%3','1,20+2',
                           '__import__("os")','2**3','float(2)','$12 dollars+3','20+8=28']:
            with self.subTest(expression=expression),self.assertRaises(ValueError):
                normalize_calculation(expression)

    def test_canonical_expression_and_printed_currency_answer_stay_bound(self):
        """Model notation is stored as the same numeric expression used for math verification."""
        page=self.math_page('What is $1,200 - $20?','$1,200-$20',1180,'$1,180')
        result=self.validate(page)
        self.assertEqual(result['exercise']['questions'][0]['calculation']['expression'],'1200-20')
        self.assertEqual(result['calculations'][0]['expression'],'1200-20')
        self.assertIn('$1,200 - $20',result['html'])
        self.assertIn('$1,180',result['answers'])

    def test_percentage_question_needs_no_model_retry(self):
        """A valid upper-grade percentage computation passes in its first local validation."""
        result=self.validate(self.math_page('Find 15 percent of 200.','15%*200',30,'30'))
        self.assertEqual(result['calculations'][0]['expression'],'(15/100)*200')

    def test_wrong_answers_are_not_repaired_by_notation_normalization(self):
        """Safe punctuation cleanup must never approve an incorrect declared solution."""
        with self.assertRaisesRegex(ValueError,'declared math answer is incorrect'):
            self.validate(self.math_page('Find 15 percent of 200.','15%*200',20,'20'))

    def test_invalid_expression_has_question_and_expression_context(self):
        """The next diagnostic identifies the offending field instead of a generic AST error."""
        with self.assertRaisesRegex(ValueError,"Question 1: calculation expression 'total_cost'"):
            self.validate(self.math_page('Compute the total.','total_cost',12,'12'))

    def test_failed_calculation_repair_uses_the_current_shared_schema(self):
        """A failed unknown equation receives numeric-only guidance without legacy manifests."""
        bad=self.math_page('Which number plus 8 makes 20?','x+8=20',12,'12')
        good=deepcopy(bad);good['exercise']['questions'][0]['calculation']['expression']='20-8'
        api=Mock()
        def response(page):
            """Emulate one complete JSON chat response."""
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        api.chat.completions.create.side_effect=[response(bad),response(good)]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 1')
        correction=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('exercise.questions[].calculation',correction)
        self.assertIn('20-8',correction)
        self.assertNotIn('Every calculations item',correction)
        self.assertEqual(result['calculations'][0]['expression'],'20-8')
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_original_generic_error_also_gets_targeted_repair(self):
        """The exact error text pasted by the user matches the repair branch."""
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
        calls=[]
        def validate(raw):
            """Fail once with the production log's diagnostic, then accept its correction."""
            calls.append(raw)
            if len(calls)==1:
                raise ValueError('Only integer/decimal literals, parentheses and + - * / are allowed; no variables, equations, units, percent signs or powers')
            return raw
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            ask_json(layout_contract(11,11,coherent=True),validate,'Activity design 1')
        self.assertIn('Correct ONLY exercise.questions[].calculation',api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])

    def test_cover_clipping_declaration_is_removed_without_redesign(self):
        """A fitting cover keeps its title and art instead of consuming a repair request."""
        raw=cover_fixture();raw['html']=raw['html'].replace('color:#0b787a','overflow:hidden;color:#0b787a')
        result=validate_design(raw,11,cover=True,quality=self.config)
        self.assertNotIn('overflow:hidden',result['html'])
        self.assertIn('Garden Makers',result['html'])
        self.assertEqual(result['images'],raw['images'])

    def test_removing_clipping_exposes_overflow_instead_of_hiding_it(self):
        """Oversized cover content still fails measured bounds after clipping is removed."""
        raw=cover_fixture();raw['html']='<div style="height:300mm;overflow:hidden">'+raw['html']+'</div>'
        with self.assertRaisesRegex(ValueError,'Design overflow'):
            validate_design(raw,11,cover=True,quality=self.config)

    def test_visible_style_cleanup_preserves_other_declarations(self):
        """Only recognized clipping declarations are normalized; other CSS stays validated."""
        result=reveal_print_content("<div style='color:teal;overflow-x:auto;padding:3mm'>Hello</div>")
        self.assertIn('color:teal',result)
        self.assertIn('padding:3mm',result)
        self.assertNotIn('overflow-x',result)
        invalid='<div style="overflow:surprise">Hello</div>'
        self.assertEqual(reveal_print_content(invalid),invalid)

    def test_malformed_css_keeps_its_original_validation_error(self):
        """Clipping cleanup does not turn a CSS parse defect into a serialization failure."""
        markup='<div style="overflow:hidden;this is malformed">Hello</div>'
        self.assertEqual(reveal_print_content(markup),markup)
