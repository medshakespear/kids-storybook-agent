"""Regress reported source aliases, neutral headings and matching-range arithmetic."""
from copy import deepcopy
import unittest

from core.activity_stimuli import normalize_stimulus_ids
from core.calculation_attachment import label_matching_text
from core.creative_generator import validate_design
from tests import test_complete_student_tasks as fixtures
from tests.test_student_workbook import evidence_page,workbook_config


def matching_page():
    """Retain two complete matching lists while reproducing the three reported defects."""
    raw=evidence_page()
    raw['exercise'].update(mechanic='matching_definitions',directions='Read the terms and definitions. Answer both questions.')
    raw['exercise']['stimuli']=[{'id':'source_card','label':'Weather Terms','text':'1. Warm 2. Cool 3. Wet 4. Dry'},
        {'id':'note_b','label':'Definitions','text':'A. Covered in water. B. Without moisture. C. A little hot. D. A little cold.'}]
    raw['exercise']['questions']=[{'id':'1','prompt':'Match each numbered term (1-4) to its definition (A-D).',
        'answer':'1:C, 2:D, 3:A, 4:B.','space_mm':35},
        {'id':'2','prompt':'Explain how wet differs from dry.','answer':'Wet means covered in water; dry means without moisture.','space_mm':35}]
    raw['html']=raw['html'].replace('<p data-content="stimulus_note_a"',
        '<h3 style="margin:0;font-size:12pt">Terms</h3><p data-content="stimulus_source_text"')
    return raw


class BindingAliasRegressions(unittest.TestCase):
    """Recover unambiguous formatting locally and keep genuine content errors strict."""

    def test_native_generation_one_response_in_both_grades(self):
        """Use the real binding, retry and measured layout pipeline without paid requests."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                raw=matching_page();before=deepcopy(raw)
                page=fixtures.CompleteStudentTaskTests().ask(raw,band)
                self.assertEqual(raw,before)
                self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
                self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
                self.assertEqual(page['images'],before['images'])
                self.assertTrue(any(c['text']=='Terms' for c in page['exercise']['captions']))
                self.assertNotIn('stimulus_source_text',page['html'])
                self.assertEqual(page['html'].count('1. Warm 2. Cool 3. Wet 4. Dry'),1)

    def test_matching_ranges_are_references_only(self):
        """Broader matching nouns never exempt a real arithmetic operation or quantity."""
        for noun in ('terms','items','components','materials','descriptions','cards'):
            prompt=f'Match the numbered {noun} (1-4) to labels (A-D).'
            self.assertIsNotNone(label_matching_text(prompt))
            for tail in (' Calculate 8-3.',' How many items remain?',' Find the total points.'):
                self.assertIsNone(label_matching_text(prompt+tail))

    def test_source_alias_is_lossless_idempotent_and_narrow(self):
        """Only one unused generic source may fill one generic placeholder."""
        page=matching_page();normalize_stimulus_ids(page,page['exercise']);once=deepcopy(page)
        normalize_stimulus_ids(page,page['exercise']);self.assertEqual(page,once)
        self.assertIn('stimulus_source_card',page['html'])
        for scenario in ('conflicting_text','competing_source','already_used','named_missing','duplicate_slot','media'):
            page=matching_page()
            if scenario=='conflicting_text':page['html']=page['html'].replace('padding:2mm"></p>','padding:2mm">Different evidence.</p>',1)
            elif scenario=='competing_source':page['exercise']['stimuli'].append({'id':'reading_card','text':'Independent evidence.'})
            elif scenario=='already_used':page['html']+='<p data-content="stimulus_source_card"></p>'
            elif scenario=='named_missing':page['html']=page['html'].replace('stimulus_source_text','stimulus_card_e')
            elif scenario=='duplicate_slot':page['html']+='<p data-content="stimulus_source_text"></p>'
            elif scenario=='media':page['html']=page['html'].replace('data-content="stimulus_source_text" style="background-color:#EDF7F4;padding:2mm"></p>', 'data-content="stimulus_source_text"><img data-asset="independent"/></p>')
            before=deepcopy(page)
            normalize_stimulus_ids(page,page['exercise'])
            self.assertEqual(page,before,scenario)

    def test_real_arithmetic_still_requires_shared_calculation(self):
        """A matching task with an extra arithmetic action must not bypass math checks."""
        page=matching_page()
        page['exercise']['questions'][0]['prompt']+=' Calculate 8-3.'
        with self.assertRaisesRegex(ValueError,'printed arithmetic requires a calculation'):
            validate_design(page,12,quality=workbook_config('3rd-4th',simple=True),expected_title="Weather Evidence Lab",require_coherent=True)


if __name__=='__main__':
    unittest.main()
