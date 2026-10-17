"""Regress published lettering, complete past-tense prose and migrating source collisions."""
from copy import deepcopy
import unittest

from core.authored_wording import merge_authored_wording,raw_paragraphs,bind_printed_context
from core.activity_stimuli import prepare_stimuli
from core.image_generator import _image_prompt,text_free_scene
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page
from tests.test_reading_bindings import plain_text

CONTEXT=('During Red Ribbon Week, local schools distributed awareness materials and hosted student workshops. '
         'Volunteers collected supplies and shared reports with their teachers after the event.')
SECOND=('Later, student groups recorded their findings and prepared short reports about the workshops. '
        'Families attended the school gathering and shared ideas about healthy habits.')


class RedRibbonRepairTests(unittest.TestCase):
    """Use mocked model completions and real print checks, with no image-review model."""

    def test_complete_past_tense_context_binds_locally_in_both_bands(self):
        """The reported source paragraph needs neither truncation nor another AI request."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page()
            for q,space in zip(raw['exercise']['questions'],(35,50)):q['space_mm']=space
            raw['html']=raw['html'].replace('<div data-content="question_1"',
                '<p>'+CONTEXT+'</p><div data-content="question_1"')
            before=deepcopy(raw);page=fixtures.CompleteStudentTaskTests().ask(raw,band)
            self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['passage'],CONTEXT)
            self.assertEqual(plain_text(page['html']).count(CONTEXT),1)
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(page['images'],before['images'])

    def test_block_wrapper_repair_preserves_each_whole_paragraph(self):
        """A scoped wording repair can bind complete neighboring paragraphs, never snippets."""
        raw=evidence_page();raw['html']='<div><p>'+CONTEXT+'</p><p>'+SECOND+'</p></div>'+raw['html']
        self.assertIn(CONTEXT.casefold(),raw_paragraphs(raw))
        corrected=deepcopy(raw);corrected['exercise']['passage']=CONTEXT+' '+SECOND
        corrected['html']=corrected['html'].replace('<div><p>'+CONTEXT+'</p><p>'+SECOND+'</p></div>',
            '<p data-content="passage"></p>')
        merged=merge_authored_wording(raw,corrected)
        self.assertEqual(merged['exercise']['passage'],CONTEXT+' '+SECOND)
        self.assertEqual(merged['exercise']['questions'],raw['exercise']['questions'])
        truncated=deepcopy(corrected);truncated['exercise']['passage']=CONTEXT[:100]
        with self.assertRaisesRegex(ValueError,'complete original paragraphs'):merge_authored_wording(raw,truncated)

    def test_colliding_caption_migration_keeps_both_source_bodies(self):
        """Only a caption reference moves; the existing source ID and text are untouched."""
        page={'html':'<p data-content="stimulus_event_data"></p><p data-content="caption_event_data"></p>',
            'exercise':{'render_mode':'authored','stimuli':[{'id':'event_data','text':CONTEXT}],
                'captions':[{'id':'event_data','text':SECOND}]}}
        sources=prepare_stimuli(page,page['exercise'])
        self.assertEqual(sources[0],{'id':'event_data','text':CONTEXT})
        self.assertEqual(sources[1]['text'],SECOND);self.assertNotEqual(sources[1]['id'],'event_data')
        self.assertLessEqual(len(sources[1]['id']),24)
        self.assertIn('data-content="stimulus_event_data"',page['html'])
        self.assertIn('data-content="stimulus_'+sources[1]['id']+'"',page['html'])
        once=deepcopy(page);prepare_stimuli(page,page['exercise']);self.assertEqual(page,once)

    def test_local_context_binding_never_absorbs_commands_or_truncates(self):
        """Commands, real data cells, filled slots and incomplete oversized prose stay intact."""
        for markup in ('<p>'+CONTEXT+' Next, calculate the number of posters.</p>',
                       '<p>'+CONTEXT+' and write a pledge.</p>',
                       '<table><tr><th>Reading</th></tr><tr><td><p>'+CONTEXT+'</p></td></tr></table>',
                       '<p data-content="directions">'+CONTEXT+'</p>',
                       '<p>'+CONTEXT*5+'</p>'):
            page={'html':markup};exercise={'render_mode':'authored','directions':'Read the sources.','questions':[], 'stimuli':[]}
            before=deepcopy(exercise)
            bind_printed_context(page,exercise,{'simple_exercises_only':True,'stimulus_limit':8})
            self.assertEqual(page['html'],markup);self.assertEqual(exercise,before)

    def test_image_prompts_remove_workflow_lettering_and_campaign_signs(self):
        """Scene-first composition keeps meaningful subjects, plain props and the red ribbon."""
        story={'resource_type':'activity_pack','character_description':'UNRELATED OWL',
            'title':'Red Ribbon Week','grade_band':'3rd-4th'}
        scene='TEXT-FREE ARTWORK: Students in a school garden hold a banner reading "DRUG FREE" beside a poster.'
        prompt=_image_prompt(story,{'image_prompt':scene},'Text-free matte educational art; warm coral and teal colors.')
        self.assertTrue(prompt.startswith('Students in a school garden'))
        for unwanted in ('TEXT-FREE','DRUG FREE','UNRELATED OWL','SCENE:','STYLE:'):
            self.assertNotIn(unwanted,prompt.upper())
        self.assertIn('plain red fabric awareness ribbons',prompt)
        self.assertIn('plain unmarked surfaces',prompt)
        self.assertIn('older elementary-school',prompt)
        self.assertLessEqual(len(prompt),2048)
        solitary=_image_prompt(story,{'image_prompt':'A solitary red fabric ribbon on a plain background.'},'Matte illustration.')
        self.assertNotIn('requested people wear',solitary)
        self.assertNotIn('natural faces',solitary)
        self.assertNotIn('TEXT-FREE',solitary.upper())
        self.assertNotIn('Healthy Choices',text_free_scene('A sign reading Healthy Choices. Children in a garden.'))


if __name__=='__main__':unittest.main()
