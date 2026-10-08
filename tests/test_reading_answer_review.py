"""Regression coverage for broken answer options in generated reading PDFs."""
from copy import deepcopy
import json
import unittest

from core.activity_generator import ActivityGenerationError
from core.pipeline import load_grade_config
from core.reading_answer_review import verify_question_answers
from core.image_generator import _image_prompt
from core.reading_generator import render_cover
from tests.test_reading_generator import reading_fixture


class ReadingAnswerReviewTests(unittest.TestCase):
    """Exercise blind solving, frozen repairs, failure bounds and illustration prompts."""

    def setUp(self):
        """Use the production grade contract and original test reading."""
        self.unit = reading_fixture()
        self.config = load_grade_config()['3rd-4th']

    def solutions(self, unit, broken=False):
        """Supply numbered independent answers through the real review validator."""
        return {'solutions':[dict(number=n,answer='NONE' if broken and n==2 else q['answer'],
                                  reason=q['explanation'],quality_issues=[]) for n,q in enumerate(unit['questions'],1)]}

    def test_solver_cannot_see_the_key_or_explanation(self):
        """Independent solving removes answer priming and creates matching key explanations."""
        def ask(prompt, validate, label, *args, **kwargs):
            """Inspect exactly what the blind reviewer receives."""
            payload = json.loads(prompt.split('\n')[-1])
            self.assertEqual(set(payload), {'paragraphs','questions'})
            for q in payload['questions']:
                self.assertEqual(set(q), {'number','prompt','options','skill'})
            return validate(self.solutions(self.unit))
        self.assertEqual(verify_question_answers(self.unit,self.config,'Reading',ask=ask),self.unit)

    def test_no_correct_option_is_repaired_and_solved_again(self):
        """Reproduce a selected option borrowed from another question, as in the upload."""
        broken = deepcopy(self.unit)
        broken['questions'][1]['options']['A']='His daughter refused to learn that many signs.'
        before, calls = deepcopy(broken), []
        def ask(prompt, validate, label, *args, **kwargs):
            """Reject the unrelated choice, then return one precise repair."""
            calls.append(label)
            if label.endswith(('answer repair','fresh question replacement')):
                return validate({'repairs':[{'number':2,'question':deepcopy(self.unit['questions'][1])}]})
            return validate(self.solutions(self.unit,broken=len(calls)==1))
        result=verify_question_answers(broken,self.config,'Reading',ask=ask)
        self.assertEqual(result,self.unit)
        self.assertEqual(broken,before)
        self.assertEqual(len(calls),3)
        for index in (0,2,3,4):
            self.assertEqual(result['questions'][index],before['questions'][index])

    def test_bad_repairs_cannot_publish_after_bounded_attempts(self):
        """An unresolved NONE answer stops the pipeline instead of publishing a bad key."""
        calls=[]
        def ask(prompt, validate, label, *args, **kwargs):
            """Simulate a provider repeatedly failing to repair a semantic defect."""
            calls.append(label)
            if label.endswith(('answer repair','fresh question replacement')):
                return validate({'repairs':[{'number':2,'question':deepcopy(self.unit['questions'][1])}]})
            return validate(self.solutions(self.unit,broken=True))
        with self.assertRaisesRegex(ActivityGenerationError,'PDF not published'):
            verify_question_answers(self.unit,self.config,'Reading',ask=ask)
        self.assertEqual(len(calls),7)

    def test_quality_fault_is_repaired_even_when_selected_answer_is_correct(self):
        """A correct letter does not excuse literal inference or absurd distractors."""
        calls=[]
        def ask(prompt,validate,label,*args,**kwargs):
            """Flag quality once, then verify the scoped repair independently."""
            calls.append(label)
            if label.endswith(('answer repair','fresh question replacement')):
                self.assertIn('inference must require',prompt)
                return validate({'repairs':[{'number':3,'question':deepcopy(self.unit['questions'][2])}]})
            result=self.solutions(self.unit)
            if len(calls)==1:
                result['solutions'][2]['quality_issues']=['literal_inference','implausible_distractors']
            return validate(result)
        self.assertEqual(verify_question_answers(self.unit,self.config,'Reading',ask=ask),self.unit)
        self.assertEqual(len(calls),3)

    def test_repair_uses_scoped_choice_and_explanation_length_helpers(self):
        """Reproduce the overlong choice/explanation failures in the uploaded run."""
        from unittest.mock import patch
        calls, wording_calls=[],[]
        def wording(prompt,validate,label,*args,**kwargs):
            """Only shorten the failed canonical field without truncating other content."""
            wording_calls.append(label)
            replacements={'2:A':self.unit['questions'][1]['options']['A']} if 'choice-length' in label else {'2:explanation':self.unit['questions'][1]['explanation']}
            return validate({'replacements':replacements})
        def ask(prompt,validate,label,*args,**kwargs):
            """Return an otherwise correct repair with the reported long fields."""
            calls.append(label)
            if label.endswith('answer repair'):
                question=deepcopy(self.unit['questions'][1])
                question['options']['A']+=' Extra explanations make this option unnecessarily long.'
                question['explanation']+=' This explanation repeats a long description of the reading instead of providing a concise answer. '*2
                return validate({'repairs':[{'number':2,'question':question}]})
            return validate(self.solutions(self.unit,broken=len(calls)==1))
        with patch('core.reading_generator.ask_json',side_effect=wording):
            result=verify_question_answers(self.unit,self.config,'Reading',ask=ask)
        self.assertEqual(result,self.unit)
        self.assertEqual(len(wording_calls),2)
        self.assertEqual(len(calls),3)

    def test_persistent_question_gets_fresh_scoped_replacement(self):
        """Two failed repairs no longer immediately discard the entire workbook."""
        calls=[]
        replacement=deepcopy(self.unit['questions'][1])
        replacement['prompt']='Why should a class check how sunlight changes?'
        def ask(prompt,validate,label,*args,**kwargs):
            """The fourth independent solve accepts a genuinely new question."""
            calls.append(label)
            if label.endswith('fresh question replacement'):
                payload=json.loads(prompt.split('\n')[-1])
                self.assertEqual([q['number'] for q in payload['accepted_questions']],[1,3,4,5])
                self.assertNotIn('questions',payload)
                return validate({'repairs':[{'number':2,'question':replacement}]})
            if label.endswith('answer repair'):
                return validate({'repairs':[{'number':2,'question':deepcopy(self.unit['questions'][1])}]})
            return validate(self.solutions(self.unit,broken=len(calls)<7))
        with self.assertLogs('core.reading_answer_review',level='WARNING') as logs:
            result=verify_question_answers(self.unit,self.config,'Reading',ask=ask)
        self.assertEqual(result['questions'][1]['prompt'],replacement['prompt'])
        self.assertEqual(result['paragraphs'],self.unit['paragraphs'])
        self.assertEqual(len(calls),7)
        self.assertIn('expected A, reviewer NONE',' '.join(logs.output))
        for index in (0,2,3,4):
            self.assertEqual(result['questions'][index],self.unit['questions'][index])

    def test_solver_rejects_duplicate_or_missing_numbers(self):
        """The independent solution cannot accidentally bind one question to another."""
        def ask(prompt, validate, *args, **kwargs):
            """Exercise numbering failures against the real parser."""
            malformed=self.solutions(self.unit)
            malformed['solutions'][1]['number']=1
            with self.assertRaisesRegex(ValueError,'each once'):
                validate(malformed)
            return validate(self.solutions(self.unit))
        verify_question_answers(self.unit,self.config,'Reading',ask=ask)

    def test_verbose_review_reason_does_not_block_either_grade(self):
        """Accept verbose internal reasoning without expanding printed explanations."""
        for band in ('3rd-4th', '5th-6th'):
            with self.subTest(band=band):
                config = load_grade_config()[band]
                unit = reading_fixture(band)
                calls = []
                def ask(prompt, validate, label, *args, **kwargs):
                    """Return valid answers with unnecessarily long reviewer reasons."""
                    calls.append(label)
                    result = self.solutions(unit)
                    for solution in result['solutions']:
                        solution['reason'] = 'The passage supports this option through several details. ' * 25
                    return validate(result)
                self.assertEqual(verify_question_answers(unit,config,'Reading',ask=ask),unit)
                self.assertEqual(len(calls),1)

    def test_verbose_defect_reason_is_preserved_for_repair(self):
        """Length normalization must never suppress a NONE answer or quality defect."""
        reason = 'The options do not answer the printed question. ' * 5
        calls = []
        def ask(prompt, validate, label, *args, **kwargs):
            """Verify the full diagnostic reaches the scoped repair request."""
            calls.append(label)
            if label.endswith('answer repair'):
                self.assertIn(reason.strip(),prompt)
                return validate({'repairs':[{'number':2,'question':deepcopy(self.unit['questions'][1])}]})
            result = self.solutions(self.unit,broken=len(calls)==1)
            if len(calls)==1:
                result['solutions'][1]['reason'] = reason
            return validate(result)
        self.assertEqual(verify_question_answers(self.unit,self.config,'Reading',ask=ask),self.unit)
        self.assertEqual(len(calls),3)

    def test_empty_or_nontext_review_reason_still_fails(self):
        """Malformed reasons cannot silently bypass answer review."""
        def ask(prompt, validate, *args, **kwargs):
            """Check required diagnostic content independently of its length."""
            for reason in (None, '', '   ', 123):
                malformed = self.solutions(self.unit)
                malformed['solutions'][0]['reason'] = reason
                with self.assertRaisesRegex(ValueError,'nonempty text'):
                    validate(malformed)
            return validate(self.solutions(self.unit))
        verify_question_answers(self.unit,self.config,'Reading',ask=ask)

    def ambiguity_fixture(self, band):
        """Model the reported two-equivalent-options defect in an inference question."""
        unit=reading_fixture(band)
        unit['questions'][3].update(answer='B', options={
            'A':'Investigate the growing conditions.',
            'B':'Check the conditions where it grows.',
            'C':'Use the same watering plan everywhere.',
            'D':'Never record slow growth.'})
        return unit

    def ambiguity_replacement(self, unit, version=0):
        """Provide a full distinct replacement with real retained passage evidence."""
        question=deepcopy(unit['questions'][3])
        question.update(prompt='Why might students reconsider a gardening plan'+(' '+str(version) if version else '')+'?',
                        options={'A':'Use new observations to revise a plan.',
                                 'B':'Choose a site using only appearances.',
                                 'C':'Keep the first plan regardless of evidence.',
                                 'D':'Apply one watering rule to every site.'},
                        answer='A', evidence='students ask questions, collect evidence, and revise their plans.',
                        explanation='New observations can give students reasons to revise a plan.')
        if version:
            question['options']={letter:value+' '+str(version) for letter,value in question['options'].items()}
        return question

    def test_ambiguity_immediately_replaces_full_question_for_both_grades(self):
        """AMBIGUOUS plus literal inference rewrites all four options, then blind-solves."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                unit=self.ambiguity_fixture(band)
                before=deepcopy(unit)
                replacement=self.ambiguity_replacement(unit)
                accepted=deepcopy(unit)
                accepted['questions'][3]=replacement
                calls=[]
                def ask(prompt,validate,label,*args,**kwargs):
                    """Force the production rewrite validator through the reported failure."""
                    calls.append(label)
                    if label.endswith('fresh question replacement'):
                        payload=json.loads(prompt.split('\n')[-1])
                        requirement=payload['replacement_requirements'][0]
                        self.assertEqual(requirement['number'],4)
                        self.assertEqual(requirement['skill'],'inference')
                        self.assertIn(unit['questions'][3]['options']['A'],requirement['rejected_options'])
                        self.assertIn('Check EACH choice',prompt)
                        unchanged=deepcopy(replacement)
                        unchanged['prompt']=unit['questions'][3]['prompt']
                        with self.assertRaisesRegex(ValueError,'new question stem'):
                            validate({'repairs':[{'number':4,'question':unchanged}]})
                        recycled=deepcopy(replacement)
                        recycled['options']['B']='CHECK THE CONDITIONS WHERE IT GROWS!'
                        with self.assertRaisesRegex(ValueError,'ALL four choices'):
                            validate({'repairs':[{'number':4,'question':recycled}]})
                        return validate({'repairs':[{'number':4,'question':replacement}]})
                    result=self.solutions(accepted)
                    if len(calls)==1:
                        result['solutions'][3].update(answer='AMBIGUOUS',quality_issues=['literal_inference'],reason='Both A and B say to check the conditions.')
                    return validate(result)
                result=verify_question_answers(unit,load_grade_config()[band],'Reading',ask=ask)
                self.assertEqual(result,accepted)
                self.assertEqual(unit,before)
                self.assertEqual(len(calls),3)
                self.assertNotIn('Reading answer repair',calls)

    def test_ambiguity_gets_extra_bounded_fresh_recovery(self):
        """A fourth blind-review failure can recover instead of discarding the workbook."""
        unit=self.ambiguity_fixture('3rd-4th')
        calls=[]
        replacements=[]
        def ask(prompt,validate,label,*args,**kwargs):
            """Fail four solves, then accept a new fully rewritten question."""
            calls.append(label)
            if label.endswith('fresh question replacement'):
                question=self.ambiguity_replacement(unit,len(replacements)+1)
                replacements.append(question)
                return validate({'repairs':[{'number':4,'question':question}]})
            current=deepcopy(unit)
            if replacements:
                current['questions'][3]=replacements[-1]
            result=self.solutions(current)
            if len(replacements)<4:
                result['solutions'][3].update(answer='AMBIGUOUS',reason='Two choices remain defensible.')
            return validate(result)
        result=verify_question_answers(unit,self.config,'Reading',ask=ask)
        self.assertEqual(len(calls),9)
        self.assertEqual(len(replacements),4)
        self.assertEqual(result['questions'][3],replacements[-1])
        self.assertEqual(result['paragraphs'],unit['paragraphs'])
        for index in (0,1,2,4):
            self.assertEqual(result['questions'][index],unit['questions'][index])

    def test_persistent_ambiguity_is_still_blocked(self):
        """Six failed blind solves cannot publish an ambiguous PDF."""
        unit=self.ambiguity_fixture('3rd-4th')
        replacements=[]
        calls=[]
        def ask(prompt,validate,label,*args,**kwargs):
            """Repeated bad semantic judgments remain bounded despite fresh rewrites."""
            calls.append(label)
            if label.endswith('fresh question replacement'):
                question=self.ambiguity_replacement(unit,len(replacements)+1)
                replacements.append(question)
                return validate({'repairs':[{'number':4,'question':question}]})
            result=self.solutions(unit)
            result['solutions'][3].update(answer='AMBIGUOUS',reason='Both choices are supported.')
            return validate(result)
        with self.assertRaisesRegex(ActivityGenerationError,'5 bounded.*PDF not published'):
            verify_question_answers(unit,self.config,'Reading',ask=ask)
        self.assertEqual(len(calls),11)
        self.assertEqual(len(replacements),5)

    def test_cover_uses_scene_not_title_and_activity_image_path(self):
        """Prevent the title entering image prompts or the recurring story-cast style."""
        plan={'title':'Voices of Native Nations Reading Workbook','overview':'Read original texts.',
              'topics':['A Three Sisters garden with corn, beans and squash.']}
        cover=render_cover(plan,'3rd-4th',self.config,5,scene_prompt='A Three Sisters garden with corn, beans and squash.')
        scene=cover['images'][0]['prompt']
        self.assertNotIn(plan['title'],scene)
        self.assertIn('No lettering',scene)
        self.assertIn('not generic costumes',scene)
        prompt=_image_prompt({'resource_type':'activity_pack','character_description':''},
                             {'image_prompt':scene},self.config['illustration_style'])
        self.assertNotIn("Children's book illustration",prompt)
        self.assertIn('SCENE is authoritative',prompt)


if __name__=='__main__':
    unittest.main()
