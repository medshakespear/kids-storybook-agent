"""Regress bare declared sources and sole-passage aliases without inventing evidence."""
from copy import deepcopy
import unittest

from core.content_binding import canonical_content_slot
from core.reading_bindings import normalize_passage_alias
from core.creative_generator import validate_design
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page,workbook_config
from tests.test_reading_bindings import plain_text


def source_page():
    """Reproduce source_2 versus the declared stimulus_source_2 with another real source."""
    raw=evidence_page()
    for q,space in zip(raw['exercise']['questions'],(35,50)):q['space_mm']=space
    raw['exercise']['stimuli'][0]['id']='source_2'
    raw['html']=raw['html'].replace('stimulus_note_a','source_2')
    return raw


def passage_page():
    """Reproduce source_harvest when the only shared reading is exercise.passage."""
    raw=evidence_page()
    for q,space in zip(raw['exercise']['questions'],(35,50)):q['space_mm']=space
    raw['exercise']['passage']='A rain gauge collected 12 millimeters of rain on Monday. Rainy days are the most enjoyable days for everyone.'
    raw['exercise']['stimuli']=[]
    raw['html']=raw['html'].replace('stimulus_note_a','source_harvest')
    raw['html']=raw['html'].replace('<p data-content="stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"></p>','')
    return raw


class SourceBodySlotTests(unittest.TestCase):
    """Require one provider response and unchanged source, question, key and artwork."""

    def test_reported_aliases_compile_in_both_bands(self):
        """Real production compilation/reflow binds both errors before model repair."""
        for band in ('3rd-4th','5th-6th'):
            for factory in (source_page,passage_page):
                with self.subTest(band=band,source=factory.__name__):
                    raw=factory();original=deepcopy(raw)
                    checked=fixtures.CompleteStudentTaskTests().ask(raw,band)
                    self.assertEqual(raw,original)
                    self.assertEqual(checked['exercise']['questions'],raw['exercise']['questions'])
                    self.assertEqual(checked['exercise'].get('stimuli',[]),raw['exercise']['stimuli'])
                    self.assertEqual(checked['images'],raw['images'])
                    reading=raw['exercise'].get('passage') or raw['exercise']['stimuli'][0]['text']
                    self.assertEqual(plain_text(checked['html']).count(reading),1)
                    slot='passage' if factory==passage_page else 'stimulus_source_2'
                    self.assertEqual(checked['source_layout'].count('data-content="'+slot+'"'),1)

    def test_declared_id_resolution_never_guesses_between_namespaces(self):
        """Exact source identity is sufficient even with several declared source records."""
        self.assertEqual(canonical_content_slot('source_2',{'stimulus_source_2':'Text','stimulus_other':'Other'}),'stimulus_source_2')
        self.assertEqual(canonical_content_slot('source_2',{'stimulus_source_2':'Text','caption_source_2':'Heading'}),'source_2')
        self.assertEqual(canonical_content_slot('source_missing',{'stimulus_source_2':'Text'}),'source_missing')

    def test_passage_alias_accepts_only_complete_retained_text(self):
        """Repeated, competing, heading, media and conflicting placeholders remain errors."""
        blocks={'passage':'A harvest reading.'};exercise={'render_mode':'authored'};config={'student_workbook':True}
        for contents in ('','A <strong>harvest</strong> reading.'):
            original='<p data-content="source_harvest">'+contents+'</p>'
            result=normalize_passage_alias(original,blocks,exercise,config)
            self.assertEqual(result,'<p data-content="passage"></p>')
            self.assertEqual(normalize_passage_alias(result,blocks,exercise,config),result)
        examples=[
            '<p data-content="source_harvest">Another account.</p>',
            '<p data-content="source_harvest">A harvest</p>',
            '<p data-content="source_harvest"><img data-asset="scene"/></p>',
            '<p data-content="source_harvest"><span data-content="question_1"></span></p>',
            '<p data-content="source_harvest"></p><p data-content="source_other"></p>',
            '<p data-content="source_harvest"></p><p data-content="source_harvest"></p>',
            '<p data-content="source_harvest"></p><p data-content="passage"></p>',
            '<h2 data-content="source_harvest"></h2>',
            '<p data-content="source_heading"></p>']
        for markup in examples:
            self.assertEqual(normalize_passage_alias(markup,blocks,exercise,config),markup)
        markup='<p data-content="source_harvest"></p>'
        self.assertEqual(normalize_passage_alias(markup,dict(blocks,stimulus_other='A second source.'),exercise,config),markup)
        self.assertEqual(normalize_passage_alias(markup,blocks,exercise,{}),markup)

    def test_declared_duplicate_is_still_rejected(self):
        """A second alias cannot quietly print the same source twice."""
        raw=source_page();raw['html']+='<p data-content="stimulus_source_2"></p>'
        with self.assertRaisesRegex(ValueError,'already printed'):
            validate_design(raw,12,quality=workbook_config('3rd-4th'),expected_title='Weather Evidence Lab',require_coherent=True)


if __name__=='__main__':unittest.main()
