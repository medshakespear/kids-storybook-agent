"""Recover canonical runs after media and route remaining inferred slots to layout repair."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.page_contract import BoundLayout
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class InferredSlotRepairTests(unittest.TestCase):
    """Preserve source wording, illustrations and response areas in both active grades."""

    def config(self,band):
        """Load the mixed activity print profile without modifying global settings."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    context_caption_limit=24,stimulus_limit=8,items_per_page=2)

    def validate(self,page,band):
        """Compile tasks and measure the resulting A4 worksheet."""
        config=self.config(band)
        return validate_design(page,config['student_font_pt'],quality=config,
                               expected_title='Garden Detectives',require_coherent=True)

    def test_formatted_canonical_run_after_image_binds_locally(self):
        """Artwork before the raw words no longer blocks whole-run recognition."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page();page['exercise'].update(captions=[],stimuli=[])
                original=deepcopy(page['exercise'])
                page['html']=page['html'].replace('<p data-content="directions"></p>','').replace(
                    '<img data-asset="scene"', '<div><img data-asset="scene"').replace(
                    'height:75mm"/>','height:75mm"/>Help a plant grow. '
                    '<em>Invent a shelter that lets sunlight reach it.</em></div>')
                result=self.validate(page,band)
                self.assertEqual(result['exercise'],original)
                self.assertEqual(result['html'].count(original['directions']),1)
                self.assertEqual(result['html'].count('data-asset="scene"'),1)
                self.assertEqual(result['html'].count('height:45mm'),1)

    def test_two_runs_with_protected_siblings_preserve_every_block(self):
        """Both an instruction and a passage may surround media and a blank panel."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page();page['exercise'].update(captions=[],stimuli=[],
                    passage='The plant is growing toward the sunlight.')
                page['html']=page['html'].replace('<p data-content="directions"></p>','').replace(
                    '<img data-asset="scene"', '<div>'+page['exercise']['directions']+'<img data-asset="scene"').replace(
                    'height:75mm"/>','height:75mm"/>'+page['exercise']['passage']+
                    '<span style="display:block;height:5mm;border:0.4mm solid #167E80"></span></div>')
                original=deepcopy(page)
                result=self.validate(page,band)
                self.assertEqual(result['exercise'],original['exercise'])
                self.assertEqual(result['html'].count(page['exercise']['passage']),1)
                self.assertIn('height:5mm',result['html'])
                self.assertEqual(page,original)

    def test_question_prefix_requests_layout_only_repair_and_preserves_workspace(self):
        """Excluded question runs get a specific small repair rather than a fresh exercise."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page();question=page['exercise']['questions'][0]
                question['space_mm']=25
                panel='<span style="display:block;height:5mm;border:0.4mm solid #167E80"></span>'
                page['html']=page['html'].replace('<div data-content="question_1" style="background-color:#FFF7DE;padding:3mm;border-radius:4mm"></div>',
                    '<div>'+question['prompt']+panel+'</div>')
                original=deepcopy(page)
                corrected=page['html'].replace(question['prompt']+panel,
                    '<span data-content="question_1"></span>'+panel)
                api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
                    for raw in (page,{'html':corrected})]
                config=self.config(band)
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:self.validate(raw,band),'Activity design 4')
                self.assertEqual(api.chat.completions.create.call_count,2)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('height:25mm',result['html'])
                self.assertIn('height:5mm',result['html'])
                message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
                self.assertIn('Return JSON containing html only',message)
                self.assertIn("Inferred slot 'question_1'",message)
                self.assertEqual(page,original)

    def test_diagnostics_identify_slot_and_following_element(self):
        """Remaining errors include actionable boundaries without discarding their content."""
        parser=BoundLayout({'title':'Title','directions':'Read.'})
        with self.assertRaisesRegex(ValueError,"Inferred slot 'directions'.*<p>.*<span>"):
            parser.feed('<p>Read.<span>Extra task.</span></p>')

    def test_protected_element_does_not_authorize_extra_wording(self):
        """A mixed run after an image cannot hide an appended independent instruction."""
        page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>','').replace(
            '<img data-asset="scene"', '<div><img data-asset="scene"').replace('height:75mm"/>',
            'height:75mm"/>'+page['exercise']['directions']+'<em>Draw three extra flowers.</em></div>')
        with self.assertRaises(ValueError):
            self.validate(page,'3rd-4th')
