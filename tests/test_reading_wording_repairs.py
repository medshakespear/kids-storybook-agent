"""Regress explanation/stem limits without weakening shared reading validation."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.pipeline import load_grade_config
from core.reading_generator import repair_unit_text, prepare_reading_unit, validate_unit
from tests.test_reading_generator import reading_fixture


class ReadingWordingRepairTests(unittest.TestCase):
    """Repair only failed wording while retaining evidence and answer alignment."""

    def test_long_explanation_is_repaired_in_both_bands(self):
        """The reported failure produces a bounded explanation, not a regenerated unit."""
        for band in ('3rd-4th','5th-6th'):
            valid=reading_fixture(band);draft=deepcopy(valid)
            draft['questions'][0]['explanation']=valid['questions'][0]['explanation']+' This explanation is unnecessarily repeated for a long classroom teaching guide. '*3
            before=deepcopy(draft)
            def ask(prompt,validate,label,*args,**kwargs):
                """Return only the explanation requested by the scoped schema."""
                self.assertIn('60-90 characters',prompt)
                self.assertEqual(set(kwargs['response_schema']['properties']['replacements']['properties']),{'1:explanation'})
                return validate({'replacements':{'1:explanation':valid['questions'][0]['explanation']}})
            with self.subTest(band=band),patch('core.reading_generator.ask_json',side_effect=ask) as api:
                result=prepare_reading_unit(draft,load_grade_config()[band],'Reading 1')
                self.assertEqual(result,valid)
                self.assertEqual(draft,before)
                api.assert_called_once()

    def test_missing_explanation_and_long_stem_are_batched(self):
        """Missing wording and excessive stems share one bounded request."""
        valid=reading_fixture();draft=deepcopy(valid)
        draft['questions'][0]['explanation']=None
        draft['questions'][1]['prompt']=valid['questions'][1]['prompt']*4
        def ask(prompt,validate,*args,**kwargs):
            """Keep every other question field and correct letter unchanged."""
            return validate({'replacements':{'1:explanation':valid['questions'][0]['explanation'],
                                             '2:prompt':valid['questions'][1]['prompt']}})
        with patch('core.reading_generator.ask_json',side_effect=ask) as api:
            result=repair_unit_text(draft,'Reading 1')
        self.assertEqual(result,valid)
        api.assert_called_once()

    def test_bad_field_replacements_cannot_bypass_limits_or_distinctness(self):
        """Reject extra edits, blanks, overlong output and duplicate question stems."""
        valid=reading_fixture();draft=deepcopy(valid)
        draft['questions'][0]['explanation']='x'*111
        draft['questions'][1]['prompt']='x'*121
        def ask(prompt,validate,*args,**kwargs):
            """Exercise precise IDs and print limits on repair responses."""
            good={'1:explanation':valid['questions'][0]['explanation'],'2:prompt':valid['questions'][1]['prompt']}
            for patch_values in ({},dict(good,extra='edit'),dict(good,**{'1:explanation':''}),
                                 dict(good,**{'1:explanation':'x'*111}),
                                 dict(good,**{'2:prompt':valid['questions'][0]['prompt']})):
                with self.assertRaises(ValueError):
                    validate({'replacements':patch_values})
            return validate({'replacements':good})
        with patch('core.reading_generator.ask_json',side_effect=ask):
            self.assertEqual(repair_unit_text(draft,'Reading 1'),valid)

    def test_title_and_image_brief_limits_share_scoped_repair(self):
        """Retain passage/questions while correcting an overlong title and artwork brief."""
        valid=reading_fixture();draft=deepcopy(valid)
        draft['title']='Title '*30;draft['image_prompt']='An original garden scene. '*35
        def ask(prompt,validate,*args,**kwargs):
            """Restore a concise expression of the same identity and illustration."""
            return validate({'replacements':{'title':valid['title'],'image_prompt':valid['image_prompt']}})
        with patch('core.reading_generator.ask_json',side_effect=ask):
            self.assertEqual(repair_unit_text(draft,'Reading 1'),valid)

    def test_review_uses_retained_cover_identity_without_extra_calls(self):
        """A comprehension review cannot rename the accepted reading or redraw its scene."""
        valid=reading_fixture();draft=deepcopy(valid)
        draft['title']='Different title';draft['image_prompt']='Different visual'
        with patch('core.reading_generator.ask_json') as api:
            self.assertEqual(repair_unit_text(draft,'Review',retained=valid),valid)
            self.assertEqual(repair_unit_text(valid,'Reading 1'),valid)
            api.assert_not_called()

    def test_oversized_paragraph_is_rebalanced_within_grade_word_range(self):
        """Paragraph character limits get a scoped passage rewrite even at valid word count."""
        from core.reading_generator import repair_unit_limits, passage_word_count
        valid=reading_fixture('5th-6th');draft=deepcopy(valid)
        draft['paragraphs']=[' '.join(valid['paragraphs']),'Careful observation matters.','Records support reasoning.']
        self.assertGreater(len(draft['paragraphs'][0]),1300)
        self.assertTrue(320 <= passage_word_count(draft['paragraphs']) <= 420)
        def ask(prompt,validate,*args,**kwargs):
            """Accept balanced paragraphs with all original supporting evidence."""
            self.assertIn('each at most 1300 characters',prompt)
            return validate({'paragraphs':valid['paragraphs']})
        with patch('core.reading_generator.ask_json',side_effect=ask):
            self.assertEqual(repair_unit_limits(draft,load_grade_config()['5th-6th'],'Reading 1'),valid)

    def test_real_retry_handles_an_overlong_replacement(self):
        """Use actual request retry handling rather than assuming repairs always conform."""
        valid=reading_fixture();draft=deepcopy(valid);draft['questions'][0]['explanation']='x'*150
        replies=[{'replacements':{'1:explanation':'x'*111}},
                 {'replacements':{'1:explanation':valid['questions'][0]['explanation']}}]
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in replies]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=repair_unit_text(draft,'Reading 1')
        validate_unit(result,load_grade_config()['3rd-4th'])
        self.assertEqual(result,valid)
        self.assertEqual(api.chat.completions.create.call_count,2)
