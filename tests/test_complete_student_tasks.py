"""Regress published matching labels, quantity wording, table keys and cramped inventories."""
from copy import deepcopy
import json
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,validate_design,layout_contract
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document,activity_sheet_count
from core.response_schemas import design_schema
from core.simple_sources import remove_orphan_separators
from core.student_workbook import check_data_table_width,check_response_width
from core.varied_generator import clarified_workbook_title
from core.image_generator import text_free_scene
from core.workbook_checks import printed_words
from core.workbook_review import review_varied_pack
from core.workbook_tasks import task_coverage_issues,repeated_inventory_sources
from tests.test_student_workbook import evidence_page,workbook_config


def inventory_page(scale=1, *, extra=''):
    """Reproduce the published four-column inventory and its complete pipe-text copy."""
    raw=evidence_page();records=[('Paper Bats',145,90,15),('Ghost Cutouts',210,135,25),('Paper Stars',180,110,20)]
    records=[(label,*(n*scale for n in values)) for label,*values in records]
    copy='Supply Tracking Table: '+' '.join(f'{label} | Initial: {a} | Distributed: {b} | Returned: {c}.' for label,a,b,c in records)+extra
    raw['exercise'].update(mechanic='data_interpretation',directions='Use the supply table. All returned items are usable and restocked. Solve both questions.',
        stimuli=[{'id':'supply_log','label':'Supply Log','text':copy}])
    raw['exercise']['questions']=[{'id':'1','prompt':'How many Ghost Cutouts are available after distribution and returns?',
        'answer':f'{100*scale} Ghost Cutouts.','calculation':{'expression':f'{210*scale}-{135*scale}+{25*scale}','answer':str(100*scale)},'space_mm':35},
        {'id':'2','prompt':'Compare the available Paper Bats and Paper Stars. Which has more, and how many?',
         'answer':f'Paper Stars have {90*scale}; Paper Bats have {70*scale}.','calculation':{'expression':f'{180*scale}-{110*scale}+{20*scale}','answer':str(90*scale)},'space_mm':35}]
    table=('<table style="width:80mm;table-layout:fixed"><tr><th>Craft Item</th><th>Initial Stock</th><th>Distributed</th><th>Returned (Usable)</th></tr>'+
        ''.join('<tr>'+''.join(f'<td>{v}</td>' for v in row)+'</tr>' for row in records)+'</table>')
    a=raw['html'].index('<p data-content="stimulus_note_a"');b=raw['html'].index('</td>',a)
    raw['html']=raw['html'][:a]+table+raw['html'][b:]
    raw['html']=raw['html'].replace('<p data-content="directions"></p>','<p data-content="directions"></p><p data-content="stimulus_supply_log"></p>')
    return raw


def incomplete_classification():
    """Four student rows need answers even when only two row discussions are registered."""
    rows=['The display has three panels.','Pumpkins look friendlier than ghosts.',
          'The borders are orange and purple.','Purple is the most exciting color.']
    return {'title':'Fact or Opinion','html':'<table><tr><th>Statement</th><th>Fact or Opinion</th><th>Supporting Evidence</th></tr>'+
        ''.join(f'<tr><td>{s}</td><td></td><td></td></tr>' for s in rows)+'</table>',
        'exercise':{'render_mode':'authored','directions':'Classify each statement in the table as Fact or Opinion.',
            'stimuli':[{'id':'display','text':'The display has three panels. The borders are orange and purple.'}],
            'questions':[{'id':'1','prompt':'Classify statement 1 and explain.','answer':'Fact. The three panels are recorded.','space_mm':35},
                         {'id':'2','prompt':'Classify statement 2 and explain.','answer':'Opinion. Friendlier expresses a judgment.','space_mm':35}]},
        'answers':'1. Fact. 2. Opinion.'}


class CompleteStudentTaskTests(unittest.TestCase):
    """Use real production contracts and offline text-provider fixtures for both bands."""

    def ask(self,raw,band,title='Reading Display Data'):
        """Require one provider response followed by actual measured local layout recovery."""
        config=workbook_config(band,simple=True);api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(12,12,coherent=True),lambda x:validate_design(x,12,quality=config,
                expected_title=title,require_coherent=True),'Activity design 7',response_schema=design_schema(
                    {'render_mode':'authored','mechanic':raw['exercise']['mechanic']},config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        return page

    def test_matching_references_require_actual_source_numbers(self):
        """The published unnumbered design terms do not satisfy a 1-4 reference."""
        page={'html':'<p>Balance Contrast Focal Point Alignment</p><p>A. Neat. B. Focus. C. Even. D. Different.</p>',
            'exercise':{'render_mode':'authored','questions':[{'id':'1','prompt':'Match each numbered design term (1-4) to its description.',
                'answer':'1:C, 2:D, 3:B, 4:A.'}]}}
        self.assertIn('printed source labels',str(task_coverage_issues(page)))
        page['html']='<p>1. Balance 2. Contrast 3. Focal Point 4. Alignment</p>'
        self.assertEqual(task_coverage_issues(page),[])
        page['html']='<ol><li>Balance</li><li>Contrast</li><li>Focal Point</li><li>Alignment</li></ol>'
        self.assertEqual(task_coverage_issues(page),[])

    def test_items_and_points_must_name_the_same_quantity(self):
        """Correct multiplication cannot validate an answer in the wrong requested unit."""
        page={'html':'<p>Four matching items.</p>','exercise':{'render_mode':'authored','questions':[{'id':'1',
            'prompt':'Compute the total number of matched items if each item earns 145 points.',
            'answer':'Total points: 580','calculation':{'expression':'4*145','answer':'580'}}]}}
        self.assertIn('number of items',str(task_coverage_issues(page)))
        page['exercise']['questions'][0]['prompt']='Compute the total points earned for four correct matches at 145 points each.'
        self.assertEqual(task_coverage_issues(page),[])

    def test_all_table_rows_need_key_coverage(self):
        """Row actions in directions are not lost just because the schema has two questions."""
        page=incomplete_classification();self.assertIn('all 4 data rows',str(task_coverage_issues(page)))
        page['exercise']['questions'][0].update(prompt='Classify all four rows and provide evidence.',
            answer='1. Fact: three panels. 2. Opinion: friendlier is a judgment. 3. Fact: border colors are recorded. 4. Opinion: most exciting is a preference.')
        self.assertEqual(task_coverage_issues(page),[])

    def test_complete_table_copy_is_removed_but_extra_evidence_and_changed_values_survive(self):
        """Consolidation requires every ordered item and value, not superficial similarity."""
        raw=inventory_page();self.assertEqual(repeated_inventory_sources(raw,raw['exercise']),{'supply_log'})
        raw['exercise']['stimuli'][0]['text']+=' All returns were checked for damage.'
        self.assertEqual(repeated_inventory_sources(raw,raw['exercise']),set())
        raw=inventory_page();raw['exercise']['stimuli'][0]['text']=raw['exercise']['stimuli'][0]['text'].replace('Initial: 145','Initial: 146')
        self.assertEqual(repeated_inventory_sources(raw,raw['exercise']),set())

    def test_inventory_reflows_wide_with_exact_values_and_writing_space_in_both_bands(self):
        """The actual narrow-table shape is corrected locally with its useful artwork retained."""
        for band,scale in (('3rd-4th',1),('5th-6th',10)):
            raw=inventory_page(scale);before=deepcopy(raw);page=self.ask(raw,band)
            self.assertEqual(raw,before);self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])
            self.assertEqual(page['exercise']['stimuli'],[]);self.assertEqual(page['images'],raw['images'])
            self.assertNotIn('Supply Tracking Table:',printed_words(page['html']))
            self.assertEqual(printed_words(page['html']).count('Ghost Cutouts'),2)  # table and question; no student-page key
            doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
            self.assertLessEqual(activity_sheet_count(page),2);check_document(doc,activity_sheet_count(page))
            check_data_table_width(doc,page['quality_profile']);check_response_width(doc,page['quality_profile'])

    def test_layout_pipes_disappear_but_sources_tables_and_work_survive(self):
        """Standalone decorative pipes cannot leak into published headings or page bottoms."""
        raw='<h1 data-content="title"></h1>|<div data-content="question_1"></div><p>|</p>'
        cleaned=remove_orphan_separators(raw,{'simple_exercises_only':True})
        self.assertNotIn('|',cleaned);self.assertEqual(remove_orphan_separators(cleaned,{'simple_exercises_only':True}),cleaned)
        for markup in ('<p data-content="stimulus_note">A | B</p>','<table><tr><td>|</td></tr></table>',
                       '<p>Read A | B carefully.</p>','<div style="height:35mm;border:1px solid black"></div>'):
            self.assertEqual(re.sub(r'<(\w+) >',r'<\1>',remove_orphan_separators(markup,{'simple_exercises_only':True})),markup)
        self.assertEqual(remove_orphan_separators(raw,{}),raw)

    def test_decor_niche_title_clarifies_the_product_without_changing_other_titles(self):
        """A workbook cannot imply that it contains a ready-to-cut bulletin-board kit."""
        self.assertEqual(clarified_workbook_title('Halloween Bulletin Board'),'Halloween Bulletin Board: Reading & Math')
        for title in ('Garden Science','Halloween Activities','Halloween Bulletin Board: Reading & Math'):
            self.assertEqual(clarified_workbook_title(title),title)
        self.assertIn('unlettered picture board',text_free_scene('Children beside a classroom bulletin board.'))

    def test_model_approval_cannot_skip_two_unanswered_table_rows(self):
        """Bounded semantic repair must return a complete key for the whole printed task."""
        for band in ('3rd-4th','5th-6th'):
            pack={'grade_band':band,'pages':[incomplete_classification()]};calls=[]
            def ask(prompt,validate,label,tokens,**kwargs):
                """Approve AI verdicts to exercise the independent local completeness check."""
                self.assertIn('Audit ALL student actions',prompt)
                pages=json.loads(prompt.split('Activities:\n',1)[1])
                return validate({'pages':[{'page_number':p['page_number'],'source_accuracy':True,'no_answer_leak':True,
                    'reason':'Sources support the task.','issues':[],'question_checks':[{'id':q['id'],'source_support':True,
                        'skill_match':True,'grade_match':True,'answer_correct':True,'solution':'Fact or opinion with evidence.',
                        'reason':'Category supported.'} for q in p['exercise']['questions']]} for p in pages]})
            def repair(number,page,issues):
                """Include every row rather than hiding missing rows from the student task."""
                self.assertIn('all 4 data rows',str(issues));calls.append(number);fixed=deepcopy(page)
                fixed['exercise']['questions'][0].update(prompt='Classify all four table statements and give a reason.',
                    answer='1. Fact: panel count. 2. Opinion: friendlier. 3. Fact: recorded colors. 4. Opinion: most exciting.')
                fixed['answers']=' '.join(q['answer'] for q in fixed['exercise']['questions'])
                return fixed
            review_varied_pack(pack,ask,repair)
            self.assertEqual(calls,[1]);self.assertEqual(pack['content_checks']['repair_rounds'],1)
            self.assertIn('4. Opinion',pack['pages'][0]['answers'])


if __name__=='__main__':unittest.main()
