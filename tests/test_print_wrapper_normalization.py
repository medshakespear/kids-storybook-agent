"""Regression tests for safe semantic wrappers and inert model-authored metadata."""
from copy import deepcopy
import unittest
from core.print_tags import normalize_print_markup
from core.activity_presentation import validate_source_markup
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import exact_page, visual_examples


class PrintWrapperNormalizationTests(unittest.TestCase):
    """Keep content and asset bindings while avoiding harmless markup retries."""
    def test_aliases_and_passive_attributes_normalize_without_losing_text(self):
        """Header/footer markup keeps text, styling and named content slots."""
        raw = '<header class="heading" id="top" role="banner"><h1 data-content="title"></h1><p>A &amp; B</p></header><footer title="tip">End</footer>'
        result = normalize_print_markup(raw)
        self.assertEqual(result,'<div><h1 data-content="title"></h1><p>A &amp; B</p></div><div>End</div>')
        self.assertEqual(normalize_print_markup(result),result)
        validate_source_markup(raw)

    def test_reported_tags_and_attributes_pass_real_canonical_page_checks(self):
        """A preschool puzzle survives wrappers and metadata through actual print layout."""
        raw = exact_page(visual_examples()[3])
        raw['html'] = '<header class="page-header" id="header">'+raw['html']+'</header>'
        original = deepcopy(raw)
        config = load_grade_config()['Pre-K-K']
        result = validate_design(raw,config['student_font_pt'],quality=config,
            expected_title='Count the Stars',require_coherent=True,
            brief={'title':'Count the Stars','render_mode':'exact','mechanic':'count'})
        self.assertEqual(raw,original)
        self.assertEqual(result['exercise']['render_mode'],'exact')
        self.assertIn('Count',result['html'])
        self.assertNotIn('page-header',result['html'])

    def test_active_remote_and_hidden_markup_still_rejected(self):
        """Normalization cannot turn scripts or external image requests into success."""
        for markup in ('<header onclick="run()">Text</header>',
                       '<header><img src="https://example.com/image.png"/></header>',
                       '<header><script>run()</script></header>',
                       '<header style="display:none">Hidden wording</header>',
                       '<header hidden>Hidden wording</header>'):
            with self.subTest(markup=markup),self.assertRaises(ValueError):
                validate_source_markup(normalize_print_markup(markup))

    def test_functional_attributes_and_response_dimensions_are_retained(self):
        """Passive metadata cannot erase canonical slots, artwork or workspace sizing."""
        markup='<main id="page"><div class="answer" data-content="question_2" style="height:40mm"></div><img alt="owl" class="art" data-asset="owl" style="width:100mm;height:90mm"/></main>'
        result=normalize_print_markup(markup)
        self.assertIn('data-content="question_2"',result)
        self.assertIn('height:40mm',result)
        self.assertIn('data-asset="owl"',result)
        self.assertIn('width:100mm;height:90mm',result)

    def test_duplicate_functional_attributes_and_bad_nesting_remain_visible(self):
        """The normalizer preserves malformed input for strict downstream validation."""
        markup='<header style="color:red" style="color:blue"><p>Text</header></p>'
        result=normalize_print_markup(markup)
        self.assertEqual(result.count('style='),2)
        self.assertIn('</div></p>',result)
        with self.assertRaisesRegex(ValueError,'Duplicate layout attributes'):
            validate_source_markup(result)
