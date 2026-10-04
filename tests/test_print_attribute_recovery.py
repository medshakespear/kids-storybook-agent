"""Exercise safe attribute conversion and diagnostic boundaries in every grade band."""
from copy import deepcopy
import unittest
from core.print_tags import normalize_print_markup
from core.activity_presentation import validate_source_markup
from core.creative_generator import validate_design, layout_contract
from core.creative_layout import PrintFragment
from core.pipeline import load_grade_config
from tests.coherent_fixtures import exact_page, visual_examples


class PrintAttributeRecoveryTests(unittest.TestCase):
    """Preserve print geometry and reject active or ambiguous attributes."""
    def test_legacy_hints_keep_css_precedence_and_text(self):
        """Legacy dimensions become styles; existing styles override presentation hints."""
        markup='<div align="center" bgcolor="#FFEEDD"><img data-asset="scene" width="100" height="40mm" style="width:120mm"/><p valign="top">A &amp; B</p></div>'
        result=normalize_print_markup(markup)
        self.assertIn('width:100px;height:40mm;width:120mm',result)
        self.assertIn('text-align:center;background-color:#FFEEDD',result)
        self.assertIn('vertical-align:top',result)
        self.assertIn('A &amp; B',result)
        self.assertEqual(normalize_print_markup(result),result)
        validate_source_markup(markup)

    def test_real_page_conversion_all_grades(self):
        """Converted source reaches real bindings and A4 checks for every grade."""
        for band,config in load_grade_config().items():
            with self.subTest(band=band):
                page=exact_page(visual_examples()[3])
                page['html']=page['html'].replace('style="width:175mm;height:150mm"',
                    'width="175mm" height="150mm" align="center" loading="lazy" decoding="async" data-page="1"')
                original=deepcopy(page)
                result=validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Count the Stars',require_coherent=True,
                    brief={'title':'Count the Stars','render_mode':'exact','mechanic':'count'})
                self.assertEqual(page,original)
                self.assertEqual(result['exercise']['visual'],page['exercise']['visual'])
                self.assertNotIn('loading=',result['html'])
                self.assertIn('data-visual="counts"',result['html'])

    def test_unknown_or_invalid_attribute_names_are_reported(self):
        """Report tag/name without dumping attribute values into logs or prompts."""
        for attr in ('onclick="secret"','src="https://example.com/secret"','hidden',
                     'width="-10mm"','height="0"','align="diagonal"','data-contentt="title"'):
            key=attr.split('=')[0]
            with self.subTest(attr=attr),self.assertRaisesRegex(ValueError,f"{key}.*<div>"):
                validate_source_markup('<div '+attr+'>Text</div>')
        with self.assertRaisesRegex(ValueError,'mystery.*<p>'):
            parser=PrintFragment({},True);parser.feed('<p mystery="secret">Text</p>')

    def test_duplicate_dimensions_remain_rejected(self):
        """Never erase duplicate source values by merging them into one CSS attribute."""
        for attrs in ('width="10mm" width="20mm"','style="color:red" style="color:blue"'):
            with self.subTest(attrs=attrs),self.assertRaisesRegex(ValueError,'Duplicate'):
                validate_source_markup('<div '+attrs+'>Text</div>')

    def test_all_layout_prompts_list_allowed_attributes(self):
        """Cover, coherent and legacy modes all explicitly request inline presentation."""
        for kwargs in ({'cover':True},{'coherent':True},{}):
            with self.subTest(kwargs=kwargs):
                prompt=layout_contract(14,14,**kwargs)
                self.assertIn('HTML attributes: style, data-content, data-asset, data-visual, colspan, rowspan only.',prompt)
                self.assertIn('never in separate HTML attributes',prompt)
