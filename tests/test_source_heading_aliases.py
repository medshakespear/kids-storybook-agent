"""Source heading aliases must never trigger fabricated missing-passage repairs."""
from copy import deepcopy
import unittest

from core.activity_stimuli import normalize_stimulus_ids, merge_missing_sources
from core.creative_generator import validate_design
from core.student_workbook import adjacent_source_labels
from tests.test_student_workbook import evidence_page, workbook_config
from tests.test_reading_bindings import plain_text


class SourceHeadingAliasTests(unittest.TestCase):
    """Recover only explicit known labels; preserve genuine missing-source failures."""

    def page(self):
        """Reproduce source_one_label beside two existing supporting passages."""
        page=evidence_page()
        for source,old,new in zip(page['exercise']['stimuli'],('note_a','note_b'),('source_one','source_two')):
            source['id']=new
            page['html']=page['html'].replace('stimulus_'+old,'stimulus_'+new)
            page['html']=page['html'].replace('<p data-content="stimulus_'+new+'"',
                '<h3 style="margin:0;font-size:12pt"><span data-content="stimulus_'+new+'_label"></span></h3>'
                '<p data-content="stimulus_'+new+'"')
        return page

    def test_existing_labels_compile_without_another_source_in_both_grades(self):
        """Real PDF validation keeps full sources, readable art and 35/50mm responses."""
        for band in ('3rd-4th','5th-6th'):
            raw=self.page();original=deepcopy(raw);config=workbook_config(band)
            result=validate_design(raw,12,quality=config,expected_title='Weather Evidence Lab',require_coherent=True)
            self.assertEqual(raw,original)
            self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
            self.assertEqual(len(result['exercise']['stimuli']),2)
            text=plain_text(result['html'])
            for source in original['exercise']['stimuli']:
                question_mentions=sum(q['prompt'].count(source['label']) for q in original['exercise']['questions'])
                self.assertEqual(text.count(source['label']),1+question_mentions)
                self.assertEqual(text.count(source['text']),1)
            self.assertIn('height:35mm',result['html']);self.assertIn('height:50mm',result['html'])
            for q,old in zip(result['exercise']['questions'],original['exercise']['questions']):
                for key in ('id','prompt','answer'):self.assertEqual(q[key],old[key])

    def test_normalization_is_idempotent_and_missing_source_merge_ignores_labels(self):
        """The heading cannot become a third passage during a different source repair."""
        page=self.page();normalize_stimulus_ids(page,page['exercise']);once=deepcopy(page)
        normalize_stimulus_ids(page,page['exercise']);self.assertEqual(page,once)
        self.assertEqual(merge_missing_sources(self.page(),self.page()),once)
        self.assertEqual(len(page['exercise']['captions']),2)

    def test_ambiguous_or_unsupplied_label_text_is_not_guessed(self):
        """Conflicting wording, media, absent labels and real suffix IDs stay explicit."""
        for extra in ('Different label','<img data-asset="weather"/>','<span data-content="title"></span>'):
            page=self.page();page['html']=page['html'].replace('stimulus_source_one_label"></span>',
                'stimulus_source_one_label">'+extra+'</span>')
            normalize_stimulus_ids(page,page['exercise'])
            self.assertIn('data-content="stimulus_source_one_label"',page['html'])
        page=self.page();del page['exercise']['stimuli'][0]['label']
        normalize_stimulus_ids(page,page['exercise'])
        self.assertIn('data-content="stimulus_source_one_label"',page['html'])
        page=self.page();page['exercise']['stimuli'].append({'id':'source_one_label','text':'A genuine third source.'})
        normalize_stimulus_ids(page,page['exercise'])
        self.assertIn('data-content="stimulus_source_one_label"',page['html'])
        page=self.page();page['exercise']['captions']=[{'id':'source_one_label','text':'Conflicting heading'}]
        normalize_stimulus_ids(page,page['exercise'])
        self.assertIn('data-content="stimulus_source_one_label"',page['html'])

    def test_genuine_missing_source_still_needs_supplied_evidence(self):
        """Suffix similarity alone never invents content or removes a source slot."""
        page=self.page();page['html']+='<p data-content="stimulus_unknown_label"></p>'
        with self.assertRaisesRegex(ValueError,'one nonempty source for unknown_label'):
            merge_missing_sources(page,page)

    def test_wrapper_with_other_wording_does_not_suppress_source_label(self):
        """Only a single formatting path between a bound heading and its card qualifies."""
        sources=[{'id':'a','label':'Card A','text':'Evidence.'}]
        captions=[{'id':'a_label','text':'Card A'}]
        for prefix in ('Other words ', '<img data-asset="scene"/>'):
            markup='<h3>'+prefix+'<span data-content="caption_a_label"></span></h3><p data-content="stimulus_a"></p>'
            self.assertEqual(adjacent_source_labels(markup,sources,captions,{'student_workbook':True}),set())


if __name__=='__main__':unittest.main()
