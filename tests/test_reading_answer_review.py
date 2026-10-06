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
                                  reason=q['explanation']) for n,q in enumerate(unit['questions'],1)]}

    def test_solver_cannot_see_the_key_or_explanation(self):
        """Independent solving removes answer priming and creates matching key explanations."""
        def ask(prompt, validate, label, *args, **kwargs):
            """Inspect exactly what the blind reviewer receives."""
            payload = json.loads(prompt.split('\n')[-1])
            self.assertEqual(set(payload), {'paragraphs','questions'})
            for q in payload['questions']:
                self.assertEqual(set(q), {'number','prompt','options'})
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
            if label.endswith('answer repair'):
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
            if label.endswith('answer repair'):
                return validate({'repairs':[{'number':2,'question':deepcopy(self.unit['questions'][1])}]})
            return validate(self.solutions(self.unit,broken=True))
        with self.assertRaisesRegex(ActivityGenerationError,'PDF not published'):
            verify_question_answers(self.unit,self.config,'Reading',ask=ask)
        self.assertEqual(len(calls),5)

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
