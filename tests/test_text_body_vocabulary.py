"""Regress text_body aliases, mixed reading/media wrappers and subject vocabulary labels."""
from copy import deepcopy
import unittest

from core.activity_stimuli import normalize_stimulus_ids
from core.content_binding import bind_standard_heading
from core.reading_bindings import normalize_reading_body_aliases
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page
from tests.test_reading_bindings import plain_text


def text_card_page(mixed=False):
    """Keep one complete labeled weather source and two source-supported reading tasks."""
    page=evidence_page();source=page['exercise']['stimuli'][0]
    source['id']='text_card';page['exercise']['stimuli']=[source]
    page['exercise'].update(mechanic='reading_evidence',directions='Read the weather note and answer both questions.')
    page['exercise']['questions'][0].update(prompt='What was measured in the weather note?',answer='Rainfall was measured.')
    page['exercise']['questions'][1].update(prompt='On which day was the observation recorded?',answer='Monday.')
    art='<img data-asset="weather" style="width:92mm;height:92mm"/>'
    body=('<p>'+source['text']+'</p>'+art) if mixed else ''
    page['html']=('<h1 data-content="title" style="font-size:18pt;margin:0"></h1>'
        '<p data-content="directions"></p><div data-content="stimulus_text_body">'+body+'</div>'+
        ('' if mixed else art)+'<div data-content="question_1"></div><div data-content="question_2"></div>')
    return page


class TextBodyVocabularyTests(unittest.TestCase):
    """Check content retention and measured layout with one mocked completion."""

    def test_plain_and_media_wrapped_body_recover_in_both_bands(self):
        """A complete source plus artwork never becomes a prefilled text-only slot."""
        for band in ('3rd-4th','5th-6th'):
            for mixed in (False,True):
                raw=text_card_page(mixed);before=deepcopy(raw)
                result=fixtures.CompleteStudentTaskTests().ask(raw,band)
                self.assertEqual(raw,before)
                self.assertEqual(result['exercise']['stimuli'],before['exercise']['stimuli'])
                self.assertEqual(result['images'],before['images'])
                self.assertEqual(plain_text(result['html']).count(before['exercise']['stimuli'][0]['text']),1)
                self.assertEqual(result['html'].count('data-asset="weather"'),1)
                self.assertNotIn('stimulus_text_body',result['html'])
                for q,original in zip(result['exercise']['questions'],before['exercise']['questions']):
                    self.assertEqual(q['prompt'],original['prompt']);self.assertEqual(q['answer'],original['answer'])

    def test_ambiguous_or_conflicting_body_alias_stays_unresolved(self):
        """A generic name cannot choose between sources or erase a conflicting excerpt."""
        for case in ('ambiguous','conflicting','used'):
            page=text_card_page()
            if case=='ambiguous':page['exercise']['stimuli'].append({'id':'source_card','text':'Independent source.'})
            elif case=='conflicting':page['html']=page['html'].replace('stimulus_text_body"></div>',
                'stimulus_text_body">Different evidence.</div>')
            else:page['html']+='<p data-content="stimulus_text_card"></p>'
            before=deepcopy(page);normalize_stimulus_ids(page,page['exercise']);self.assertEqual(page,before)

    def test_unverified_mixed_body_does_not_swallow_art_or_make_up_a_passage(self):
        """An empty mixed wrapper needs a real complete source copy before local rebinding."""
        exercise={'render_mode':'authored','stimuli':[{'id':'text_card','text':'Complete retained source.'}]}
        for body in ('<img data-asset="art"/>','Different evidence.<img data-asset="art"/>'):
            markup='<div data-content="stimulus_text_body">'+body+'</div>'
            result=normalize_reading_body_aliases(markup,{'stimulus_text_card':'Complete retained source.'},
                exercise,{'student_workbook':True})
            self.assertEqual(result,markup)

    def test_subject_vocabulary_heading_binds_without_repairing_paragraphs(self):
        """Short contextual headings are canonical labels, never replacement source text."""
        for title in ('Artifact Terms','Cultural Heritage Terms','Weather Definitions'):
            exercise={'render_mode':'authored','mechanic':'matching','captions':[]}
            markup='<h3>'+title+'</h3>'
            result=bind_standard_heading(markup,exercise)
            self.assertEqual([c['text'] for c in exercise['captions']],[title])
            self.assertIn('data-content="caption_',result)
        for title in ('Write Artifact Terms','Calculate Definitions','Answer the Terms','Terms are Definitions'):
            exercise={'render_mode':'authored','mechanic':'matching','captions':[]}
            markup='<h3>'+title+'</h3>'
            self.assertEqual(bind_standard_heading(markup,exercise),markup)
            self.assertEqual(exercise['captions'],[])
