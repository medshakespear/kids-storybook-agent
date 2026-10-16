"""Simple written workbooks exclude crafts and check grade math and source-grounded keys."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from core.creative_generator import validate_design,validate_plan
from core.simple_exercises import check_simple_activity,check_grade_math
from core.varied_generator import generate_varied_pack
from core.pipeline import load_grade_config
from core.workbook_checks import classification_leaks,printed_words
from core.workbook_review import blind_pages,review_varied_pack,validate_independent
from tests.test_student_workbook import evidence_page,workbook_config
from tests.test_book_types import mixed_plan


class SimpleExerciseTests(unittest.TestCase):
    """Use production profiles for both supported grade bands."""

    def test_wrapper_applies_only_scoped_simple_policy(self):
        """The QCM/global config is unchanged and all generation guidance excludes craft work."""
        config=load_grade_config();before=deepcopy(config)
        for band in ('3rd-4th','5th-6th'):
            with patch('core.varied_generator.generate_creative_pack',return_value={'pages':[]}) as generate:
                generate_varied_pack('Halloween Craft',band,config)
            profile=generate.call_args.args[2][band]
            self.assertTrue(profile['simple_exercises_only']);self.assertEqual(profile['grade_band'],band)
            self.assertIn('No drawing, templates',generate.call_args.kwargs['source_context'])
            self.assertEqual(config,before)

    def test_drawing_and_templates_are_rejected_before_art_generation(self):
        """A harmless book theme cannot override a ban on student craft actions."""
        for band in ('3rd-4th','5th-6th'):
            for prompt in ('Draw a skull.','Read the passage. Then carefully sketch a banner.',
                           'Complete the blank right half.','Color the picture.',
                           'Design a poster about your answer.','Complete the activity by drawing a leaf.'):
                page=evidence_page();page['exercise']['questions'][0]['prompt']=prompt
                with self.subTest(band=band,prompt=prompt),self.assertRaisesRegex(ValueError,'Simple workbook'):
                    validate_design(page,12,quality=workbook_config(band,simple=True),expected_title='Written Evidence',require_coherent=True)
            page=evidence_page();page['images'][0]['local_template']='skull_symmetry'
            with self.assertRaisesRegex(ValueError,'drawing templates'):
                validate_design(page,12,quality=workbook_config(band,simple=True),expected_title='Written Evidence',require_coherent=True)
        exercise={'render_mode':'authored','mechanic':'inference','directions':'Read about how families decorate their homes.',
                  'questions':[{'prompt':'Draw a conclusion about the character using one detail from the text.'}]}
        check_simple_activity(exercise)

    def test_planner_cannot_sneak_a_craft_through_a_generic_mechanic(self):
        """Banned work is caught in the plan, including third-person action descriptions."""
        plan=mixed_plan()
        self.assertEqual(len(validate_plan(plan,10,require_coherent=True,require_variety=True,student_workbook=True,simple_exercises_only=True)['pages']),10)
        plan['pages'][0]['activity_concept']='Students draw a lantern and explain its colors.'
        with self.assertRaisesRegex(ValueError,'Simple workbook'):
            validate_plan(plan,10,require_coherent=True,require_variety=True,student_workbook=True,simple_exercises_only=True)

    def test_grade_math_rejects_observed_weak_addition_and_accepts_useful_work(self):
        """Directions stay simple while upper-elementary arithmetic has meaningful demand."""
        exercise={'stimuli':[]}
        cases={'3rd-4th':(['4+3','12-5','4+3+2'],['245-128','12*4','84/7','4*24-38']),
               '5th-6th':(['4+3','24-8','245-128','12*4','84/7','4+3+2'],['2450-1284','48*12','0.75*8','3/4+1/8','325*7/20'])}
        for band,(bad,good) in cases.items():
            for expression in bad:
                with self.subTest(band=band,bad=expression),self.assertRaisesRegex(ValueError,'below'):
                    check_grade_math({'id':'1','calculation':{'expression':expression}},exercise,band)
            for expression in good:
                check_grade_math({'id':'1','calculation':{'expression':expression}},exercise,band)

    def test_standalone_inferred_math_cannot_bypass_grade_check(self):
        """The same rule applies when Python supplies omitted literal calculation metadata."""
        for band in ('3rd-4th','5th-6th'):
            page=evidence_page();page['exercise']['questions'][0].update(prompt='Calculate 4 + 3.',answer='7')
            with self.assertRaisesRegex(ValueError,'below'):
                validate_design(page,12,quality=workbook_config(band,simple=True),expected_title='Math Practice',require_coherent=True)

    def test_wrong_math_key_and_wrong_operation_remain_errors(self):
        """Grade checks never weaken exact numeric or printed-operation verification."""
        for band in ('3rd-4th','5th-6th'):
            for expression,answer in (('4*24-38','56'),('4*24+38','134')):
                page=evidence_page();q=page['exercise']['questions'][0]
                q.update(prompt='Calculate 4 * 24 - 38.',answer=answer,calculation={'expression':expression,'answer':answer})
                with self.assertRaisesRegex(ValueError,'incorrect|does not solve'):
                    validate_design(page,12,quality=workbook_config(band,simple=True),expected_title='Math Practice',require_coherent=True)

    def test_real_classification_leak_is_detected_but_source_cards_are_not_answers(self):
        """Reproduce the published table's filled cultural-interpretation reasoning cells."""
        page=evidence_page();page['exercise']['directions']='Classify each statement as a Direct Observation or Cultural Interpretation.'
        page['html']+='<table><tr><th>Statement Card</th><th>Classification</th><th>Evidence / Reasoning</th></tr><tr><td>Card B</td><td>________</td><td>Cultural interpretation linking scent to guiding souls</td></tr></table>'
        self.assertTrue(classification_leaks(page))
        page['html']=page['html'].replace('Cultural interpretation linking scent to guiding souls','________')
        self.assertEqual(classification_leaks(page),[])
        page['html']=page['html'].replace('<th>Statement Card</th>','<th>Worked Example</th>').replace('<td>________</td>','<td>Cultural Interpretation</td>')
        self.assertEqual(classification_leaks(page),[])


class BlindKeyTests(unittest.TestCase):
    """The independent solver cannot see the key it is meant to verify."""

    def pack(self):
        """Use the published family-comparison mismatch, with complete printed sources."""
        page={'title':'Family Traditions','html':'<p>Source A: At home we share bread and family stories.</p><p>Source B: At the cemetery we bring sugar skulls and light candles.</p>',
            'exercise':{'render_mode':'authored','mechanic':'compare_texts','directions':'Read both sources.',
                'stimuli':[{'id':'a','text':'At home we share bread and family stories.'},{'id':'b','text':'At the cemetery we bring sugar skulls and light candles.'}],
                'questions':[{'id':'1','prompt':'Where does Source B gather?','answer':'At home with floating candle boats.','space_mm':35}]},
            'answers':'1. At home with floating candle boats.'}
        return {'grade_band':'3rd-4th','pages':[page]}

    def rows(self,pages,**changes):
        """Return complete verdicts with a solution grounded in the printed source."""
        raw={'pages':[{'page_number':p['page_number'],'source_accuracy':True,'no_answer_leak':True,
            'reason':'The printed sources support a clear answer.','issues':[],
            'question_checks':[{'id':q['id'],'source_support':True,'skill_match':True,
                'answer_correct':True,'grade_match':True,'solution':'At the cemetery.',
                'reason':'Source B explicitly states the cemetery location.'} for q in p['exercise']['questions']]}
            for p in pages]}
        for row in raw['pages']:
            for check in row['question_checks']:check.update(solution='At the cemetery.',**changes)
        return raw

    def test_blind_payload_removes_answers_calculations_and_artwork_guesses(self):
        """Neither the authored answer nor calculation metadata reaches the first phase."""
        page=self.pack()['pages'][0];page['page_number']=1;page['student_content']=printed_words(page['html'])
        page['exercise']['questions'][0]['calculation']={'answer':123,'expression':'100+23'}
        page['answer_key']='At home with floating candle boats.';page['planned_intent']={'answer':'Secret'}
        page['exercise']['goal']='Secret unprinted solution'
        public=blind_pages([page]);encoded=json.dumps(public)
        self.assertNotIn('floating candle boats',encoded);self.assertNotIn('calculation',encoded)
        self.assertNotIn('Secret',encoded);self.assertNotIn('answer_key',encoded)
        self.assertIn('cemetery',encoded)

    def test_wrong_key_is_repaired_and_both_phases_recheck_only_that_page(self):
        """The observed invented location cannot be approved by copying the existing answer."""
        pack=self.pack();calls=[]
        def ask(prompt,validate,label,tokens,**kwargs):
            """Solve from the source first; compare with the retained key second."""
            pages=json.loads(prompt.split('Activities:\n',1)[1]);calls.append(label)
            rows=self.rows(pages)
            if label=='Workbook independent solutions':
                self.assertNotIn('floating candle boats',prompt)
            elif 'floating candle boats' in pages[0]['answer_key']:
                rows['pages'][0]['question_checks'][0].update(answer_correct=False,reason='The key invents home and boats; Source B says cemetery.')
            return validate(rows)
        def repair(number,page,issues):
            """Correct the key without changing the source, question or response space."""
            self.assertEqual(number,1);self.assertIn('invents',str(issues));fixed=deepcopy(page)
            fixed['exercise']['questions'][0]['answer']='At the cemetery.';fixed['answers']='1. At the cemetery.'
            return fixed
        review_varied_pack(pack,ask,repair)
        self.assertEqual(calls,['Workbook independent solutions','Workbook content review']*2)
        self.assertEqual(pack['pages'][0]['exercise']['questions'][0]['answer'],'At the cemetery.')
        self.assertEqual(pack['content_checks']['repair_rounds'],1)

    def test_blind_unsupported_task_cannot_be_overruled_by_positive_comparison(self):
        """Insufficient evidence and grade mismatch force repair even if the key reviewer agrees."""
        for flag in ('source_support','grade_match'):
            pack=self.pack()
            def ask(prompt,validate,label,tokens,**kwargs):
                """Return a persistent independent failure and a permissive comparison."""
                pages=json.loads(prompt.split('Activities:\n',1)[1]);rows=self.rows(pages)
                if label=='Workbook independent solutions':rows['pages'][0]['question_checks'][0][flag]=False
                return validate(rows)
            with self.assertRaisesRegex(ValueError,'still needs correction'):
                review_varied_pack(pack,ask,lambda n,p,issues:p)
            self.assertNotIn('content_checks',pack)


if __name__=='__main__':unittest.main()
