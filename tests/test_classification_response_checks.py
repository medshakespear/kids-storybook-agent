"""Distinguish classification scaffolds and supplied evidence from completed student answers."""
from copy import deepcopy
import json
import unittest

from core.workbook_checks import classification_leaks,printed_words
from core.workbook_review import review_varied_pack


def classification_page(cell='Fact', *, header='Classification', source_header='Statement'):
    """Create a complete source/task/key with one separately owned student answer column."""
    return {'title':'Fact and Opinion','html':
        f'<table><tr><th>{source_header}</th><th>{header}</th></tr>'
        '<tr><td>The class collected 24 books.</td><td style="height:35mm;border:1px solid black">'
        +cell+'</td></tr></table>',
        'exercise':{'render_mode':'authored','directions':'Classify each statement as Fact or Opinion.',
            'stimuli':[{'id':'note','text':'The class collected 24 books.'}],
            'questions':[{'id':'1','prompt':'Classify the statement as fact or opinion and explain.',
                'answer':'Fact. The number of books can be counted.','space_mm':35}]},
        'answers':'1. Fact. The number of books can be counted.'}


class ClassificationResponseCheckTests(unittest.TestCase):
    """Never disable real answer-leak checks to bypass a publication failure."""

    def test_unselected_choices_and_empty_work_cells_are_not_leaks(self):
        """Printed alternatives help students choose without disclosing a chosen answer."""
        for cell in ('', '_______', 'Fact / Opinion', '[ ] Fact [ ] Opinion',
                     '☐ Fact   ☐ Opinion', 'Circle one: Fact or Opinion',
                     '<span>Fact</span> / <span>Opinion</span>', '☐ Fact'):
            page=classification_page(cell);before=deepcopy(page)
            with self.subTest(cell=cell):self.assertEqual(classification_leaks(page),[])
            self.assertEqual(page,before)

    def test_selected_choices_and_prefilled_explanations_report_exact_cell(self):
        """Actual solutions still fail and diagnostics identify where the repair belongs."""
        for cell in ('Fact', '[x] Fact [ ] Opinion', '☑ Fact ☐ Opinion', 'Fact / Opinion (circle Fact)',
                     'Fact, because the number can be counted.', 'Opinion: this expresses a preference.'):
            issues=classification_leaks(classification_page(cell))
            with self.subTest(cell=cell):
                self.assertEqual(len(issues),1)
                for text in ('table 1','data row 1','column 2','Classification','printed cell','final key'):
                    self.assertIn(text,issues[0])
        page=classification_page('✓',header='Fact')
        self.assertTrue(classification_leaks(page))

    def test_source_and_evidence_columns_do_not_get_misread_as_answers(self):
        """Category words inside retained evidence are not filled classification response cells."""
        for heading in ('Evidence Statement','Source Claim','Evidence'):
            page=classification_page('Fact / Opinion',source_header=heading)
            page['html']=page['html'].replace('The class collected 24 books.',
                'The writer calls the opening claim an opinion in the provided paragraph.')
            self.assertEqual(classification_leaks(page),[])
        page=classification_page('Fact, because the count is recorded.',header='Supporting Evidence')
        self.assertTrue(classification_leaks(page))
        page=classification_page('Fact',header='Fact or Opinion')
        self.assertTrue(classification_leaks(page))

    def test_other_category_pairs_unselected_options_and_worked_examples(self):
        """Multiword classifications obey the same selected-versus-unselected distinction."""
        page=classification_page('☐ Direct Observation / ☐ Cultural Interpretation')
        page['exercise']['directions']='Classify as Direct Observation or Cultural Interpretation.'
        page['exercise']['questions'][0]['prompt']='Classify each source and explain.'
        self.assertEqual(classification_leaks(page),[])
        page['html']=page['html'].replace('☐ Direct Observation / ☐ Cultural Interpretation',
            'Cultural interpretation: the scent symbolizes guidance.')
        self.assertTrue(classification_leaks(page))
        page['html']=page['html'].replace('<th>Statement</th>','<th>Worked Example</th>')
        self.assertEqual(classification_leaks(page),[])

    def test_layout_tables_and_merged_headers_defer_ambiguous_column_ownership(self):
        """A layout-row paragraph or spanning banner is not an answer-column header."""
        page=classification_page('An opinion can express a preference.',header='A reading about facts and opinions')
        self.assertEqual(classification_leaks(page),[])
        page['html']=('<table><tr><th colspan="2">Classification</th></tr>'
            '<tr><td>A fact can be checked.</td><td>_______</td></tr></table>')
        self.assertEqual(classification_leaks(page),[])

    def approve(self,prompt,validate,label,tokens,**kwargs):
        """Approve all model checks so local guard behavior is independently exercised."""
        pages=json.loads(prompt.split('Activities:\n',1)[1])
        self.assertIn('Unselected Fact/Opinion',prompt)
        return validate({'pages':[{'page_number':p['page_number'],'source_accuracy':True,'no_answer_leak':True,
            'reason':'The source supports the task.','issues':[],
            'question_checks':[{'id':q['id'],'source_support':True,'skill_match':True,'grade_match':True,
                'answer_correct':True,'solution':'Fact; books can be counted.','reason':'The count is checkable.'}
                for q in p['exercise']['questions']]} for p in pages]})

    def test_valid_scaffolds_publish_without_model_repair_in_both_bands(self):
        """The prior false-positive shape no longer spends a repair call or blocks publication."""
        for band in ('3rd-4th','5th-6th'):
            pack={'grade_band':band,'pages':[classification_page('☐ Fact ☐ Opinion')]}
            def repair(*args):
                """Fail if a legitimate unselected choice is treated as a disclosure."""
                self.fail('No repair is needed for unselected categories')
            review_varied_pack(pack,self.approve,repair)
            self.assertEqual(pack['content_checks']['repair_rounds'],0)

    def test_real_leak_repairs_only_answer_cell_and_keeps_evidence_and_key(self):
        """Bounded review can fix an actual disclosure with an exact cell diagnostic."""
        for band in ('3rd-4th','5th-6th'):
            original=classification_page('Fact');pack={'grade_band':band,'pages':[deepcopy(original)]};repairs=[]
            def repair(number,previous,issues):
                """Represent a targeted repair that blanks the cell but retains its work area."""
                self.assertIn('column 2',str(issues));repairs.append(number)
                result=deepcopy(previous);result['html']=result['html'].replace('>Fact</td>','></td>')
                return result
            review_varied_pack(pack,self.approve,repair)
            self.assertEqual(repairs,[1]);self.assertEqual(pack['content_checks']['repair_rounds'],1)
            fixed=pack['pages'][0]
            self.assertEqual(fixed['exercise'],original['exercise']);self.assertEqual(fixed['answers'],original['answers'])
            self.assertIn('The class collected 24 books.',printed_words(fixed['html']))
            self.assertIn('height:35mm',fixed['html'])

    def test_unrepaired_leak_still_blocks_publication(self):
        """A second model approval cannot override a student answer remaining on the page."""
        pack={'grade_band':'3rd-4th','pages':[classification_page('Fact')]}
        with self.assertRaisesRegex(ValueError,'table 1, data row 1, column 2'):
            review_varied_pack(pack,self.approve,lambda number,page,issues:page)
        self.assertNotIn('content_checks',pack)


if __name__=='__main__':unittest.main()
