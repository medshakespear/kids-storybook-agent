"""Normalize simple grids and fit substantial art without flattening data tables."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.layout_recovery import retained_table_artwork_recovery
from core.pipeline import load_grade_config
from core.print_grid import normalize_print_grid
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class GridTableArtRecoveryTests(unittest.TestCase):
    """Exercise measured print geometry with all source cells and response areas retained."""

    def config(self,band):
        """Use production varied-activity table and source allowances."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,table_caption_limit=36,items_per_page=2)

    def validate(self,page,band):
        """Compile and measure the original A4 exercise without API calls."""
        config=self.config(band)
        return validate_design(page,config['student_font_pt'],quality=config,
                               expected_title='Garden Records',require_coherent=True)

    def table_page(self):
        """Place a too-small illustration beside a real nested measurement table."""
        page=authored_page(mechanic='interpret_table')
        page['exercise'].update(captions=[{'id':'plant','text':'Plant'}, {'id':'height','text':'Height'},
            {'id':'bean','text':'Bean'}, {'id':'bean_cm','text':'20 cm'},
            {'id':'pea','text':'Pea'}, {'id':'pea_cm','text':'12 cm'}],stimuli=[])
        page['exercise']['questions'][0].update(prompt='Name the taller plant using the table.',
            answer='The bean plant is taller: 20 cm compared with 12 cm.',space_mm=25)
        table=('<table style="width:100%;border-collapse:collapse"><tbody>'
            '<tr><th data-content="caption_plant"></th><th data-content="caption_height"></th></tr>'
            '<tr><td data-content="caption_bean"></td><td data-content="caption_bean_cm"></td></tr>'
            '<tr><td data-content="caption_pea"></td><td data-content="caption_pea_cm"></td></tr></tbody></table>')
        page['html']=page['html'].replace('<img data-asset="scene" style="width:175mm;height:75mm"/>',
            '<table style="width:175mm;table-layout:fixed"><tbody><tr>'
            '<td style="width:75mm;height:78mm"><img data-asset="scene" style="width:72mm;height:72mm"/></td>'
            '<td style="width:100mm;vertical-align:top">'+table+'</td></tr></tbody></table>')
        return page

    def test_simple_grids_become_ordered_print_tables(self):
        """Equal tracks preserve cell order, contents and blank work panels."""
        for tracks in ('1fr 1fr','repeat(2, 1fr)','repeat(2, minmax(0, 1fr))'):
            with self.subTest(tracks=tracks):
                markup='<div style="display:grid;grid-template-columns:'+tracks+';gap:2mm;background-color:#DFF4EF">'
                markup+='<p data-content="directions"></p><div style="height:20mm"></div></div>'
                result=normalize_print_grid(markup)
                self.assertNotIn('grid-template',result)
                self.assertIn('border-spacing:2mm 2mm',result)
                self.assertIn('height:20mm',result)
                self.assertIn('background-color:#DFF4EF',result)
                self.assertLess(result.index('data-content="directions"'),result.index('height:20mm'))
                self.assertEqual(normalize_print_grid(result),result)

    def test_grid_page_passes_real_preflight_for_both_grades(self):
        """A grid syntax mistake needs no model retry or exercise replacement."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
                    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:2mm">'
                    '<p data-content="directions"></p><p data-content="name"></p></div>')
                original=deepcopy(page)
                result=self.validate(page,band)
                self.assertNotIn('grid-template-columns',result['html'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(page,original)

    def test_table_artwork_reflow_preserves_data_rows_and_answer(self):
        """A narrow image column can become a square main visual without losing the data table."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.table_page();original=deepcopy(page);config=self.config(band)
                page['_recovery_config']=config;page['_recovery_title']='Garden Records'
                candidate=retained_table_artwork_recovery(page,config['minimum_text_pt'],config['visual_area_mm2'])
                self.assertIsNotNone(candidate)
                result=self.validate(candidate,band)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(result['html'].count('<tr'),3)
                self.assertIn('height:25mm',result['html'])
                self.assertEqual(result['html'].count('data-asset="scene"'),1)

    def test_complex_grid_and_missing_evidence_are_not_silently_repaired(self):
        """Spanning grids and undeclared source wording still need explicit correction."""
        for style in ('display:grid;grid-template-columns:2fr 1fr',
                      'display:grid;grid-template-columns:1fr 1fr;grid-template-areas:"a b"',
                      'display:grid;grid-template-columns:1fr 1fr;gap:-2mm'):
            with self.subTest(style=style),self.assertRaises(ValueError):
                normalize_print_grid('<div style=\''+style+'\'><p>One</p><p>Two</p></div>')
        page=self.table_page();page['html']+='<p>Write an unrelated extra answer.</p>'
        self.assertIsNone(retained_table_artwork_recovery(page,12,8000))

    def test_unrelated_workspace_survives_reflow(self):
        """Moving the art cannot remove another blank student work panel."""
        page=self.table_page();page['_recovery_config']=self.config('3rd-4th')
        page['html']+='<div style="height:15mm;border:0.4mm solid #167E80"></div>'
        candidate=retained_table_artwork_recovery(page,12,8000)
        self.assertIsNotNone(candidate)
        self.assertIn('height:15mm',candidate['html'])

    def test_production_shortfall_recovers_without_another_model_response(self):
        """A correct data-table exercise with small artwork can complete from one draft."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.table_page();original=deepcopy(page);config=self.config(band)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:self.validate(raw,band),'Activity design 2',
                        response_schema=design_schema({'render_mode':'authored','mechanic':'interpret_table'},config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
                self.assertIn('height:25mm',result['html'])
                self.assertEqual(page,original)
