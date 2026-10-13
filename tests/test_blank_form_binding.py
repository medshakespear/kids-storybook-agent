"""Normalize empty student form controls without accepting independent task wording."""
from copy import deepcopy
import unittest
from core.page_contract import BoundLayout
from core.creative_generator import validate_design
from core.exact_context import normalize_exact_context
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page, exact_page, visual_examples


class BlankFormBindingTests(unittest.TestCase):
    """Preserve answer boxes, metadata, canonical instructions and printed work areas."""

    def config(self,band):
        """Use the production mixed settings for both active grade bands."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=4,context_caption_limit=24,items_per_page=2)

    def test_empty_boxes_are_workspace_but_marked_answers_and_tasks_are_not(self):
        """Accept only fully empty bracket controls, including multiple boxes."""
        for value in ('[   ]','[ ] [ ]','[____]'):
            parser=BoundLayout({'title':'Test'})
            parser.feed('<p>'+value+'</p>')
            self.assertIn(value,''.join(parser.parts))
        for value in ('[X]','[2]','[ ] Explain your choice.','[Correct]'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                BoundLayout({'title':'Test'}).feed('<p>'+value+'</p>')

    def test_combined_metadata_and_blank_boxes_print_for_both_active_grades(self):
        """A styled combined line is bound without dropping the task or response space."""
        for band in ('3rd-4th','5th-6th'):
            for line in ('Name: _______________________________      Date: ___________________',
                         'Date: ____________ Name: ____________________',
                         '<strong>Name:</strong> _____________ <em>Date:</em> _____________'):
                page=authored_page();page['exercise'].update(captions=[],stimuli=[])
                original=deepcopy(page['exercise']);config=self.config(band)
                page['html']='<p style="color:#167E80">'+line+'</p>'+page['html']+'<p>[   ] [   ]</p>'
                result=validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Garden Design',require_coherent=True)
                self.assertEqual(result['html'].count('Name:'),1)
                self.assertEqual(result['html'].count('Date:'),1)
                self.assertIn('[   ] [   ]',result['html'])
                self.assertEqual(result['exercise'],original)
                self.assertIn('height:45mm',result['html'])

    def test_combined_metadata_deduplicates_only_blank_identification_fields(self):
        """An existing separate name/date slot cannot create redundant printed fields."""
        page=authored_page();config=self.config('3rd-4th')
        page['html']='<p data-content="name"></p><p>Name: ______ Date: ______</p>'+page['html']+'<p data-content="date"></p>'
        result=validate_design(page,config['student_font_pt'],quality=config,expected_title='Garden Design',require_coherent=True)
        self.assertEqual(result['html'].count('Name:'),1)
        self.assertEqual(result['html'].count('Date:'),1)

    def test_identification_line_cannot_swallow_meaningful_content(self):
        """Filled student values and an appended task need proper content binding."""
        for line in ('Name: Alex Date: October 13','Name: _____ Date: _____ Now draw a plant.'):
            page=authored_page();page['html']='<p>'+line+'</p>'+page['html'];config=self.config('3rd-4th')
            with self.subTest(line=line),self.assertRaises(ValueError):
                validate_design(page,config['student_font_pt'],quality=config,expected_title='Garden Design',require_coherent=True)

    def test_empty_unknown_direction_box_keeps_all_workspace_geometry(self):
        """Removing an invalid text binding must never delete the empty writing panel."""
        markup='<div data-content="directions" style="height:25mm;border:0.4mm solid #167E80"></div>'
        result=normalize_exact_context({'render_mode':'exact'},markup)
        self.assertNotIn('data-content="directions"',result)
        self.assertIn('height:25mm',result)
        self.assertIn('border:0.4mm solid #167E80',result)

    def test_unknown_directions_with_exact_caption_copy_rebinds_without_task_change(self):
        """A mislabeled literal known caption can bind locally; other instructions cannot."""
        page=exact_page(visual_examples()[5])
        page['exercise']['captions']=[{'id':'context','text':'This fictional museum display includes different shapes.'}]
        page['html']+='<p data-content="directions">This fictional museum display includes different shapes.</p>'
        config=self.config('3rd-4th')
        result=validate_design(page,config['student_font_pt'],quality=config,expected_title='Museum Sorting',require_coherent=True)
        self.assertEqual(result['exercise']['captions'],page['exercise']['captions'])
        self.assertEqual(result['html'].count(page['exercise']['captions'][0]['text']),1)
        self.assertEqual(result['exercise']['visual'],page['exercise']['visual'])
        self.assertEqual(normalize_exact_context({'render_mode':'exact'},'<p data-content="directions">Explain a new rule.</p>'),
                         '<p data-content="directions">Explain a new rule.</p>')
