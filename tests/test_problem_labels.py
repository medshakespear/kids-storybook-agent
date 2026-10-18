"""Regress problem labels, bare matching ranges and empty illustration containers."""
from copy import deepcopy
import unittest

from core.calculation_attachment import label_matching_text
from core.question_slots import normalize_question_slots
from core.media_namespaces import normalize_authored_media
from core.creative_generator import validate_design
from tests.test_binding_alias_regressions import matching_page
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page,workbook_config


class ProblemLabelTests(unittest.TestCase):
    """Use production binding and real print measurement in both supported grades."""

    def test_bare_matching_ranges_and_numbered_terms_need_no_arithmetic(self):
        """The identifier typography must not turn a matching task into subtraction."""
        for band in ('3rd-4th','5th-6th'):
            raw=matching_page()
            raw['html']=raw['html'].replace('>Terms<','>Numbered Terms<')
            raw['exercise']['questions'][0]['prompt']='Match the numbered terms 1–4 to definitions A–D.'
            raw['exercise']['questions'][0]['calculation']={'expression':'1-4','answer':'-3'}
            page=fixtures.CompleteStudentTaskTests().ask(raw,band)
            self.assertNotIn('calculation',page['exercise']['questions'][0])
            self.assertEqual(page['exercise']['questions'][0]['answer'],'1:C, 2:D, 3:A, 4:B.')
            self.assertIn('Numbered Terms',page['html'])

    def test_problem_aliases_bind_to_their_declared_number_once(self):
        """Reported Problem 3/caption_p3_text renders the real prompt and writing area."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page()
            for old,new in (('1','3'),('2','4')):
                raw['exercise']['questions'][int(old)-1]['id']=new
                raw['html']=raw['html'].replace('question_'+old,'question_'+new)
            raw['exercise']['captions']=[{'id':'prob3_label','text':'Problem 3:'},
                                         {'id':'prob4_label','text':'Problem 4:'}]
            raw['html']=raw['html'].replace('<div data-content="question_3"',
                '<h3 style="font-size:12pt;margin:0">Problem 3:</h3><div data-content="caption_p3_text"')
            raw['html']=raw['html'].replace('<div data-content="question_4"',
                '<h3 style="font-size:12pt;margin:0">Problem 4:</h3><div data-content="question_4"')
            before=deepcopy(raw)
            page=fixtures.CompleteStudentTaskTests().ask(raw,band)
            self.assertEqual(page['exercise']['questions'][0]['prompt'],before['exercise']['questions'][0]['prompt'])
            self.assertEqual(page['exercise']['questions'][0]['answer'],before['exercise']['questions'][0]['answer'])
            self.assertIn('Problem 3:',page['html']);self.assertIn('Problem 4:',page['html'])
            self.assertNotIn('caption_p3_text',page['html'])
            self.assertEqual(raw,before)

    def test_problem_aliases_never_overwrite_an_unrelated_task_or_source(self):
        """Unknown labels, conflicting words and media remain strict repair cases."""
        blocks={'question_3':'3. Explain the evidence.'}
        for markup in ('<p data-content="caption_p4_text"></p>',
                       '<p data-content="caption_p3_text">Different task.</p>',
                       '<p data-content="caption_p3_text"><img data-asset="scene"/></p>',
                       '<p data-content="caption_p3_text" style="height:35mm"></p>'):
            self.assertEqual(normalize_question_slots(markup,blocks),markup)
        markup='<p data-content="caption_p3_text"></p>'
        self.assertEqual(normalize_question_slots(markup,dict(blocks,caption_p3_text='Problem context')),markup)

    def test_actual_calculations_are_not_exempted_by_matching_wording(self):
        """References are harmless, but added operations and weak drills still fail."""
        prompt='Match terms 1-4 to definitions A-D.'
        self.assertIsNotNone(label_matching_text(prompt))
        self.assertIsNotNone(label_matching_text('Match definitions A–D with numbered terms 1–4.'))
        self.assertIsNone(label_matching_text('Match terms 1-4.5 to their answers.'))
        for tail in (' Calculate 8-3.',' Find the total.',' Compare measurements 8-3.'):
            self.assertIsNone(label_matching_text(prompt+tail))
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page()
            raw['exercise']['questions'][0].update(prompt='Calculate 8-3.',answer='5')
            with self.assertRaisesRegex(ValueError,'below'):
                validate_design(raw,12,quality=workbook_config(band,simple=True),expected_title='Practice',require_coherent=True)

    def test_empty_declared_asset_container_recovers_without_consuming_content(self):
        """The uploaded diagnostic's empty div gets an image, not invented artwork or lost prose."""
        page={'exercise':{'render_mode':'authored'},'images':[{'id':'festival_art','prompt':'Original scene.'}],
              'html':'<div data-asset="festival_art" style="flex:1"></div><p>Retained source.</p>'}
        normalize_authored_media(page)
        self.assertIn('<img data-asset="festival_art"',page['html'])
        self.assertIn('Retained source.',page['html'])
        once=deepcopy(page);normalize_authored_media(page);self.assertEqual(page,once)
        for body in ('Source text.','<p data-content="passage"></p>','<img data-asset="other"/>'):
            page['html']='<div data-asset="festival_art">'+body+'</div>'
            before=deepcopy(page);normalize_authored_media(page);self.assertEqual(page,before)
