"""Regress prefilled slots and semantic wrappers from first/second-grade cron failures."""
import unittest
from copy import deepcopy

from core.creative_generator import validate_design
from core.creative_layout import fragment
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page
from tests.test_creative_design import cover_fixture


class ContentBindingRepairTests(unittest.TestCase):
    """Normalize harmless model drafts without accepting unbound tasks or dropping graphics."""

    def setUp(self):
        """Use the reported younger-grade layout and reading limits."""
        self.config=load_grade_config()['1st-2nd']

    def validate(self,page):
        """Exercise the actual canonical content compiler and print preflight."""
        return validate_design(page,14,quality=self.config,expected_title='Safe Design',require_coherent=True)

    def test_filled_slots_use_canonical_text_once(self):
        """Model-written copies inside slots cannot override shared instructions or title."""
        page=authored_page()
        page['html']=page['html'].replace('></h1>','>Old Wrong Title</h1>')
        page['html']=page['html'].replace('data-content="directions"></p>',
                                        'data-content="directions">Follow this incorrect draft.</p>')
        result=self.validate(page)
        self.assertIn('Safe Design',result['html'])
        self.assertNotIn('Old Wrong Title',result['html'])
        self.assertNotIn('incorrect draft',result['html'])
        self.assertEqual(result['html'].count(page['exercise']['directions']),1)
        self.assertEqual(result['exercise'],page['exercise'])

    def test_nested_text_draft_is_replaced_without_duplicate_response_area(self):
        """A common prefilled question container retains one canonical prompt and answer space."""
        page=authored_page()
        page['html']=page['html'].replace('border-radius:4mm"></div>',
            'border-radius:4mm"><p><strong>Draw a shelter.</strong></p><div style="height:40mm"></div></div>')
        result=self.validate(page)
        self.assertEqual(result['html'].count('Draw your shelter.'),1)
        self.assertEqual(result['html'].count('height:45mm'),1)
        self.assertNotIn('height:40mm',result['html'])

    def test_exact_unbound_copies_receive_correct_binding_and_numbers(self):
        """Identical raw wording is recovered locally rather than requesting a redesigned page."""
        page=authored_page()
        page['html']=page['html'].replace('<h1 data-content="title"','<h1').replace('></h1>','>Activity 1: Safe Design</h1>')
        page['html']=page['html'].replace('<p data-content="directions"></p>',
                                         '<p>'+page['exercise']['directions']+'</p>')
        page['html']=page['html'].replace('<div data-content="question_1"','<div').replace('border-radius:4mm"></div>',
                                       'border-radius:4mm">'+page['exercise']['questions'][0]['prompt']+'</div>')
        result=self.validate(page)
        self.assertIn('1. Draw your shelter.',result['html'])
        self.assertIn('height:45mm',result['html'])
        self.assertEqual(result['exercise_binding']['status'],'bound')

    def test_duplicate_canonical_directions_are_not_printed_twice(self):
        """A stray exact copy of an already-bound direction does not become an extra task."""
        page=authored_page();page['html']+='<p>'+page['exercise']['directions']+'</p>'
        result=self.validate(page)
        self.assertEqual(result['html'].count(page['exercise']['directions']),1)

    def test_unrelated_raw_instruction_still_fails_with_specific_feedback(self):
        """Known mismatched tasks are not accepted under the guise of forgiving HTML."""
        page=authored_page();page['html']+='<p>Count the missing seesaws.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording:.*Count the missing seesaws'):
            self.validate(page)

    def test_inferred_container_cannot_discard_new_tasks(self):
        """A canonical first text chunk does not hide an unrelated instruction in nested markup."""
        page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<p>'+page['exercise']['directions']+'<span>Now count the stars.</span></p>')
        with self.assertRaisesRegex(ValueError,'inferred content slot'):
            self.validate(page)

    def test_images_inside_text_slots_are_not_silently_removed(self):
        """Graphics must remain explicit layout assets even when the slot text is redundant."""
        page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<p data-content="directions"><img data-asset="scene" style="width:175mm;height:75mm"/></p>')
        with self.assertRaisesRegex(ValueError,'keep graphics and other slots outside'):
            self.validate(page)

    def test_semantic_wrappers_are_shared_by_compiler_and_pdf_renderer(self):
        """Header, main, figure and captions map to safe containers with unchanged styling."""
        page=authored_page();page['html']='<article><header>'+page['html']+'</header><footer><p data-content="name"></p></footer></article>'
        result=self.validate(page)
        self.assertNotIn('<header',result['html'])
        self.assertNotIn('<article',result['html'])
        self.assertIn('Safe Design',fragment(result,preview=True))
        cover=cover_fixture();cover['html']='<main><header>'+cover['html']+'</header></main>'
        cover_result=validate_design(cover,14,quality=self.config,cover=True)
        self.assertNotIn('<main',fragment(cover_result,preview=True))
        self.assertEqual(cover_result['images'],cover['images'])

    def test_nested_script_cannot_pass_as_prefilled_text(self):
        """Forgiving content-copy handling never accepts executable markup."""
        page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<p data-content="directions"><script>bad()</script></p>')
        with self.assertRaises(ValueError): self.validate(page)

    def test_duplicate_explicit_slots_remain_rejected(self):
        """Recovery does not invent a choice between two independently bound copies."""
        page=authored_page();page['html']+='<p data-content="directions"></p>'
        with self.assertRaisesRegex(ValueError,'repeated exercise content slot'):
            self.validate(page)
