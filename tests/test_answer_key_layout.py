"""Regress valid long keys and measured single-page answer-sheet fitting."""
import html
import unittest
from unittest.mock import patch
from copy import deepcopy

from weasyprint import HTML
from core.creative_generator import validate_design, compact_shared_answers
from core.creative_layout import answer_key_markup, fit_answer_key, document_markup, data_only_fetcher, check_document, preflight_pack, pack_markup
from core.pipeline import load_grade_config
from core.task_visuals import answer_text
from tests.coherent_fixtures import authored_page
from tests.test_creative_design import creative_fixture


def long_key_pack(length=130):
    """Create a bounded older-grade key that exceeds the old per-page character cap."""
    pack=creative_fixture('5th-6th')
    for number,page in enumerate(pack['pages'],1):
        answer=('Identify the hazard, explain how it could cause harm and suggest a practical safe action that a student can take with adult help. '*2)[:length]
        page['answers']=' '.join(f'{i}. Example {number}-{i}: {answer}' for i in range(1,5))
    return pack


class AnswerKeyLayoutTests(unittest.TestCase):
    """Keep all solutions and student typography while adapting only the final sheet."""

    def setUp(self):
        """Use the grade band and maximum item count from the reported failure."""
        self.config=load_grade_config()['5th-6th']

    def test_valid_individual_answers_do_not_hit_conflicting_total_limit(self):
        """Four individually valid answers above 650 combined characters remain bound and intact."""
        page=authored_page(mechanic='fire safety reasoning')
        answer=('Accept a reasoned answer that identifies a hazard, explains why it is unsafe, and proposes a practical action with adult help. '+
                'The action should protect other students and keep exits clear.')[:175]
        page['exercise']['questions']=[dict(id=str(i),prompt=f'Explain safety choice {i}.',answer=answer,space_mm=0) for i in range(1,5)]
        page['html']+=''.join(f'<p data-content="question_{i}"></p>' for i in range(2,5))
        result=validate_design(page,11,quality=self.config,expected_title='Fire Safety Choices',require_coherent=True)
        self.assertGreater(len(result['answers']),650)
        self.assertEqual(result['answers'].count(answer),4)
        self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])

    def test_per_answer_limit_still_bounds_content(self):
        """Removing the conflicting aggregate cap does not allow unbounded individual content."""
        page=authored_page();page['exercise']['questions'][0]['answer']='x'*181
        with self.assertRaisesRegex(ValueError,'answer/criterion'):
            validate_design(page,11,quality=self.config,expected_title='Fire Safety',require_coherent=True)

    def test_measured_compaction_keeps_every_answer_and_one_page(self):
        """A key too long for the standard layout fits without dropping or rewriting text."""
        pack=long_key_pack(100)
        standard=HTML(string=document_markup([answer_key_markup(pack)],11),url_fetcher=data_only_fetcher).render()
        self.assertGreater(len(standard.pages),1)
        original=[answer_text(page) for page in pack['pages']]
        fit_answer_key(pack,self.config)
        self.assertIn(pack['answer_key_layout'],{'compact','dense'})
        markup=answer_key_markup(pack,pack['answer_key_layout'])
        check_document(HTML(string=document_markup([markup],11),url_fetcher=data_only_fetcher).render(),1)
        for key in original:
            self.assertIn(html.escape(key),markup)
        self.assertEqual([answer_text(p) for p in pack['pages']],original)

    def test_full_book_keeps_final_sheet_and_student_layouts(self):
        """Preview and final composition share the same selected key style and page count."""
        pack=long_key_pack(100)
        originals=[deepcopy(page['html']) for page in pack['pages']]
        preflight_pack(pack,self.config)
        check_document(HTML(string=pack_markup(pack,self.config,preview=True),url_fetcher=data_only_fetcher).render(),12)
        self.assertEqual([page['html'] for page in pack['pages']],originals)
        self.assertEqual(pack_markup(pack,self.config,preview=True).count('<h1>Answer Key</h1>'),1)

    def test_shared_compaction_preserves_tasks_and_exact_ids(self):
        """The optional overflow repair updates canonical answers without replacing student work."""
        raw=authored_page();raw['exercise']['questions'][0]['answer']='Accept a design that provides sunlight and access for watering. Explain how both needs are met.'
        page=validate_design(raw,11,quality=self.config,expected_title='Garden Design',require_coherent=True)
        page.update(title='Garden Design',page_number=1)
        pack={'pages':[page]}
        original_html=page['html'];original_exercise=deepcopy(page['exercise'])
        def ask(prompt,validate,*args):
            """Validate the proposed concise criterion through production checks."""
            return validate({'pages':[{'page_number':1,'answers':[{'id':'1','answer':'Accept a shelter allowing sunlight and watering access.'}]}]})
        with patch('core.creative_generator.ask_json',side_effect=ask):
            compact_shared_answers(pack,self.config)
        updated=pack['pages'][0]
        self.assertEqual(updated['html'],original_html)
        self.assertEqual(updated['images'],page['images'])
        self.assertEqual(updated['exercise']['questions'][0]['prompt'],original_exercise['questions'][0]['prompt'])
        self.assertEqual(updated['answer_key_original']['1'],original_exercise['questions'][0]['answer'])
        self.assertIn('watering access',updated['answers'])
        self.assertEqual(updated['exercise']['questions'][0]['id'],'1')

    def test_shared_compaction_cannot_lose_a_question(self):
        """Missing answer IDs trigger repair rather than silently deleting a solution."""
        raw=authored_page()
        page=validate_design(raw,11,quality=self.config,expected_title='Garden Design',require_coherent=True)
        page.update(title='Garden Design',page_number=1)
        pack={'pages':[page]}
        def ask(prompt,validate,*args):
            """Emulate an invalid provider response through its real validator."""
            return validate({'pages':[{'page_number':1,'answers':[]}]})
        with patch('core.creative_generator.ask_json',side_effect=ask),self.assertRaisesRegex(ValueError,'every shared question'):
            compact_shared_answers(pack,self.config)
        self.assertEqual(pack['pages'][0],page)

    def test_unfit_key_reports_final_sheet_without_clipping(self):
        """Excessive content fails with a key-specific diagnosis instead of clipping or removing answers."""
        pack=creative_fixture('5th-6th')
        for page in pack['pages']: page['answers']='Extremely long response. '*500
        before=[p['answers'] for p in pack['pages']]
        with self.assertRaisesRegex(ValueError,'Final answer sheet cannot fit'):
            fit_answer_key(pack,self.config)
        self.assertEqual([p['answers'] for p in pack['pages']],before)
