"""Keep source text clear of following tables while recovering small illustrations."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from core.text_flow import reflow_text_heights
from tests.coherent_fixtures import authored_page


class VerticalFlexRecoveryTests(unittest.TestCase):
    """Measure real A4 layout for both grades without provider requests."""

    def test_column_basis_does_not_clamp_text_or_shrink_workspace(self):
        """A vertical flex stack becomes normal flow; row layouts remain untouched."""
        markup=('<div style="display:flex;flex-direction:column;color:#167E80">'
                '<p style="flex-basis:3mm">A long source paragraph wraps.</p>'
                '<div style="height:25mm;border:0.4mm solid #809AA6"></div></div>')
        result=reflow_text_heights(markup)
        self.assertNotIn('display:flex',result)
        self.assertIn('display:block',result)
        self.assertIn('height:25mm',result)
        row=markup.replace('flex-direction:column','flex-direction:row')
        self.assertEqual(reflow_text_heights(row),row)
        stacked=reflow_text_heights(row,stack_rows=True)
        self.assertIn('display:block',stacked)
        self.assertIn('height:25mm',stacked)
        self.assertIn('A long source paragraph wraps.',stacked)
        reverse=row.replace('flex-direction:row','flex-direction:row-reverse')
        self.assertEqual(reflow_text_heights(reverse,stack_rows=True),reverse)
        wrapped=row.replace('flex-direction:row','flex-direction:row;flex-wrap:wrap')
        self.assertEqual(reflow_text_heights(wrapped,stack_rows=True),wrapped)

    def test_reported_source_table_overlap_and_small_art_recover_locally(self):
        """All measurements, table cells, art and answer space survive one model response."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,table_caption_limit=36,items_per_page=2)
                page=authored_page(mechanic='interpret_table')
                source=('In this fictional museum, a research team measures a femur bone at exactly 74 '
                        'centimeters, and the estimated length is recorded in a table. The team checks '
                        'each measurement carefully before sharing its notes with visitors. These are '
                        'fictional measurements for this classroom comparison, not claims about a real specimen.')
                page['exercise'].update(stimuli=[{'id':'case','text':source}],captions=[
                    {'id':'feature','text':'Feature'},{'id':'length','text':'Length'},
                    {'id':'femur','text':'Femur bone'},{'id':'measurement','text':'74 centimeters'}])
                page['exercise']['questions'][0].update(prompt='Name the measured bone using the table.',
                    answer='The measured bone is a femur.',space_mm=25)
                page['html']=('<h1 data-content="title"></h1><p data-content="directions"></p>'
                    '<img data-asset="scene" style="width:45mm;height:45mm"/>'
                    '<div style="display:flex;flex-direction:row;width:175mm">'
                    '<p data-content="stimulus_case" style="width:145mm;flex-basis:145mm;margin:0"></p>'
                    '<table style="width:175mm;table-layout:fixed;border-collapse:collapse">'
                    '<tr><th data-content="caption_feature"></th><th data-content="caption_length"></th></tr>'
                    '<tr><td data-content="caption_femur"></td><td data-content="caption_measurement"></td></tr>'
                    '</table></div><div data-content="question_1"></div>')
                original=deepcopy(page);brief={'render_mode':'authored','mechanic':'interpret_table'}
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title='Museum Measurements',require_coherent=True),
                        'Activity design 2',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn(source,result['html'])
                for caption in page['exercise']['captions']:
                    self.assertIn(caption['text'],result['html'])
                self.assertIn('<table',result['html'])
                self.assertIn('height:25mm',result['html'])
                self.assertNotIn('width:45mm;height:45mm',result['html'])
