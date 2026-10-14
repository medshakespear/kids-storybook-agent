"""Recover source-aware diagrams and nested image/data tables without losing task evidence."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page,visual_examples
from tests import test_bounded_layout as bounded_fixtures


class SourceAwareGeometryTests(unittest.TestCase):
    """Cover both production grade bands with native retries and real WeasyPrint bounds."""

    def run_page(self,page,band,title):
        """Try the actual one-response generation/recovery path."""
        config=dict(load_grade_config()[band],purposeful_activity_layout=False,
            stimulus_limit=8,context_caption_limit=24,table_caption_limit=36,items_per_page=2)
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        brief={key:page['exercise'][key] for key in ('render_mode','mechanic')}
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                    expected_title=title,require_coherent=True,brief=brief),
                'Activity design 1',response_schema=design_schema(brief,config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        return result

    def test_exact_visual_grows_out_of_narrow_column_with_source_card_retained(self):
        """The full-diagram reflow includes every source block and its additional question."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=exact_page(visual_examples()[5])
                page['exercise'].update(captions=[{'id':'intro_label','text':'Observation Notes'}],
                    stimuli=[{'id':'space_facts','text':'Fictional classroom notes: Students use telescopes to observe distant objects and compare the clarity of different displays.'}],
                    questions=[{'id':'2','prompt':'Explain one useful display idea from the notes.',
                        'answer':'Accept an observation-related display idea supported by the notes.','space_mm':15}])
                page['html']=page['html'].replace('padding:2mm;border:1mm','width:42mm;padding:2mm;border:1mm')
                page['html']=page['html'].replace('width:175mm;height:150mm','width:150mm;height:95mm')
                page['html']+='<p data-content="caption_intro_label"></p><p data-content="stimulus_space_facts"></p><div data-content="question_2"></div>'
                original=deepcopy(page);result=self.run_page(page,band,'Observation Studio')
                for field in ('visual','stimuli','questions','captions'):
                    self.assertEqual(result['exercise'][field],original['exercise'][field])
                self.assertIn(original['exercise']['stimuli'][0]['text'],result['html'])
                self.assertIn('height:15mm',result['html'])
                self.assertEqual(page,original)

    def test_nested_layout_table_separates_art_without_flattening_data_rows(self):
        """A table around the image/source is layout; the nested measurement table stays intact."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=bounded_fixtures.BoundedLayoutTests().page()
                image='<div style="width:60mm;padding:20mm"><img data-asset="scene" style="width:50mm;height:60mm"/></div>'
                source_start=page['html'].index('<p data-content="stimulus_notes"')
                source_end=page['html'].index('</table>',source_start)+len('</table>')
                source=page['html'][source_start:source_end]
                page['html']=page['html'].replace(image,'').replace(source,
                    '<table style="width:90mm;table-layout:fixed"><tr><td>'+image+'</td><td>'+source+'</td></tr></table>')
                original=deepcopy(page);result=self.run_page(page,band,'Museum Model Studio')
                for field in ('stimuli','questions','captions'):
                    self.assertEqual(result['exercise'][field],original['exercise'][field])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('70 cm',result['html']);self.assertIn('90 cm',result['html'])
                self.assertIn('<table',result['html'])
                for height in (10,25,35): self.assertIn(f'height:{height}mm',result['html'])
