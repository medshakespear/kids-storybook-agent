"""Whole-container text binding and explicit image-manifest shape recovery."""
from copy import deepcopy
import unittest

from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class FormattedBindingTests(unittest.TestCase):
    """Accept harmless presentation differences while preserving tasks, work space and art."""

    def validate(self,page):
        """Use actual canonical binding and young-reader print preflight."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Safe Design',require_coherent=True)

    def test_formatted_complete_direction_binds_without_a_retry(self):
        """Split text nodes, emphasis and an empty trailing span retain one canonical instruction."""
        for body in ['<strong>Help a plant grow.</strong> Invent a shelter that lets sunlight reach it.',
                     'Help a plant grow. <em>Invent a shelter that lets sunlight reach it.</em>',
                     'Help a plant grow. Invent a shelter that lets sunlight reach it.<span></span>',
                     'Help a plant grow.<br/>Invent a shelter that lets sunlight reach it.']:
            with self.subTest(body=body):
                page=authored_page();original=deepcopy(page['exercise'])
                page['html']=page['html'].replace('<p data-content="directions"></p>','<p>'+body+'</p>')
                result=self.validate(page)
                self.assertEqual(result['html'].count(page['exercise']['directions']),1)
                self.assertEqual(result['exercise'],original)

    def test_formatted_question_keeps_number_and_work_area_once(self):
        """Canonical question binding adds its existing response box without double-printing it."""
        page=authored_page()
        page['html']=page['html'].replace('data-content="question_1"','').replace('border-radius:4mm"></div>',
                    'border-radius:4mm"><strong>Draw your shelter.</strong> Show a way to water the plant.</div>')
        result=self.validate(page)
        self.assertIn('1. Draw your shelter.',result['html'])
        self.assertEqual(result['html'].count('height:45mm'),1)

    def test_formatted_title_preserves_planned_heading(self):
        """Styled heading text is compared as a whole, including the harmless page prefix."""
        page=authored_page();page['html']=page['html'].replace('data-content="title"','').replace('></h1>',
                      '>Activity 1: <span>Safe</span> <em>Design</em></h1>')
        self.assertIn('Safe Design',self.validate(page)['html'])

    def test_extra_nested_task_remains_rejected(self):
        """A complete first chunk cannot hide newly appended independent instructions."""
        page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<p>'+page['exercise']['directions']+'<span>Now count the stars.</span></p>')
        with self.assertRaisesRegex(ValueError,'inferred content slot'):
            self.validate(page)

    def test_nested_art_and_manual_work_area_are_not_discarded(self):
        """The prepass will not swallow an image or a dimensioned response panel as text styling."""
        for trailing in ['<img data-asset="scene" style="width:175mm;height:75mm"/>',
                         '<span style="display:block;height:45mm"></span>']:
            with self.subTest(trailing=trailing),self.assertRaises(ValueError):
                page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
                            '<p>'+page['exercise']['directions']+trailing+'</p>')
                self.validate(page)

    def test_prefilled_explicit_slot_keeps_existing_canonical_replacement(self):
        """Formatting recovery must not create a second named slot inside an explicit one."""
        page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
                  '<p data-content="directions"><span>'+page['exercise']['directions']+'</span></p>')
        self.assertEqual(self.validate(page)['html'].count(page['exercise']['directions']),1)

    def test_explicit_manifest_shapes_normalize_without_changing_prompts(self):
        """Singleton and keyed objects retain authored ID/prompt information exactly."""
        original=authored_page()
        asset=original['images'][0]
        for manifest in [asset,{'scene':asset['prompt']},{'scene':{'prompt':asset['prompt']}},
                         {'scene':dict(asset)}]:
            with self.subTest(manifest=manifest):
                page=deepcopy(original);page['images']=deepcopy(manifest);untouched=deepcopy(page)
                self.assertEqual(self.validate(page)['images'],original['images'])
                self.assertEqual(page,untouched)

    def test_missing_or_ambiguous_manifest_still_requires_repair(self):
        """Never invent art for absent prompts or contradicting ID declarations."""
        for manifest in [None,'A plant',{'scene':{'id':'owl','prompt':'An owl'}},
                         {'id':'scene','prompt':'A plant','style':'cartoon'}, {'scene':{}},{}]:
            with self.subTest(manifest=manifest),self.assertRaisesRegex(ValueError,'Illustration manifest'):
                page=authored_page();page['images']=manifest
                self.validate(page)
