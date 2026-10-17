"""Regress the reviewed Halloween sequence and matching activity in both bands."""
from copy import deepcopy
import json
import unittest

from core.sequence_matching import shuffle_matching_rows,sequence_matching_issues,revealed_matching_tables
from core.workbook_tasks import page_tree,node_words,tables_in,own_rows,row_cells
from core.workbook_review import review_varied_pack
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page


def sequence_page():
    """Reproduce the printed First/Then/Next/Finally cards and wrong published key."""
    source=('A. Finally, families walk along the glowing path. '
        'B. First, volunteers sweep the pathway. '
        'C. Next, visitors gather for warm cider. '
        'D. Then, before sunset, children place pumpkins along the fence.')
    return {'title':'Sequence of Events','html':'<p data-content="stimulus_steps"></p>',
        'exercise':{'render_mode':'authored','mechanic':'ordering','directions':'Read the steps.',
            'stimuli':[{'id':'steps','label':'Festival Steps','text':source}],
            'questions':[{'id':'1','prompt':'Write the correct chronological letter sequence.',
                'answer':'B, D, A, C','space_mm':35},
                {'id':'2','prompt':'What does before sunset tell you?',
                 'answer':'It is before evening.','space_mm':35}]},'answers':'1. B, D, A, C'}


def matching_page():
    """A two-column table reveals all partners; the follow-up invents historical causes."""
    raw=evidence_page()
    pairs=[('1. Bonfires','A. Hilltop fires mark the harvest end.'),('2. Guising','B. People perform in costume for treats.'),
           ('3. Turnip Lanterns','C. People carve root vegetables.'),('4. Community Fair','D. Neighbors share food and games.')]
    table='<table style="width:80mm;table-layout:fixed"><tr><th>Term</th><th>Description</th></tr>'+''.join(
        f'<tr><td>{a}</td><td>{b}</td></tr>' for a,b in pairs)+'</table>'
    a=raw['html'].index('<p data-content="stimulus_note_a"');b=raw['html'].index('</td>',a)
    raw['html']=raw['html'][:a]+table+raw['html'][b:]
    raw['exercise'].update(mechanic='text_matching',directions='Match the four numbered customs to their description letters.',stimuli=[])
    raw['exercise']['questions']=[{'id':'1','prompt':'Match terms 1 to 4 to their description letters A to D.',
        'answer':'1-A, 2-B, 3-C, 4-D','space_mm':35},
        {'id':'2','prompt':'Explain why harvest traditions have changed over time.',
         'answer':'People adopted new crops and modern safety standards.','space_mm':35}]
    return raw


class SequenceMatchingTests(unittest.TestCase):
    """Keep wording and geometry intact while correcting the two scoped defects."""

    def test_wrong_final_card_cannot_pass(self):
        """Finally is last even if an AI reviewer approved the wrong sequence."""
        page=sequence_page()
        self.assertIn('sequence key contradicts',str(sequence_matching_issues(page)))
        page['exercise']['questions'][0]['answer']='B, D, C, A'
        self.assertEqual(sequence_matching_issues(page),[])
        page['exercise']['questions'][0]['answer']='D, B, C, A'
        self.assertIn('sequence key contradicts',str(sequence_matching_issues(page)))
        # Then/Next alone are not enough to assign middle ranks locally.
        page['exercise']['questions'][0]['answer']='B, C, D, A'
        self.assertEqual(sequence_matching_issues(page),[])

    def test_matching_rotation_preserves_every_choice_and_key(self):
        """Shift complete cells, not labels or meanings, and never shuffle twice."""
        page=matching_page();original=deepcopy(page)
        self.assertTrue(revealed_matching_tables(page_tree(page),page['exercise']))
        shuffle_matching_rows(page,page['exercise'],{'simple_exercises_only':True})
        self.assertEqual(page['exercise'],original['exercise'])
        self.assertFalse(revealed_matching_tables(page_tree(page),page['exercise']))
        table=next(t for t in tables_in(page_tree(page)) if len(own_rows(t))==5)
        choices=[node_words(row_cells(r)[1],page['exercise'])[0] for r in own_rows(table)[1:]]
        self.assertEqual(choices,['B','C','D','A'])
        once=deepcopy(page);shuffle_matching_rows(page,page['exercise'],{'simple_exercises_only':True});self.assertEqual(page,once)
        untouched=deepcopy(original);shuffle_matching_rows(untouched,untouched['exercise'],{});self.assertEqual(untouched,original)

    def test_native_matching_reflow_in_both_grades(self):
        """One mocked completion, real WeasyPrint measurements, original question/key/art."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                raw=matching_page();before=deepcopy(raw)
                page=fixtures.CompleteStudentTaskTests().ask(raw,band)
                self.assertEqual(raw,before)
                self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])
                self.assertEqual(page['images'],raw['images'])
                self.assertFalse(revealed_matching_tables(page_tree(page),page['exercise']))
                self.assertIn('supply no reasons',str(sequence_matching_issues(page)))

    def test_supported_comparison_and_causal_readings_remain_valid(self):
        """A changed task must be grounded; genuinely printed causes remain allowed."""
        page=matching_page();shuffle_matching_rows(page,page['exercise'],{'simple_exercises_only':True})
        page['exercise']['questions'][1].update(prompt='How does guising differ from a community fair?',
            answer='Guising involves performing in costume; a fair includes shared food and games.')
        self.assertEqual(sequence_matching_issues(page),[])
        page['exercise']['questions'][1]['prompt']='Explain why harvest traditions have changed.'
        page['html']+='<p>Traditions changed because new crops became available.</p>'
        self.assertEqual(sequence_matching_issues(page),[])

    def test_bounded_review_repairs_only_sequence_key_and_matching_followup(self):
        """Even blanket AI approval cannot bypass these local checks."""
        for band in ('3rd-4th','5th-6th'):
            sequence=sequence_page();matching=matching_page()
            shuffle_matching_rows(matching,matching['exercise'],{'simple_exercises_only':True})
            matching['title']='Tradition Matching';matching['answers']=' '.join(q['answer'] for q in matching['exercise']['questions'])
            pack={'grade_band':band,'pages':[sequence,matching]};before=deepcopy(pack);repairs=[]
            def ask(prompt,validate,label,tokens,**kwargs):
                """Supply approving AI verdicts; local defects must still force repair."""
                pages=json.loads(prompt.split('Activities:\n',1)[1])
                return validate({'pages':[{'page_number':p['page_number'],'source_accuracy':True,'no_answer_leak':True,
                    'reason':'Approved.','issues':[],'question_checks':[{'id':q['id'],'source_support':True,'skill_match':True,
                    'grade_match':True,'answer_correct':True,'solution':'Approved.','reason':'Approved.'} for q in p['exercise']['questions']]} for p in pages]})
            def repair(number,page,issues):
                """Change the wrong key or unsupported follow-up, retaining other student content."""
                fixed=deepcopy(page);repairs.append(number)
                if number==1:
                    self.assertIn('sequence key contradicts',str(issues))
                    fixed['exercise']['questions'][0]['answer']='B, D, C, A'
                else:
                    self.assertIn('supply no reasons',str(issues))
                    fixed['exercise']['questions'][1].update(prompt='How does guising differ from a community fair?',
                        answer='Guising involves performing in costume; a fair includes shared food and games.')
                fixed['answers']=' '.join(q['answer'] for q in fixed['exercise']['questions'])
                return fixed
            review_varied_pack(pack,ask,repair)
            self.assertEqual(repairs,[1,2]);self.assertEqual(pack['content_checks']['repair_rounds'],1)
            self.assertEqual(pack['pages'][0]['exercise']['stimuli'],before['pages'][0]['exercise']['stimuli'])
            self.assertEqual(pack['pages'][1]['html'],before['pages'][1]['html'])
            self.assertEqual(pack['pages'][1]['exercise']['questions'][0],before['pages'][1]['exercise']['questions'][0])


if __name__=='__main__':unittest.main()
