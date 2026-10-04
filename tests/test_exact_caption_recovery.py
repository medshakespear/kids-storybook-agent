"""Regress captions containing computed puzzle instructions or additional actions."""
from copy import deepcopy
import unittest
from core.creative_generator import validate_design, merge_exact_wording_repair
from core.exact_caption_recovery import remove_duplicate_instruction_captions
from core.pipeline import load_grade_config
from tests.coherent_fixtures import exact_page, visual_examples


class ExactCaptionRecoveryTests(unittest.TestCase):
    """Resolve proven duplicates while keeping independent student work."""
    def page(self, text='Sort the pictures by shape.'):
        """Make a valid puzzle plus an incorrectly declared instruction caption."""
        page=exact_page(visual_examples()[5])
        page['exercise']['captions']=[{'id':'c2','text':text}]
        page['html']+='<p data-content="caption_c2"></p>'
        return page

    def validate(self, page):
        """Use actual canonical binding and print geometry."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
            expected_title='Sorting Studio',require_coherent=True)

    def test_literal_duplicate_is_resolved_without_an_api_retry(self):
        """Verified directions remain on the computed graphic and the duplicate disappears."""
        page=self.page(); original=deepcopy(page)
        result=self.validate(page)
        self.assertEqual(page,original)
        self.assertEqual(result['exercise']['captions'],[])
        self.assertEqual(result['exercise']['visual'],page['exercise']['visual'])
        self.assertNotIn('caption_c2',result['source_layout'])
        from core.task_visuals import answer_text
        self.assertIn('1.',answer_text(result))

    def test_additional_action_is_not_deleted_as_a_duplicate(self):
        """A different task requires a question and an answer, not silent removal."""
        with self.assertRaisesRegex(ValueError,'Caption ID: c2'):
            self.validate(self.page('Draw a new shape in each group.'))

    def test_explicit_workspace_is_never_removed(self):
        """Even a literal repeated instruction cannot delete a sized response surface."""
        page=self.page()
        page['html']=page['html'].replace('<p data-content="caption_c2">','<p style="height:40mm" data-content="caption_c2">')
        self.assertEqual(remove_duplicate_instruction_captions(page['exercise'],page['html']),page['html'])
        self.assertEqual(len(page['exercise']['captions']),1)

    def test_repair_drift_restores_answer_and_response_space(self):
        """An independent question remains byte-for-byte unchanged during caption repair."""
        original=exact_page(visual_examples()[5])
        question={'id':'2','prompt':'Draw a new shape.', 'answer':'Accept a new shape.','space_mm':30}
        original['exercise']['questions']=[question]
        original['html']+='<div data-content="question_2"></div>'
        correction=deepcopy(original)
        correction['exercise']['questions'][0].update(answer='Changed',space_mm=0)
        repaired=merge_exact_wording_repair(original,correction)
        self.assertEqual(repaired['exercise']['questions'],[question])
        result=self.validate(repaired)
        self.assertIn('Accept a new shape',result['answers'])
