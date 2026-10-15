"""Replay the two-illustration comparison page with duplicate white answer boxes."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,layout_contract,validate_design
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.response_schemas import design_schema
from core.student_workbook import consolidate_response_panels,check_response_width
from tests.test_student_workbook import workbook_config


def comparison_fixture():
    """Read the sanitized failed page, excluding credentials and provider logs."""
    return json.loads((Path(__file__).parent/'fixtures'/'ofrenda_comparison_layout.json').read_text())


class WhiteResponsePanelTests(unittest.TestCase):
    """Keep legitimate tasks and artwork while consolidating smaller duplicate surfaces."""

    def test_two_image_diagnostic_fits_after_one_provider_response_in_both_bands(self):
        """Both original images, sources, keys and 45mm full-width answer areas survive."""
        fixture=comparison_fixture()
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                raw=deepcopy(fixture['page']);original=deepcopy(raw);config=workbook_config(band)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
                brief={k:raw['exercise'][k] for k in ('render_mode','mechanic')}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    page=ask_json(layout_contract(12,12,coherent=True),
                        lambda value:validate_design(value,12,quality=config,expected_title=fixture['title'],
                            require_coherent=True,brief=brief),'Activity design 1',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(raw,original);self.assertEqual(page['exercise'],original['exercise'])
                self.assertEqual(page['images'],original['images'])
                self.assertNotIn('height:35mm',page['source_layout'].replace(' ',''))
                for asset in original['images']:
                    self.assertEqual(page['source_layout'].count('data-asset="'+asset['id']+'"'),1)
                doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
                check_document(doc,1);check_response_width(doc,page['quality_profile'])
                areas=[];boxes={}
                for box in doc.pages[0]._page_box.descendants():
                    element=getattr(box,'element',None)
                    if element is None:continue
                    if box.element_tag=='img':areas.append(box.width*box.height*(25.4/96)**2)
                    if box.element_tag=='span' and 'solid #809AA6' in element.get('style',''):
                        boxes.setdefault(id(element),(box.width*25.4/96,box.height*25.4/96))
                self.assertEqual(len(areas),2)
                self.assertGreaterEqual(sum(areas),config['visual_area_mm2'])
                self.assertTrue(all(a>=0.75*config['visual_area_mm2']/2 for a in areas))
                self.assertEqual(len(boxes),2)
                self.assertTrue(all(w>=150 and h>=44 for w,h in boxes.values()))

    def test_equivalent_opaque_white_fills_are_recognized_without_changing_workspace(self):
        """Paper-white paint is harmless; canonical height and model inputs are unchanged."""
        questions=[{'id':'1','space_mm':45}];profile={'student_workbook':True}
        prefix='<div data-content="question_1"></div>'
        for prop in ('background','background-color'):
            for color in ('white','#fff','#FFFFFF','rgb(255,255,255)','rgba(255,255,255,1)'):
                markup=prefix+f'<div style="height:35mm;border:1px dashed #999;border-radius:4px;{prop}:{color}"></div>'
                result=consolidate_response_panels(markup,questions,profile)
                self.assertNotIn('height:35mm',result)
                self.assertIn('question_1',result)
                self.assertEqual(consolidate_response_panels(result,questions,profile),result)
        self.assertEqual(questions,[{'id':'1','space_mm':45}])

    def test_colored_labeled_larger_or_independent_white_surfaces_are_preserved(self):
        """Never hide real work, illustrations, multi-part panels or meaningful backgrounds."""
        prefix='<div data-content="question_1"></div>'
        profile={'student_workbook':True};questions=[{'id':'1','space_mm':45}]
        for background in ('#eee','transparent','rgba(255,255,255,0.5)',
                'linear-gradient(white,blue)','url(https://example.com/image.png)','white no-repeat'):
            markup=prefix+f'<div style="height:35mm;border:1px solid #999;background:{background}"></div>'
            self.assertEqual(consolidate_response_panels(markup,questions,profile),markup)
        blank='<div style="height:35mm;border:1px solid #999;background:white"></div>'
        cases=[prefix+blank+blank,
            prefix+blank.replace('35mm','55mm'),
            prefix+blank.replace('><','>Draw here.<'),
            prefix+blank.replace('<div style','<div data-content="caption_workspace" style'),
            prefix+'<p>Independent work</p>'+blank,
            prefix+blank.replace('><','><img data-asset="scene"/><'),
            prefix+blank.replace('background:white','background:white!important')]
        for markup in cases:
            self.assertEqual(consolidate_response_panels(markup,questions,profile),markup)
        self.assertEqual(consolidate_response_panels(prefix+blank,questions,{}),prefix+blank)
