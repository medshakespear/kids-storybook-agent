"""Regress short Gemini passages and overlong QCM choices with scoped content repair."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from core.pipeline import load_grade_config
from core.reading_generator import repair_unit_limits, validate_unit, passage_word_count
from tests.test_reading_generator import reading_fixture


class ReadingLimitRepairTests(unittest.TestCase):
    """Preserve the exercise while repairing only the failed content family."""

    def setUp(self):
        """Load the two production grade profiles."""
        self.config = load_grade_config()

    def test_short_passage_repairs_only_paragraphs_in_both_grades(self):
        """Retain title, artwork and all five questions after a measured expansion."""
        for band in ('3rd-4th','5th-6th'):
            draft=reading_fixture(band)
            draft['paragraphs']=[' '.join(p.split()[:50]) for p in draft['paragraphs']]
            before=deepcopy(draft)
            def ask(prompt,validate,label,*args,**kwargs):
                """Exercise the actual scoped validator on a valid expansion."""
                self.assertIn('Repair ONLY the passage length',prompt)
                self.assertIn('add about',prompt)
                self.assertEqual(set(kwargs['response_schema']['properties']),{'paragraphs'})
                return validate({'paragraphs':reading_fixture(band)['paragraphs']})
            with self.subTest(band=band),patch('core.reading_generator.ask_json',side_effect=ask) as api:
                repaired=repair_unit_limits(draft,self.config[band],'Reading 1')
                validate_unit(repaired,self.config[band])
                self.assertEqual(repaired['questions'],before['questions'])
                self.assertEqual(repaired['title'],before['title'])
                self.assertEqual(repaired['image_prompt'],before['image_prompt'])
                self.assertEqual(draft,before)
                api.assert_called_once()

    def test_long_choices_are_batched_without_touching_other_fields(self):
        """Replace only overlong choices and preserve answer letters and evidence."""
        for band in ('3rd-4th','5th-6th'):
            draft=reading_fixture(band)
            draft['questions'][0]['options']['A']='Gardens only need sunlight and no other conditions are worth observing.'
            draft['questions'][1]['options']['D']='To replace all the soil in the entire garden with only empty air.'
            before=deepcopy(draft)
            def ask(prompt,validate,label,*args,**kwargs):
                """Return the precise choice IDs selected by the repair schema."""
                self.assertIn('answer-letter correctness',prompt)
                self.assertEqual(set(kwargs['response_schema']['properties']['replacements']['properties']),{'1:A','2:D'})
                return validate({'replacements':{'1:A':'Gardens only need sunlight.','2:D':'To replace soil with air.'}})
            with self.subTest(band=band),patch('core.reading_generator.ask_json',side_effect=ask) as api:
                repaired=repair_unit_limits(draft,self.config[band],'Reading 1')
                validate_unit(repaired,self.config[band])
                self.assertEqual(repaired,reading_fixture(band))
                self.assertEqual(draft,before)
                api.assert_called_once()

    def test_repair_rejects_still_short_passages_or_lost_evidence(self):
        """A repair cannot bypass the grade length or delete supporting quotations."""
        draft=reading_fixture('5th-6th');draft['paragraphs']=reading_fixture()['paragraphs']
        def ask(prompt,validate,*args,**kwargs):
            """Verify corrective feedback and evidence retention before accepting content."""
            with self.assertRaisesRegex(ValueError,'Target 350 words'):
                validate({'paragraphs':draft['paragraphs']})
            invalid=deepcopy(reading_fixture('5th-6th')['paragraphs'])
            invalid[0]=invalid[0].replace('Good planning begins with watching carefully rather than guessing.','Reliable planning relies on careful observation of the site.')
            with self.assertRaisesRegex(ValueError,'supporting quotation'):
                validate({'paragraphs':invalid})
            return validate({'paragraphs':reading_fixture('5th-6th')['paragraphs']})
        with patch('core.reading_generator.ask_json',side_effect=ask):
            result=repair_unit_limits(draft,self.config['5th-6th'],'Reading 1')
        self.assertGreaterEqual(passage_word_count(result['paragraphs']),320)

    def test_choice_repair_rejects_wrong_ids_overlength_and_duplicates(self):
        """No silent truncation, duplicated choices or unexpected edits are accepted."""
        draft=reading_fixture();draft['questions'][0]['options']['A']='Gardens only need sunlight and no other conditions are worth observing.'
        def ask(prompt,validate,*args,**kwargs):
            """Reject malformed scoped edits while keeping the original exercise."""
            for changes in ({'2:A':'Unrequested'}, {'1:A':'x'*56}, {'1:A':draft['questions'][0]['options']['B']}):
                with self.assertRaises(ValueError):
                    validate({'replacements':changes})
            return validate({'replacements':{'1:A':'Gardens only need sunlight.'}})
        with patch('core.reading_generator.ask_json',side_effect=ask):
            repair_unit_limits(draft,self.config['3rd-4th'],'Reading 1')

    def test_real_json_retry_handles_short_repair_then_long_choice(self):
        """Reproduce the provider's successive length failures with real request retries."""
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock
        valid=reading_fixture('5th-6th')
        draft=deepcopy(valid)
        draft['paragraphs']=[' '.join(p.split()[:n]) for p,n in zip(valid['paragraphs'],(60,100,127))]
        draft['questions'][0]['options']['A']='Gardens only need sunlight and no other conditions are worth observing.'
        short=[' '.join(p.split()[:n]) for p,n in zip(valid['paragraphs'],(65,110,131))]
        replies=[{'paragraphs':short},{'paragraphs':valid['paragraphs']},
                 {'replacements':{'1:A':'x'*56}}, {'replacements':{'1:A':'Gardens only need sunlight.'}}]
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in replies]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=repair_unit_limits(draft,self.config['5th-6th'],'Reading 1')
        validate_unit(result,self.config['5th-6th'])
        self.assertEqual(api.chat.completions.create.call_count,4)
        self.assertEqual(result,valid)

    def test_valid_draft_does_not_spend_repair_calls(self):
        """The normal path keeps its existing request count."""
        with patch('core.reading_generator.ask_json') as api:
            for band in ('3rd-4th','5th-6th'):
                unit=reading_fixture(band)
                self.assertEqual(repair_unit_limits(unit,self.config[band],'Reading'),unit)
            api.assert_not_called()

