"""Regress a passage mislabeled as a stimulus followed by a missing/nested source label."""
from copy import deepcopy
import unittest

from core.content_binding import bind_formatted_canonical_text
from core.reading_bindings import normalize_passage_alias
from core.label_bindings import restore_declared_labels
from tests import test_complete_student_tasks as fixtures
from tests.test_source_body_slots import passage_page
from tests.test_reading_bindings import plain_text


class PassageLabelChainTests(unittest.TestCase):
    """Recover existing text and its retained label without fabricating another source."""

    def test_reported_chain_uses_one_completion_in_both_bands(self):
        """A nested source-label wrapper cannot hide a canonical passage from recovery."""
        for band in ('3rd-4th','5th-6th'):
            for nested in (False,True):
                with self.subTest(band=band,nested=nested):
                    raw=passage_page();raw['exercise']['captions']=[{'id':'source_label','text':'Weather Source A'}]
                    raw['html']=raw['html'].replace('source_harvest','stimulus_source_a')
                    if nested:
                        raw['html']=raw['html'].replace('<p data-content="stimulus_source_a" style="background-color:#EDF7F4;padding:2mm"></p>',
                            '<div data-content="caption_source_label"><p>Weather Source A</p><p data-content="stimulus_source_a"></p></div>')
                    before=deepcopy(raw);page=fixtures.CompleteStudentTaskTests().ask(raw,band)
                    self.assertEqual(raw,before)
                    self.assertEqual(page['exercise']['passage'],before['exercise']['passage'])
                    self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
                    self.assertEqual(page['exercise']['captions'],before['exercise']['captions'])
                    self.assertEqual(page['exercise']['stimuli'],[])
                    self.assertEqual(page['images'],before['images'])
                    self.assertEqual(plain_text(page['html']).count(raw['exercise']['passage']),1)
                    self.assertEqual(plain_text(page['html']).count('Weather Source A'),1)
                    self.assertEqual(page['source_layout'].count('data-content="passage"'),1)
                    self.assertNotIn('data-content="stimulus_source_a"',page['source_layout'])

    def test_complete_mixed_passage_preserves_artwork_and_workspaces(self):
        """Only a whole retained reading can authorize unwrapping a media-bearing alias."""
        blocks={'passage':'A complete retained reading.','caption_source_label':'Reading Source'}
        exercise={'render_mode':'authored','captions':[{'id':'source_label','text':'Reading Source'}],'stimuli':[]}
        config={'student_workbook':True}
        markup='<div data-content="stimulus_source_a"><p>A complete retained reading.</p><img data-asset="scene"><div style="height:40mm;border:1px solid blue"></div></div>'
        normalized=normalize_passage_alias(markup,blocks,exercise,config)
        self.assertIn('data-content="passage"',normalized)
        result=bind_formatted_canonical_text(normalized,blocks,separate_protected=True)
        result=restore_declared_labels(result,blocks,exercise,config)
        self.assertEqual(result.count('data-content="passage"'),1)
        self.assertEqual(result.count('data-content="caption_source_label"'),1)
        self.assertEqual(result.count('data-asset="scene"'),1)
        self.assertIn('height:40mm',result)
        for body in ('','A partial reading.','Unrelated source evidence.'):
            bad=markup.replace('A complete retained reading.',body)
            self.assertEqual(normalize_passage_alias(bad,blocks,exercise,config),bad)

    def test_source_label_does_not_guess_between_passage_and_sources(self):
        """Generic labels cannot be attached to a passage when multiple readings coexist."""
        markup='<p data-content="passage"></p><p data-content="stimulus_other"></p>'
        exercise={'render_mode':'authored','stimuli':[{'id':'other','text':'Independent source.'}],
            'captions':[{'id':'source_label','text':'Source A'}]}
        blocks={'passage':'First source.','stimulus_other':'Independent source.','caption_source_label':'Source A'}
        self.assertNotIn('data-content="caption_source_label"',restore_declared_labels(markup,blocks,exercise,{'student_workbook':True}))
        for html in ('<p data-content="stimulus_source_a"></p><p data-content="stimulus_source_b"></p>',
                     '<p data-content="stimulus_source_a"></p><p data-content="passage"></p>'):
            self.assertEqual(normalize_passage_alias(html,{'passage':'First source.'},exercise,{'student_workbook':True}),html)


if __name__=='__main__':unittest.main()
