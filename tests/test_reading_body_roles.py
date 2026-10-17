"""Regress generic source-body namespaces and named source _text suffixes."""
from copy import deepcopy
import unittest

from core.content_binding import canonical_content_slot
from core.reading_bindings import normalize_reading_body_aliases
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page
from tests.test_reading_bindings import plain_text


class ReadingBodyRoleTests(unittest.TestCase):
    """Both reported designs bind once, retaining distinct evidence and print geometry."""

    def test_generic_caption_body_with_data_table_in_both_bands(self):
        """A body mislabeled as a caption uses the one declared event_data source."""
        for band in ('3rd-4th','5th-6th'):
            for prefilled in (False,True):
                with self.subTest(band=band,prefilled=prefilled):
                    raw=fixtures.inventory_page(10 if band=='5th-6th' else 1)
                    source={'id':'event_data','label':'Inventory Note',
                        'text':'In this fictional inventory, distributed items leave storage. All returned items are usable and restocked.'}
                    raw['exercise']['stimuli']=[source]
                    raw['exercise']['captions']=[{'id':'source_label','text':'Inventory Note'}]
                    raw['html']=raw['html'].replace('<p data-content="stimulus_supply_log"></p>',
                        '<p data-content="caption_source_text">'+(source['text'] if prefilled else '')+'</p>')
                    before=deepcopy(raw);page=fixtures.CompleteStudentTaskTests().ask(raw,band)
                    self.assertEqual(raw,before)
                    self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
                    self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
                    self.assertEqual(page['images'],before['images'])
                    self.assertEqual(plain_text(page['html']).count(source['text']),1)
                    self.assertEqual(page['source_layout'].count('data-content="stimulus_event_data"'),1)
                    self.assertNotIn('data-content="caption_source_text"',page['source_layout'])
                    self.assertEqual(plain_text(page['html']).count('Inventory Note'),1)

    def test_named_body_suffix_preserves_two_different_sources(self):
        """source_a_text resolves to A and source_b_text to B, never by list order."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page()
            for q,space in zip(raw['exercise']['questions'],(35,50)):q['space_mm']=space
            for source,old,new in zip(raw['exercise']['stimuli'],('note_a','note_b'),('source_a','source_b')):
                source['id']=new
                raw['html']=raw['html'].replace('stimulus_'+old,'stimulus_'+new+'_text')
            raw['exercise']['captions']=[{'id':'source_a_label','text':'Card A'},{'id':'source_b_label','text':'Card B'}]
            before=deepcopy(raw);page=fixtures.CompleteStudentTaskTests().ask(raw,band)
            self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            for source in raw['exercise']['stimuli']:
                self.assertEqual(page['source_layout'].count('data-content="stimulus_'+source['id']+'"'),1)
                self.assertEqual(plain_text(page['html']).count(source['text']),1)
                expected_mentions=1+sum(q['prompt'].count(source['label']) for q in raw['exercise']['questions'])
                self.assertEqual(plain_text(page['html']).count(source['label']),expected_mentions)

    def test_alias_precedence_collision_and_unknown_named_source(self):
        """Exact IDs win; missing B never borrows A; prefix collisions stay explicit."""
        blocks={'stimulus_source_a':'A','stimulus_source_b':'B'}
        for slot in ('stimulus_source_a_text','caption_source_a_text','source_a_body','source_a_content'):
            self.assertEqual(canonical_content_slot(slot,blocks),'stimulus_source_a')
        self.assertEqual(canonical_content_slot('stimulus_source_a_text',dict(blocks,stimulus_source_a_text='Separate A text')),'stimulus_source_a_text')
        self.assertEqual(canonical_content_slot('source_a_text',dict(blocks,caption_source_a_text='Heading',stimulus_source_a_text='Separate text')),'source_a_text')
        exercise={'render_mode':'authored','stimuli':[{'id':'event_data','text':'Complete retained event data.'}]}
        config={'student_workbook':True};one={'stimulus_event_data':'Complete retained event data.'}
        for markup,available in (
            ('<p data-content="stimulus_source_b"></p>',one),
            ('<p data-content="caption_source_text"></p>',blocks),
            ('<p data-content="caption_source_text">Partial or conflicting evidence.</p>',one),
            ('<p data-content="caption_source_text"></p><p data-content="stimulus_event_data"></p>',one),
            ('<p data-content="caption_source_text"></p><p data-content="stimulus_source_text"></p>',one),
            ('<h3 data-content="caption_source_text"></h3>',one)):
            self.assertEqual(normalize_reading_body_aliases(markup,available,exercise,config),markup)


if __name__=='__main__':unittest.main()
