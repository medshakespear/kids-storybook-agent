"""Replay paired calavera references and a half-banner with a genuine design-rule table."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from PIL import Image,ImageChops
from weasyprint import HTML
from core.blank_templates import template_png
from core.creative_generator import ask_json,validate_design,layout_contract,generate_creative_images
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.response_schemas import design_schema
from core.student_workbook import check_response_width
from core.work_templates import check_template_geometry,on_template_drawing
from tests.test_student_workbook import workbook_config
from tests.test_reading_bindings import plain_text


def symmetry_fixture(name):
    """Read only retained page content and its real grade configuration."""
    return json.loads((Path(__file__).parent/'fixtures'/name).read_text())


class ReferenceSymmetryTests(unittest.TestCase):
    """Keep copying references faithful, exact work surfaces large, and table relationships intact."""

    def test_reference_questions_keep_separate_writing_when_they_ask_for_it(self):
        """Mentioning a template or mirror is insufficient to suppress a written response."""
        stem='Examine the left reference motifs and blank right half of the banner template. '
        for action in ('Describe the mirror pattern.', 'Identify the mirror shapes.',
                       'Calculate how many mirror shapes are required.', 'Compare the mirror pattern sizes.'):
            self.assertFalse(on_template_drawing(stem+action,'banner_symmetry'))

    def ask(self,raw,band,title):
        """Use one mocked provider response and real content/layout validation."""
        config=workbook_config(band);api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                quality=config,expected_title=title,require_coherent=True),'Activity design 7',
                response_schema=design_schema({'render_mode':'authored','mechanic':raw['exercise']['mechanic']},config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
        check_document(doc,1);check_template_geometry(doc);check_response_width(doc,page['quality_profile'])
        return page,doc

    def test_actual_diagnostics_complete_for_both_grade_bands(self):
        """Keep all source text, keys, captions, a 50mm separate response, and exact table rows."""
        for name in ('calavera_reference_pair_layout.json','banner_symmetry_table_layout.json'):
            f=symmetry_fixture(name)
            for band in ('3rd-4th','5th-6th'):
                with self.subTest(name=name,band=band):
                    raw=deepcopy(f['page']);before=deepcopy(raw);page,doc=self.ask(raw,band,f['title'])
                    self.assertEqual(raw,before)
                    self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
                    self.assertEqual(page['exercise']['captions'],before['exercise']['captions'])
                    for new,old in zip(page['exercise']['questions'],before['exercise']['questions']):
                        for key in old:self.assertEqual(new[key],old[key])
                    self.assertIn('_template_response_asset',page['exercise']['questions'][0])
                    self.assertNotIn('_template_response_asset',page['exercise']['questions'][1])
                    self.assertEqual(page['html'].count('height:50mm'),1)
                    text=plain_text(page['html'])
                    for source in before['exercise']['stimuli']:self.assertIn(source['text'],text)
                    for caption in before['exercise']['captions']:self.assertEqual(text.count(caption['text']),1)
                    for asset in page['images']:self.assertEqual(page['html'].count('data-asset="'+asset['id']+'"'),1)
                    if name.startswith('banner'):
                        self.assertEqual(page['images'][0]['local_template'],'banner_symmetry')
                        self.assertEqual(page['html'].count('<tr'),4)
                        self.assertIn('caption_th_step',page['source_layout'])
                        for row in ('td_1a','td_2a','td_3a'):self.assertIn('caption_'+row,page['source_layout'])
                    else:
                        self.assertEqual([a['local_template'] for a in page['images']],['skull_reference','skull_symmetry'])

    def test_reference_pixels_match_and_right_banner_half_is_blank(self):
        """The source and work template share identical left motifs; no AI interpretation is needed."""
        source=Image.open(io.BytesIO(template_png('skull_reference'))).convert('RGB')
        work=Image.open(io.BytesIO(template_png('skull_symmetry'))).convert('RGB')
        self.assertIsNone(ImageChops.difference(source.crop((0,0,900,1320)),work.crop((0,0,900,1320))).getbbox())
        banner=Image.open(io.BytesIO(template_png('banner_symmetry'))).convert('RGB')
        self.assertEqual(banner.size,(1800,1020))
        self.assertGreater(sum(banner.crop((150,150,850,860)).convert('L').histogram()[:150]),100)
        self.assertEqual(banner.crop((950,150,1650,860)).getextrema(),((255,255),)*3)

    def test_reference_and_work_assets_both_bypass_ai_and_match_final_preview(self):
        """No Cloudflare call or Gemini image review is needed for exact copying materials."""
        for name in ('calavera_reference_pair_layout.json','banner_symmetry_table_layout.json'):
            f=symmetry_fixture(name);page,_=self.ask(f['page'],'3rd-4th',f['title'])
            pack={'cover':{'images':[]},'pages':[page],'art_direction':'Warm classroom colors'}
            with tempfile.TemporaryDirectory() as folder,patch('core.creative_generator.generate_images') as provider:
                generate_creative_images(pack,{},folder)
                provider.assert_not_called()
                for asset in page['images']:
                    self.assertEqual(Path(asset['path']).read_bytes(),template_png(asset['local_template']))
                self.assertEqual(fragment(page,True),fragment(page,False))
                self.assertEqual(pack['image_review']['status'],'disabled')


if __name__=='__main__':unittest.main()
