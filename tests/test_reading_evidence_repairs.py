"""Regress paraphrased Gemini evidence while retaining actual passage grounding."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.pipeline import load_grade_config
from core.reading_generator import repair_unit_evidence, excerpt_in_passage, validate_unit
from tests.test_reading_generator import reading_fixture


class ReadingEvidenceRepairTests(unittest.TestCase):
    """Repair unsupported excerpts without modifying source text or unrelated questions."""

    def test_typography_and_quote_wrappers_do_not_spend_calls(self):
        """Smart quotes, whitespace and dash styles do not alter copied wording."""
        paragraphs=['Gardening isn’t guessing—it requires observation.', 'Other text.', 'Final text.']
        self.assertTrue(excerpt_in_passage('“Gardening isn\'t guessing-it requires observation.”',paragraphs))
        self.assertTrue(excerpt_in_passage('Gardening\nisn’t guessing—it requires observation.',paragraphs))
        unit=reading_fixture();unit['questions'][0]['evidence']='“'+unit['questions'][0]['evidence']+'”'
        with patch('core.reading_generator.ask_json') as api:
            result=repair_unit_evidence(unit,'Reading 1')
            api.assert_not_called()
        validate_unit(result,load_grade_config()['3rd-4th'])

    def test_paraphrases_are_not_treated_as_copied_evidence(self):
        """Nearby meaning and omitted intermediate words cannot bypass literal grounding."""
        self.assertFalse(excerpt_in_passage('Plants require water.', ['Plants need water.']))
        self.assertFalse(excerpt_in_passage('Plants ... water.', ['Plants need water.']))
        self.assertFalse(excerpt_in_passage('', ['Plants need water.']))
        self.assertFalse(excerpt_in_passage(None, ['Plants need water.']))
        self.assertFalse(excerpt_in_passage('12', ['There were 120 samples.']))
        self.assertFalse(excerpt_in_passage('fire', ['The firefighters arrived.']))

    def test_batched_repairs_preserve_passage_and_unaffected_questions(self):
        """Both grades replace only failed question/evidence pairs with supported versions."""
        for band in ('3rd-4th','5th-6th'):
            valid=reading_fixture(band);bad=deepcopy(valid)
            bad['questions'][0]['evidence']='Observations help gardeners make decisions.'
            bad['questions'][3]['evidence']=None
            before=deepcopy(bad)
            def ask(prompt,validate,label,*args,**kwargs):
                """Apply the exact scoped schema with independent question replacements."""
                self.assertIn('not merely appear somewhere',prompt)
                self.assertEqual(set(kwargs['response_schema']['properties']['questions']['properties']),{'1','4'})
                return validate({'questions':{'1':valid['questions'][0],'4':valid['questions'][3]}})
            with self.subTest(band=band),patch('core.reading_generator.ask_json',side_effect=ask) as api:
                result=repair_unit_evidence(bad,'Reading 1')
                validate_unit(result,load_grade_config()[band])
                self.assertEqual(result,valid)
                self.assertEqual(bad,before)
                api.assert_called_once()

    def test_invalid_evidence_and_unrequested_edits_are_rejected(self):
        """A repair cannot justify a question with a new claim or replace a different page."""
        valid=reading_fixture();bad=deepcopy(valid);bad['questions'][0]['evidence']='Made up text.'
        def ask(prompt,validate,*args,**kwargs):
            """Exercise the real scoped validator on malformed repairs."""
            for replacements in ({}, {'2':valid['questions'][0]}, {'1':bad['questions'][0]}):
                with self.assertRaises(ValueError):
                    validate({'questions':replacements})
            replacement=deepcopy(valid['questions'][0]);replacement['evidence']='x'*181
            with self.assertRaises(ValueError):
                validate({'questions':{'1':replacement}})
            return validate({'questions':{'1':valid['questions'][0]}})
        with patch('core.reading_generator.ask_json',side_effect=ask):
            result=repair_unit_evidence(bad,'Reading 1')
        self.assertEqual(result['paragraphs'],bad['paragraphs'])

    def test_real_retry_rejects_paraphrase_before_accepting_existing_quote(self):
        """Run actual JSON feedback retries on the user's reported evidence failure."""
        valid=reading_fixture();bad=deepcopy(valid);bad['questions'][0]['evidence']='Watching helps plan a garden.'
        replies=[{'questions':{'1':bad['questions'][0]}},{'questions':{'1':valid['questions'][0]}}]
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in replies]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=repair_unit_evidence(bad,'Reading 1')
        self.assertEqual(result,valid)
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_evidence_repair_schema_offers_only_real_bounded_excerpts(self):
        """A constrained evidence bank prevents paraphrases and overlong quote outputs."""
        from core.reading_generator import passage_excerpt_bank
        for band in ('3rd-4th','5th-6th'):
            valid=reading_fixture(band);bad=deepcopy(valid)
            bad['questions'][0]['evidence']='x'*181
            def ask(prompt,validate,label,*args,**kwargs):
                """Select an exact offered source quotation in the production schema."""
                from core.reading_generator import passage_excerpt_bank
                bank=passage_excerpt_bank(valid['paragraphs'])
                properties=kwargs['response_schema']['properties']['questions']['properties']['1']['properties']
                self.assertNotIn('evidence',properties)
                self.assertEqual(properties['evidence_index']['maximum'],len(bank))
                self.assertTrue(bank)
                self.assertTrue(all(len(q)<=180 and excerpt_in_passage(q,valid['paragraphs']) for q in bank))
                self.assertIn(valid['questions'][0]['evidence'],bank)
                self.assertIn('return evidence_index',prompt)
                question=deepcopy(valid['questions'][0]);question.pop('evidence')
                for index in (0,True,len(bank)+1):
                    question['evidence_index']=index
                    with self.assertRaises(ValueError):validate({'questions':{'1':question}})
                question['evidence_index']=bank.index(valid['questions'][0]['evidence'])+1
                return validate({'questions':{'1':question}})
            with self.subTest(band=band),patch('core.reading_generator.ask_json',side_effect=ask):
                self.assertEqual(repair_unit_evidence(bad,'Reading 1'),valid)
            long=' '.join(['Students record environmental observations and discuss their conclusions carefully']*10)+'.'
            bank=passage_excerpt_bank([long])
            self.assertTrue(bank)
            self.assertTrue(all(len(q)<=180 and excerpt_in_passage(q,[long]) for q in bank))

    def test_valid_reading_and_malformed_units_need_no_evidence_call(self):
        """Avoid extra provider spending on valid or structurally invalid drafts."""
        with patch('core.reading_generator.ask_json') as api:
            for value in (None,{}, {'paragraphs':['short']}, reading_fixture()):
                self.assertEqual(repair_unit_evidence(value,'Reading 1'),value)
            api.assert_not_called()
