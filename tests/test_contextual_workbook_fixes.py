"""Regress the published bullying workbook's semantics, repeated cards and headers."""
from copy import deepcopy
import json
import unittest

from weasyprint import HTML
from core.contextual_tasks import contextual_task_issues,inventory_return_issues,upstander_sequence_issues
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.creative_generator import validate_design
from core.image_generator import _image_prompt,text_free_scene
from core.simple_sources import collapse_repeated_cards,normalize_student_header
from core.student_workbook import check_response_width
from core.workbook_checks import printed_words
from core.workbook_review import review_varied_pack
from tests.test_student_workbook import evidence_page,workbook_config

RECORD=('Oak Creek Elementary handed out 245 blue kindness wristbands on Monday and 318 '
        'on Tuesday. On Wednesday, students returned 112 unneeded wristbands to the main office.')
CARDS=('Card A: Walk away calmly and tell a trusted adult what you observed. '
       'Card B: Notice when a classmate is treated unkindly. '
       'Card C: Check in with your classmate privately. '
       'Card D: Speak up safely if comfortable.')


def inventory_exercise():
    """Reproduce the published source and incorrectly named net-distribution result."""
    return {'render_mode':'authored','stimuli':[{'id':'event','text':RECORD}],
        'questions':[{'id':'1','prompt':'How many total kindness wristbands remain at the school?',
            'answer':'451 wristbands remain.','calculation':{'expression':'245+318-112','answer':'451'}},
            {'id':'2','prompt':'If the school ordered a total of 750 wristbands, how many wristbands are left in the storage box?',
             'answer':'299 wristbands.','calculation':{'expression':'750-245-318+112','answer':'299'}}]}


class ContextualWorkbookFixTests(unittest.TestCase):
    """Use real print checks for both bands and mandatory semantic repair offline."""

    def test_stock_and_distributed_quantities_are_not_interchangeable(self):
        """Correct subtraction cannot prove stock remaining without initial inventory."""
        exercise=inventory_exercise();issues=inventory_return_issues(exercise)
        self.assertEqual(len(issues),1);self.assertIn('Question 1',issues[0]);self.assertIn('still distributed',issues[0])
        exercise['questions'][0]['prompt']='How many wristbands are still with recipients after the returns?'
        self.assertEqual(inventory_return_issues(exercise),[])
        exercise['questions'][1]['calculation']['answer']='75'
        self.assertIn('= 299',str(inventory_return_issues(exercise)))

    def test_clear_stock_passes_and_unrelated_records_are_not_guessed(self):
        """Only complete two-delivery integer records enter the narrow local stock check."""
        exercise=inventory_exercise();exercise['stimuli'][0]['text']='The school started with 750 wristbands. '+RECORD+' All returns were restocked.'
        exercise['questions'][0].update(answer='299',calculation={'expression':'750-245-318+112','answer':'299'})
        self.assertEqual(inventory_return_issues(exercise),[])
        exercise['stimuli'][0]['text']=RECORD.replace('returned 112 unneeded','returned 112 damaged')
        self.assertEqual(inventory_return_issues(exercise),[])
        exercise['stimuli'][0]['text']='There were 750 wristbands in the box. '+RECORD
        self.assertEqual(inventory_return_issues(exercise),[])
        exercise['stimuli'][0]['text']=RECORD.replace('and 318 on Tuesday','and 318 bookmarks on Tuesday')
        self.assertEqual(inventory_return_issues(exercise),[])
        exercise['stimuli'][0]['text']='Students measured 245 millimeters and 318 millimeters. A friend returned 112 minutes later.'
        self.assertEqual(inventory_return_issues(exercise),[])

    def test_upstander_key_does_not_require_peer_actions_before_reporting(self):
        """The reported B,D,C,A key requires source/task repair, not just different letters."""
        exercise={'render_mode':'authored','directions':'Order the upstander actions into a chronological sequence.',
            'stimuli':[{'id':'cards','text':CARDS}], 'questions':[{'id':'1','prompt':'Write the letter sequence.','answer':'B, D, C, A'}]}
        self.assertIn('not merely change',str(upstander_sequence_issues(exercise)))
        exercise['questions'][0]['answer']='B, A, D, C. Optional peer support only when safe.'
        self.assertEqual(upstander_sequence_issues(exercise),[])
        exercise['directions']='Identify an example of safe support.'
        self.assertEqual(upstander_sequence_issues(exercise),[])

    def test_repeated_lists_preserve_distinct_content_and_are_idempotent(self):
        """Only complete same-letter same-body list repeats collapse."""
        second=CARDS.replace('Card A:','A.').replace('Card B:','B.').replace('Card C:','C.').replace('Card D:','D.')
        result=collapse_repeated_cards(CARDS+' '+second)
        self.assertEqual(result,second);self.assertEqual(collapse_repeated_cards(result),result)
        changed=CARDS+' '+second.replace('privately','after school')
        self.assertEqual(collapse_repeated_cards(changed),changed)
        self.assertEqual(collapse_repeated_cards('A. First action. B. Another action.'),'A. First action. B. Another action.')

    def test_duplicate_cards_and_narrow_headers_compile_in_both_bands(self):
        """Real rendering retains artwork, all answers and full-width student writing."""
        raw=evidence_page();exercise=raw['exercise']
        exercise['stimuli']=[{'id':'note_a','label':'Action Cards','text':
            'Card A: Notice the issue. Card B: Ask an adult. A. Notice the issue. B. Ask an adult.'}]
        exercise['directions']='Read the action cards.'
        exercise['questions']=[{'id':'1','prompt':'What does the student notice in Card A?',
            'answer':'The issue.','space_mm':35},{'id':'2','prompt':'Who does the student ask for help?',
            'answer':'An adult.','space_mm':35}]
        raw['html']=raw['html'].replace('<p data-content="stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"></p>','')
        raw['html']=raw['html'].replace('<p data-content="name"></p>','<div style="width:30mm"><p data-content="name"></p><p data-content="date"></p></div>')
        for band in ('3rd-4th','5th-6th'):
            page=validate_design(raw,12,quality=workbook_config(band,simple=True),expected_title='Safe Choices',require_coherent=True)
            words=printed_words(page['html'])
            self.assertEqual(words.count('Notice the issue.'),1)
            self.assertEqual(words.count('Name:'),1);self.assertEqual(words.count('Date:'),1)
            self.assertEqual(page['exercise']['questions'],exercise['questions'])
            doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_response_width(doc,page['quality_profile'])
            lines=[b for b in doc.pages[0]._page_box.descendants() if type(b).__name__=='LineBox'
                   and any(getattr(c,'text','').startswith(('Name:','Date:')) for c in b.descendants())]
            self.assertEqual(len(lines),2);self.assertAlmostEqual(lines[0].position_y,lines[1].position_y,places=2)

    def test_header_is_scoped_idempotent_and_preserves_media(self):
        """Legacy layouts and contaminated prefills remain subject to strict validation."""
        raw='<h1 data-content="title"></h1><p data-content="name"></p>'
        profile=workbook_config('3rd-4th',simple=True)
        result=normalize_student_header(raw,profile)
        self.assertEqual(normalize_student_header(result,profile),result)
        self.assertEqual(normalize_student_header(raw,{}),raw)
        for prefill in ('Name: include your team.','<img data-asset="weather"/>'):
            bad=raw.replace('<p data-content="name"></p>',f'<p data-content="name">{prefill}</p>')
            self.assertEqual(normalize_student_header(bad,profile),bad)

    def test_header_stays_inside_first_continuation_sheet(self):
        """Header movement cannot create a third root and break two-sheet rendering."""
        from core.content_binding import CanonicalTextContainers
        raw=('<div><h1 data-content="title"></h1><span data-content="name"></span></div>'
             '<div style="break-before:page"><h1 data-content="continuation_title"></h1></div>')
        profile=workbook_config('3rd-4th',simple=True)
        result=normalize_student_header(raw,profile)
        parser=CanonicalTextContainers({});parser.feed(result);parser.close()
        roots=[n for n in parser.root if isinstance(n,dict)]
        self.assertEqual(len(roots),2);self.assertTrue(all(n['tag']=='div' for n in roots))
        self.assertEqual(result.count('data-content="name"'),1);self.assertEqual(result.count('data-content="date"'),1)
        self.assertEqual(normalize_student_header(result,profile),result)

    def test_quoted_prop_lettering_is_removed_without_removing_scene(self):
        """Explicit lettering conflicts cannot outrank the text-free image instructions."""
        scene='Friendly children holding a sign reading "BULLYING PREVENTION MONTH" in a school garden.'
        cleaned=text_free_scene(scene)
        self.assertIn('blank sign',cleaned);self.assertIn('school garden',cleaned)
        self.assertNotIn('BULLYING PREVENTION MONTH',cleaned)
        prompt=_image_prompt({'resource_type':'activity_pack','character_description':'A student.'},
            {'image_prompt':scene},'Teal and coral.')
        self.assertTrue(prompt.startswith('TEXT-FREE ARTWORK'))
        self.assertNotIn('BULLYING PREVENTION MONTH',prompt);self.assertLessEqual(len(prompt),2048)
        self.assertEqual(text_free_scene('An owl beside a bridge.'),'An owl beside a bridge.')

    def test_model_approval_cannot_override_inventory_semantic_failure(self):
        """Two approving AI phases still require repair and re-review of a stock mismatch."""
        page={'title':'Kindness Counts','html':'<p>'+RECORD+'</p>','exercise':inventory_exercise()}
        pack={'grade_band':'3rd-4th','pages':[page]};repairs=[];calls=[]

        def ask(prompt,validate,label,tokens,**kwargs):
            """Approve model verdicts to exercise the mandatory local guard."""
            pages=json.loads(prompt.split('Activities:\n',1)[1]);calls.append(label)
            self.assertIn('Usable returns',prompt);self.assertIn('per-student',prompt)
            return validate({'pages':[{'page_number':p['page_number'],'source_accuracy':True,'no_answer_leak':True,
                'reason':'Consistent source.','issues':[],'question_checks':[{'id':q['id'],'source_support':True,
                    'skill_match':True,'grade_match':True,'answer_correct':True,'solution':'451 or 299 as requested.',
                    'reason':'Checked inventory.'} for q in p['exercise']['questions']]} for p in pages]})

        def repair(number,previous,issues):
            """Clarify the measured population while retaining the correct quantities."""
            self.assertIn('stock remaining is underdetermined',str(issues));repairs.append(number)
            fixed=deepcopy(previous)
            fixed['exercise']['questions'][0].update(prompt='How many wristbands are still with recipients after returns?',answer='451 still with recipients.')
            return fixed

        review_varied_pack(pack,ask,repair)
        self.assertEqual(repairs,[1]);self.assertEqual(len(calls),4)
        self.assertEqual(pack['content_checks']['repair_rounds'],1)
        self.assertEqual(contextual_task_issues(pack['pages'][0]),[])


if __name__=='__main__':unittest.main()
