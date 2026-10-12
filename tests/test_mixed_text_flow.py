"""Repair fixed-height source collisions without shrinking text or response workspaces."""
from copy import deepcopy
import unittest
from core.creative_generator import validate_design, merge_layout_repair
from core.pipeline import load_grade_config
from core.text_flow import reflow_text_heights
from tests.coherent_fixtures import authored_page


class MixedTextFlowTests(unittest.TestCase):
    """Preserve model composition/content while allowing text panels to grow."""

    def test_text_clamps_removed_but_art_and_blank_workspace_dimensions_remain(self):
        """Only text and redundant wrapper dimensions change."""
        source=('<div style="height:60mm;min-height:60mm;border:1mm solid teal">'
                '<p style="height:4mm;max-height:4mm">Lifestyle items wrap across lines.</p>'
                '<img data-asset="scene" style="width:90mm;height:90mm"/>'
                '<span style="height:30mm;border:0.4mm solid #809AA6"></span></div>'
                '<div style="height:35mm;border:1mm solid gold">_______________</div>')
        result=reflow_text_heights(source)
        self.assertNotIn('height:60mm',result)
        self.assertNotIn('height:4mm',result)
        self.assertIn('width:90mm;height:90mm',result)
        self.assertIn('height:30mm',result)
        self.assertIn('height:35mm',result)
        self.assertIn('Lifestyle items wrap across lines.',result)
        self.assertIn('_______________',result)

    def test_reflow_does_not_rebind_or_drop_printed_identification_fields(self):
        """The already-compiled Name/Date wording remains literal text after reflow."""
        source='<p style="height:2mm">Name: ____________________</p><p>Date: ____________________</p>'
        result=reflow_text_heights(source)
        self.assertIn('Name: ____________________',result)
        self.assertIn('Date: ____________________',result)
        self.assertNotIn('data-content',result)

    def test_reported_source_and_banner_question_do_not_overlap_in_both_grades(self):
        """Long text in a 4mm panel grows before the following response question prints."""
        for band in ('3rd-4th','5th-6th'):
            config=dict(load_grade_config()[band],purposeful_activity_layout=False,stimulus_limit=4,context_caption_limit=24)
            page=authored_page(mechanic='design_banner')
            page['exercise'].update(directions='Read the fictional case and plan a clear banner.',
                stimuli=[{'id':'case','text':('In this fictional campaign, students choose a banner for a school display. '
                'They compare clear wording, relevant illustrations and useful everyday lifestyle items.')}])
            page['exercise']['questions'][0].update(prompt='Draft your catchy banner. Explain why its message is clear.',
                answer='Accept a relevant banner and an explanation of clear wording or imagery.',space_mm=30)
            page['html']=page['html'].replace('<div data-content="question_1"',
                '<p data-content="stimulus_case" style="height:4mm;max-height:4mm;margin:0"></p><div data-content="question_1"')
            original=deepcopy(page)
            result=validate_design(page,config['student_font_pt'],quality=config,expected_title='Banner Choices',require_coherent=True)
            self.assertEqual(page,original)
            self.assertNotIn('height:4mm',result['html'])
            self.assertIn('lifestyle items.',result['html'])
            self.assertIn('Draft your catchy banner',result['html'])
            self.assertIn('height:30mm',result['html'])

    def test_mixed_layout_caption_drift_is_ignored_with_original_text_retained(self):
        """A layout-only retry cannot alter content even if the model proposes shorter captions."""
        original=authored_page();original['_caption_context_limit']=24
        original['exercise']['captions']=[{'id':'label','text':'Original caption wording.'}]
        original['html']+='<p data-content="caption_label"></p>'
        correction={'html':original['html'],'exercise':{'captions':[{'id':'label','text':'Shorter changed wording.'}]}}
        result=merge_layout_repair(original,correction)
        self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        legacy=deepcopy(original);legacy.pop('_caption_context_limit')
        with self.assertRaisesRegex(ValueError,'cannot change existing caption'):
            merge_layout_repair(legacy,correction)


if __name__=='__main__':unittest.main()
