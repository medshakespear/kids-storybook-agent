"""Align layout question IDs while preserving verified tasks and extra blank workspace."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.pipeline import load_grade_config
from core.question_slots import normalize_question_slots
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page,visual_examples


class QuestionSlotAlignmentTests(unittest.TestCase):
    """Exercise typo, extra-placeholder and negative cases in both active grades."""

    def page(self):
        """Supply computed question 1, a real question 2 and its retained source."""
        page=exact_page(visual_examples()[5])
        page['exercise'].update(stimuli=[{'id':'space_facts','text':'Fictional classroom notes: A telescope helps students observe distant objects.'}],
            captions=[{'id':'intro_label','text':'Observation Notes'}],
            questions=[{'id':'2','prompt':'Describe one useful classroom display idea based on the notes.',
                'answer':'Accept an idea linked to observation or telescopes.','space_mm':15}])
        page['html']+='<p data-content="caption_intro_label"></p><p data-content="stimulus_space_facts"></p>'
        return page

    def test_stale_question_three_rebinds_or_detaches_blank_workspace_locally(self):
        """No question, source, answer or explicit writing dimensions change."""
        for band in ('3rd-4th','5th-6th'):
            for kind in ('empty_typo','verbatim_typo','extra_workspace','literal_already_printed'):
                with self.subTest(band=band,kind=kind):
                    page=self.page()
                    if kind=='empty_typo': page['html']+='<div data-content="question_3"></div>'
                    elif kind=='verbatim_typo':
                        page['html']+='<p data-content="question_3">3. '+page['exercise']['questions'][0]['prompt']+'</p>'
                    else:
                        page['html']+=('<div data-content="question_2"></div>' if kind=='extra_workspace'
                            else '<p>2. '+page['exercise']['questions'][0]['prompt']+'</p>')
                        page['html']+='<div data-content="question_3" style="height:10mm;border:0.4mm solid #167E80"><span style="height:5mm;display:block"></span></div>'
                    original=deepcopy(page)
                    config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                        stimulus_limit=8,context_caption_limit=24,items_per_page=2)
                    api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                    brief={'render_mode':'exact','mechanic':'sort'}
                    with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                         patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                         patch('core.creative_generator.time.sleep'):
                        result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                            lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                                expected_title='Observation Studio',require_coherent=True,brief=brief),
                            'Activity design 7',response_schema=design_schema(brief,config))
                    self.assertEqual(api.chat.completions.create.call_count,1)
                    for field in ('questions','stimuli','visual','captions'):
                        self.assertEqual(result['exercise'][field],original['exercise'][field])
                    self.assertNotIn('data-content="question_3"',result['html'])
                    self.assertIn('height:15mm',result['html'])
                    if kind in {'extra_workspace','literal_already_printed'}:
                        self.assertIn('height:10mm',result['html']);self.assertIn('height:5mm',result['html'])
                    self.assertEqual(page,original)

    def test_ambiguous_missing_questions_and_meaningful_unmatched_content_stay_strict(self):
        """Never choose between several questions, invent a key or consume an extra task."""
        for markup,blocks in (
            ('<p data-content="question_4"></p>',{'question_2':'2. Describe a model.','question_3':'3. Explain a feature.'}),
            ('<p data-content="question_3">Write an unrelated answer.</p>',{'question_2':'2. Describe a model.'}),
            ('<p data-content="question_3" style="height:25mm"></p>',{'question_2':'2. Describe a model.'}),
            ('<p data-content="question_2"></p><div data-content="question_3"><img data-asset="scene"/></div>',{'question_2':'2. Describe a model.'}),
        ):
            self.assertEqual(normalize_question_slots(markup,blocks),markup)

    def test_known_duplicate_questions_are_not_arbitrarily_deleted(self):
        """Duplicating a declared question remains a validation issue."""
        markup='<p data-content="question_2"></p><p data-content="question_2"></p>'
        self.assertEqual(normalize_question_slots(markup,{'question_2':'2. Describe a model.'}),markup)

    def test_empty_extra_panels_resolve_after_matching_the_real_question(self):
        """An earlier blank extra frame does not obstruct a later verbatim binding."""
        markup=('<div data-content="question_4" style="height:10mm"></div>'
                '<p data-content="question_3">3. Describe a model.</p>')
        result=normalize_question_slots(markup,{'question_2':'2. Describe a model.'})
        self.assertIn('data-content="question_2"',result)
        self.assertNotIn('data-content="question_4"',result)
        self.assertIn('height:10mm',result)
        result=normalize_question_slots('<div data-content="question_3" style="height:10mm"></div>',{})
        self.assertNotIn('data-content',result)
        self.assertIn('height:10mm',result)
