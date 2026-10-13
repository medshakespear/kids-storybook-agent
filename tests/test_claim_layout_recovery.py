"""Preserve claim wording and repair readable computed graphics without dropping work."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.content_binding import diagram_label,evidence_heading
from core.creative_generator import ask_json,layout_contract,validate_design
from core.layout_recovery import readable_exact_layout
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page,exact_page,visual_examples


class ClaimLayoutRecoveryTests(unittest.TestCase):
    """Use real SVG dimensions and A4 preflight in both active grade bands."""

    def config(self,band):
        """Retain the mixed-profile caption/source allowances."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    context_caption_limit=24,stimulus_limit=8,items_per_page=2)

    def validate(self,page,config):
        """Compile canonical questions, assets and actual printable geometry."""
        return validate_design(page,config['student_font_pt'],quality=config,
                               expected_title='Evidence Studio',require_coherent=True)

    def test_claim_heading_labels_bind_with_the_authored_instruction(self):
        """Declared tasks and short standalone labels survive without guessing any answer."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page()
                page['exercise']['directions']='Pair each museum visitor claim with its exact objective measurement record.'
                page['exercise']['questions'][0].update(
                    prompt='Pair Claim A with Record B. Explain how the measurement supports the claim.',
                    answer='Accept a comparison linking the declared claim and its measurement.',space_mm=25)
                page['exercise']['stimuli']=[{'id':'claim','text':'Fictional Claim A: This model is twice as tall as that model.'},
                    {'id':'record','text':'Fictional Record B: The models measure 40 cm and 20 cm tall.'}]
                page['html']=page['html'].replace('<p data-content="directions"></p>',
                    '<h3 style="font-size:14pt">Visitor Guide Claims</h3><p data-content="directions"></p>'
                    '<p><strong>Claim A:</strong></p><p data-content="stimulus_claim"></p>'
                    '<p data-content="stimulus_record"></p>')
                original=deepcopy(page)
                result=self.validate(page,self.config(band))
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(result['html'].count('Visitor Guide Claims'),1)
                self.assertEqual(result['html'].count('Claim A:</'),1)
                self.assertEqual(page,original)

    def test_labels_do_not_authorize_independent_commands(self):
        """Claim headings cannot hide matching instructions or an answer after the colon."""
        self.assertTrue(diagram_label('Claim A:'))
        self.assertTrue(diagram_label('Record B'))
        self.assertFalse(diagram_label('Claim A: Match this card.'))
        self.assertFalse(evidence_heading('Visitor Guide Claims: The answer is B.'))
        page=exact_page(visual_examples()[1])
        page['html']+='<p>Pair each museum visitor claim with its exact objective measurement record.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page,self.config('3rd-4th'))

    def test_small_graphic_grows_in_retained_layout_with_workspace_preserved(self):
        """A blank writing panel prevents recomposition but survives local SVG resizing."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                config=self.config(band)
                page=exact_page(visual_examples()[1])
                page['html']=page['html'].replace('width:175mm;height:150mm','width:70mm;height:40mm')
                page['html']+='<div style="height:18mm;border:0.4mm solid #167E80"></div>'
                original=deepcopy(page)
                candidate=readable_exact_layout(page,config['minimum_text_pt'],config['visual_area_mm2'])
                self.assertIsNotNone(candidate)
                result=self.validate(candidate,config)
                self.assertEqual(result['exercise']['visual'],original['exercise']['visual'])
                self.assertIn('height:18mm',result['html'])
                self.assertNotIn('width:70mm;height:40mm',result['html'])
                self.assertEqual(page,original)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    recovered=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:self.validate(raw,config),'Activity design 3',
                        response_schema=design_schema({'render_mode':'exact','mechanic':'matching'},config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertIn('height:18mm',recovered['html'])

    def test_resize_cannot_discard_unknown_wording_or_accept_an_overfull_page(self):
        """New instructions block recovery and excessive retained workspace still fails fit."""
        config=self.config('3rd-4th')
        page=exact_page(visual_examples()[1]);page['html']+='<p>Draw another owl.</p>'
        self.assertIsNone(readable_exact_layout(page,12,8000))
        page=exact_page(visual_examples()[1]);page['html']+='<div style="height:240mm"></div>'
        candidate=readable_exact_layout(page,12,8000)
        self.assertIsNotNone(candidate)
        self.assertIn('height:240mm',candidate['html'])
        with self.assertRaisesRegex(ValueError,'Design overflow'):
            self.validate(candidate,config)
