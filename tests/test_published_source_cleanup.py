"""Regress source duplication, misleading references and unsupported facts in a published workbook."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.simple_sources import prepare_simple_sources
from core.workbook_checks import printed_words,unsupported_fact_claims
from core.workbook_review import review_varied_pack
from tests.test_student_workbook import evidence_page,workbook_config

LIBRARY=('Jane and her community volunteers collected 184 new reading books to distribute equally '
         'among 4 local neighborhood libraries. Later, they also shared 216 science magazines '
         'equally across 6 community centers.')
LAB=('Dr. Marie Curie\'s team prepared 14 science experiment kits for local classrooms. '
     'Each kit contained 12 specialized glass tubes for safe chemical testing.')
ART=('Alma Thomas was an inspiring art teacher and painter who lived in Washington, D.C. '
     'She developed bright abstract patterns inspired by nature and space. '
     'Alma Thomas used vibrant abstract color patterns to bring joy to community spaces and inspire young students.')
SUMMARY='Alma Thomas used vibrant abstract color patterns to bring joy to community spaces and inspire young students.'


def duplicated_page(kind='library'):
    """Recreate actual source wording in representative model-owned page markup."""
    page=evidence_page();body=LIBRARY if kind=='library' else LAB
    labels=('Source A','Library Text') if kind=='library' else ('Lab Note A','Card Text')
    page['exercise'].update(mechanic='resource_math',directions='Read the resource records. Solve both questions and show your work.',
        stimuli=[{'id':'note_a','label':labels[0],'text':body},{'id':'note_b','label':labels[1],'text':body}])
    if kind=='library':
        page['exercise']['questions']=[{'id':'1','prompt':'How many books does each library receive when 184 books are shared equally among 4 libraries?',
            'answer':'46 books.','calculation':{'expression':'184/4','answer':'46'},'space_mm':35},
            {'id':'2','prompt':'How many magazines does each center receive when 216 magazines are shared equally among 6 centers?',
             'answer':'36 magazines.','calculation':{'expression':'216/6','answer':'36'},'space_mm':35}]
    else:
        page['exercise']['stimuli'][0]['text']='Lab Note A '+body
        page['exercise']['questions']=[{'id':'1','prompt':'How many tubes are in 14 kits with 12 tubes each?',
            'answer':'168 tubes.','calculation':{'expression':'14*12','answer':'168'},'space_mm':35},
            {'id':'2','prompt':'How many tubes are in 23 kits with 12 tubes each?',
             'answer':'276 tubes.','calculation':{'expression':'23*12','answer':'276'},'space_mm':35}]
    return page


class PublishedSourceCleanupTests(unittest.TestCase):
    """Compile both grade bands with actual WeasyPrint checks and one provider response."""

    def ask(self,raw,band,title='Reading and Practice'):
        """Exercise native binding and measured local reflow without live API requests."""
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                quality=workbook_config(band,simple=True),expected_title=title,require_coherent=True),'Activity design 9')
        self.assertEqual(api.chat.completions.create.call_count,1)
        return page

    def test_actual_library_and_lab_duplicates_print_once_in_both_bands(self):
        """All numbers, distinct questions, correct answers, art and answer areas survive."""
        for band in ('3rd-4th','5th-6th'):
            for kind in ('library','lab'):
                with self.subTest(band=band,kind=kind):
                    raw=duplicated_page(kind);before=deepcopy(raw);page=self.ask(raw,band)
                    self.assertEqual(raw,before);self.assertEqual(page['images'],raw['images'])
                    self.assertEqual(len(page['exercise']['stimuli']),1)
                    self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])
                    text=printed_words(page['html']);self.assertEqual(text.count(LIBRARY if kind=='library' else LAB),1)
                    self.assertEqual(page['html'].count('height:35mm'),2)
                    self.assertNotIn('stimulus_note_b',page['source_layout'])

    def test_summary_label_and_caption_are_not_a_second_answer_before_the_reading(self):
        """The complete biography retains its facts while duplicated summary metadata disappears."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page();raw['exercise'].update(mechanic='reading',directions='Read the biography.',
                stimuli=[{'id':'note_a','label':SUMMARY,'text':ART}],captions=[{'id':'source_heading','text':'Source: '+SUMMARY}])
            raw['html']=raw['html'].replace('<p data-content="stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"></p>','')
            raw['html']=raw['html'].replace('<p data-content="stimulus_note_a"','<p data-content="caption_source_heading"></p><p data-content="stimulus_note_a"')
            raw['exercise']['questions']=[{'id':'1','prompt':'What inspired the patterns described in the biography?',
                'answer':'Nature and space.','space_mm':35},{'id':'2','prompt':'How did her work help community spaces and students?',
                'answer':'It brought joy and inspired young students.','space_mm':35}]
            page=self.ask(raw,band)
            self.assertEqual(page['exercise']['stimuli'][0]['text'],ART)
            self.assertEqual(page['exercise']['stimuli'][0]['label'],'Reading Source')
            self.assertEqual(printed_words(page['html']).count(SUMMARY),1)
            self.assertEqual(page['exercise']['captions'],[])

    def test_migrated_long_caption_cannot_reintroduce_the_same_source(self):
        """A generic long-body caption may migrate into stimuli, then consolidate safely."""
        raw=duplicated_page();raw['exercise']['stimuli'].pop()
        raw['html']=raw['html'].replace('<p data-content="stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"></p>',
            '<p data-content="caption_para_a"></p>')
        raw['exercise']['captions']=[{'id':'para_a','text':LIBRARY}]
        for band in ('3rd-4th','5th-6th'):
            page=self.ask(raw,band)
            self.assertEqual(len(page['exercise']['stimuli']),1)
            self.assertEqual(printed_words(page['html']).count(LIBRARY),1)

    def test_layout_references_and_underlined_word_are_neutral_and_task_preserving(self):
        """Only the presentation reference changes, never a number, answer or source fact."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page();raw['exercise']['directions']='Read the source cards on the right.'
            raw['exercise']['stimuli'][0]['text']='Advocacy means active support for a cause. The neighbors spoke up for the library.'
            raw['exercise']['questions'][0].update(prompt="Based on the source above, what does the underlined word 'advocacy' mean?",answer='Active support for a cause.')
            raw['exercise']['questions'][1].update(prompt='Read the source sentences on the left. What did the neighbors support?',answer='The library.')
            page=self.ask(raw,band);text=printed_words(page['html'])
            for wording in ('source above','on the left','on the right','underlined word'):self.assertNotIn(wording,text)
            self.assertIn("word 'advocacy'",text)
            self.assertEqual([q['answer'] for q in page['exercise']['questions']],[q['answer'] for q in raw['exercise']['questions']])
            self.assertEqual(page['exercise']['stimuli'],raw['exercise']['stimuli'])

    def test_cleanup_is_idempotent_and_conservative_about_distinct_accounts_and_work(self):
        """Identity references, comparisons, different facts and graphics prevent deletion."""
        config=workbook_config('3rd-4th',simple=True)
        for variant in ('referenced','comparison','different','media','partial'):
            raw=duplicated_page()
            if variant=='referenced':raw['exercise']['questions'][0]['prompt']+=' Use Library Text.'
            if variant=='comparison':raw['exercise']['directions']='Compare the two accounts.'
            if variant=='different':raw['exercise']['stimuli'][1]['text']+=' One center opens on Friday.'
            if variant=='media':raw['html']=raw['html'].replace('stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"></p>',
                'stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"><img data-asset="weather"/></p>')
            if variant=='partial':raw['html']=raw['html'].replace('stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"></p>',
                'stimulus_note_b" style="background-color:#FFF3D9;padding:2mm">Different printed context.</p>')
            before=deepcopy(raw);prepare_simple_sources(raw,raw['exercise'],config)
            self.assertEqual(raw,before,variant)
        raw=duplicated_page();prepare_simple_sources(raw,raw['exercise'],config);once=deepcopy(raw)
        prepare_simple_sources(raw,raw['exercise'],config);self.assertEqual(raw,once)
        raw=duplicated_page();before=deepcopy(raw);prepare_simple_sources(raw,raw['exercise'],workbook_config('3rd-4th'))
        self.assertEqual(raw,before)

    def test_passage_copy_can_merge_but_tables_and_response_panels_stay_intact(self):
        """An explicit source/table relationship and independent work surface cannot be swallowed."""
        raw=duplicated_page();raw['exercise']['passage']=LIBRARY
        raw['html']='<p data-content="passage"></p>'+raw['html']+'<div style="height:20mm;border:1px solid teal"></div>'
        raw['html']+='<table><tr><td data-content="caption_source_summary"></td></tr></table>'
        raw['exercise']['captions']=[{'id':'source_summary','text':LIBRARY}]
        prepare_simple_sources(raw,raw['exercise'],workbook_config('3rd-4th',simple=True))
        self.assertEqual(raw['exercise']['stimuli'],[]);self.assertEqual(raw['exercise']['passage'],LIBRARY)
        self.assertEqual(len(raw['exercise']['captions']),1)
        self.assertIn('height:20mm',raw['html']);self.assertIn('caption_source_summary',raw['html'])

    def test_named_park_cannot_be_proved_by_a_quote_that_only_says_tanzania(self):
        """The exact published FACT mismatch is caught independently of AI approval."""
        page={'exercise':{'stimuli':[{'text':'Jane Goodall lived among wild chimpanzees in Tanzania for decades to observe their daily behavior.'}],
            'questions':[{'id':'1','prompt':"Classify this statement based on the reading: 'Jane Goodall spent many years studying chimpanzees in Gombe Stream National Park.' Write the exact supporting text.",
                          'answer':'Classification: Fact. Jane Goodall lived among wild chimpanzees in Tanzania for decades.'}]}}
        self.assertIn('Gombe Stream National Park',str(unsupported_fact_claims(page)))
        page['exercise']['questions'][0]['answer']='False. The passage only identifies Tanzania.'
        self.assertEqual(unsupported_fact_claims(page),[])
        page['exercise']['questions'][0]['answer']='Fact.';page['exercise']['stimuli'][0]['text']+=' She studied in Gombe Stream National Park.'
        self.assertEqual(unsupported_fact_claims(page),[])

    def test_unsupported_named_fact_requires_repair_even_if_both_models_approve(self):
        """A known evidence gap cannot disappear behind permissive model review booleans."""
        text='Jane Goodall lived among wild chimpanzees in Tanzania for decades to observe their daily behavior.'
        page={'title':'Text Evidence','html':'<p>'+text+'</p>',
            'exercise':{'directions':'Read the source.','stimuli':[{'id':'bio','text':text}],
                'questions':[{'id':'1','prompt':"Based on the reading, classify this statement: 'Jane Goodall studied chimpanzees in Gombe Stream National Park.' Give supporting text.",
                    'answer':'Classification: Fact. '+text}]},'answers':'1. Fact.'}
        pack={'grade_band':'3rd-4th','pages':[page]};repaired=[]
        def ask(prompt,validate,label,tokens,**kwargs):
            """Approve semantically so the independent local evidence guard is exercised."""
            pages=json.loads(prompt.split('Activities:\n',1)[1])
            return validate({'pages':[{'page_number':p['page_number'],'source_accuracy':True,'no_answer_leak':True,
                'reason':'The passage supports the statement.','issues':[],
                'question_checks':[{'id':q['id'],'source_support':True,'skill_match':True,'grade_match':True,
                    'answer_correct':True,'solution':text,'reason':'The supplied text supports the answer.'}
                    for q in p['exercise']['questions']]} for p in pages]})
        def repair(number,previous,issues):
            """Remove only the unsupported location from the printed claim."""
            self.assertIn('Gombe Stream National Park',str(issues));repaired.append(number)
            fixed=deepcopy(previous);fixed['exercise']['questions'][0]['prompt']=fixed['exercise']['questions'][0]['prompt'].replace('Gombe Stream National Park','Tanzania')
            return fixed
        review_varied_pack(pack,ask,repair)
        self.assertEqual(repaired,[1]);self.assertEqual(pack['content_checks']['repair_rounds'],1)
        self.assertEqual(pack['pages'][0]['exercise']['stimuli'],page['exercise']['stimuli'])


if __name__=='__main__':unittest.main()
