"""Undeclared section headings bind locally while substantive content stays pinned."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,merge_layout_repair,validate_design
from core.creative_layout import activity_sheet_count
from core.section_headings import bind_section_headings
from tests.test_student_workbook import evidence_page,workbook_config
from tests.test_reading_bindings import plain_text


def section_page(text='',wrapped=False):
    """Reproduce an undeclared numbered heading beside an existing source."""
    page=evidence_page()
    heading='<span data-content="caption_sec_title_1">'+text+'</span>' if wrapped else text
    attrs='' if wrapped else ' data-content="caption_sec_title_1"'
    page['html']=page['html'].replace('<p data-content="stimulus_note_a"',
        '<h3'+attrs+' style="font-size:12pt;margin:0">'+heading+'</h3><p data-content="stimulus_note_a"')
    return page


class SectionHeadingTests(unittest.TestCase):
    """Run both grade contracts and retain geometry and all educational wording."""

    def ask(self,raw,band,title='Weather Evidence Lab'):
        """Use one mocked provider response and real print validation/recovery."""
        config=workbook_config(band);api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                quality=config,expected_title=title,require_coherent=True),'Activity design 2')
        self.assertEqual(api.chat.completions.create.call_count,1)
        return page

    def test_reported_heading_recovers_in_both_bands_after_one_response(self):
        """Complete printed headings and adjacent empty headings retain sources and answers."""
        for band in ('3rd-4th','5th-6th'):
            for text,wrapped in (('',False),('',True),('Weather <strong>Evidence</strong>',False)):
                with self.subTest(band=band,text=text,wrapped=wrapped):
                    raw=section_page(text,wrapped);before=deepcopy(raw);page=self.ask(raw,band)
                    heading='Weather Evidence' if text else 'Card A'
                    self.assertIn({'id':'sec_title_1','text':heading},page['exercise']['captions'])
                    self.assertEqual(raw,before);self.assertEqual(page['images'],raw['images'])
                    self.assertEqual(page['exercise']['stimuli'],raw['exercise']['stimuli'])
                    for new,old in zip(page['exercise']['questions'],raw['exercise']['questions']):
                        for key in ('id','prompt','answer'):self.assertEqual(new[key],old[key])
                    self.assertEqual(page['html'].count('height:35mm'),1)
                    self.assertEqual(page['html'].count('height:50mm'),1)
                    self.assertEqual(plain_text(page['html']).count(raw['exercise']['stimuli'][0]['text']),1)
                    if not text:self.assertEqual(plain_text(page['html']).count('Card A'),2) # heading + question reference

    def test_layout_repair_accepts_only_the_retained_source_label(self):
        """The second reported error is avoided without accepting new subject matter."""
        raw=section_page();raw['_recovery_config']=workbook_config('3rd-4th')
        correction={'html':raw['html'],'exercise':{'captions':[{'id':'sec_title_1','text':'Card A'}]}}
        result=merge_layout_repair(raw,correction)
        self.assertEqual(result['exercise']['captions'],correction['exercise']['captions'])
        self.assertEqual(result['exercise']['stimuli'],raw['exercise']['stimuli'])
        correction['exercise']['captions'][0]['text']='An invented historical heading'
        with self.assertRaisesRegex(ValueError,'complete wording already printed'):merge_layout_repair(raw,correction)

    def test_ambiguous_instructional_and_unknown_source_slots_are_not_invented(self):
        """No guesses from opaque IDs, image prompts, answers or question text."""
        config=workbook_config('3rd-4th')
        for markup in ('<h3 data-content="caption_sec_title_1"></h3>',
                       '<h3 data-content="caption_sec_title_1">Write the answer here.</h3>',
                       '<h3 data-content="caption_sec_title_1">Trace a path through the cards.</h3>',
                       '<h3 data-content="caption_sec_title_1">Design your banner in the box.</h3>',
                       '<h3 data-content="caption_sec_title_1"><img data-asset="weather"/></h3>',
                       '<h3 data-content="caption_sec_title_1"></h3><p data-content="stimulus_missing"></p>',
                       '<h3 data-content="caption_invented_label"></h3><p data-content="stimulus_note_a"></p>',
                       '<h3 data-content="caption_sec_title_1"></h3><div><p data-content="stimulus_note_a"></p><p data-content="stimulus_note_b"></p></div>',
                       '<h3 data-content="caption_sec_title_1">Evidence</h3>'*2):
            exercise=deepcopy(evidence_page()['exercise']);before=deepcopy(exercise)
            self.assertEqual(bind_section_headings(markup,exercise,config),markup)
            self.assertEqual(exercise,before)
        exercise=deepcopy(evidence_page()['exercise']);markup='<h3 data-content="caption_sec_title_1">Evidence</h3>'
        self.assertEqual(bind_section_headings(markup,exercise,{}),markup)
        exercise['render_mode']='exact';self.assertEqual(bind_section_headings(markup,exercise,config),markup)

    def test_idempotence_budget_and_neutral_unlabelled_source(self):
        """A valid source without a supplied label gets only an organizational label."""
        config=workbook_config('3rd-4th');raw=section_page();exercise=raw['exercise']
        del exercise['stimuli'][0]['label']
        once=bind_section_headings(raw['html'],exercise,config)
        self.assertEqual(exercise['captions'],[{'id':'sec_title_1','text':'Source'}])
        self.assertEqual(bind_section_headings(once,exercise,config),once)
        raw=section_page();raw['exercise']['captions']=[{'id':f'c{i}','text':f'Context {i}'} for i in range(24)]
        self.assertEqual(bind_section_headings(raw['html'],raw['exercise'],config),raw['html'])
        raw=section_page();raw['html']=raw['html'].replace('<h3 ','<p ').replace('</h3>','</p>')
        bind_section_headings(raw['html'],raw['exercise'],config)
        self.assertIn({'id':'sec_title_1','text':'Card A'},raw['exercise']['captions'])

    def test_uploaded_banner_keeps_both_motifs_template_and_writing(self):
        """Three images use bounded reference/response sheets instead of repeated overflow."""
        f=json.loads((Path(__file__).parent/'fixtures/banner_two_reference_motifs.json').read_text())
        for band in ('3rd-4th','5th-6th'):
            page=self.ask(deepcopy(f['page']),band,f['title'])
            self.assertEqual(activity_sheet_count(page),2)
            self.assertEqual(page['exercise']['stimuli'],f['page']['exercise']['stimuli'])
            self.assertEqual(page['exercise']['captions'],f['page']['exercise']['captions'])
            for new,old in zip(page['exercise']['questions'],f['page']['exercise']['questions']):
                for key in ('id','prompt','answer'):self.assertEqual(new[key],old[key])
            self.assertEqual([a['id'] for a in page['images']],['motif_one','motif_two','banner_template'])
            self.assertEqual(page['images'][-1]['local_template'],'banner_plan')
            self.assertIn('height:50mm',page['html']);self.assertIn('width:168mm;height:95.2mm',page['source_layout'])


if __name__=='__main__':unittest.main()
