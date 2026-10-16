"""Separate authored art from exact mechanisms and use the intended banner work surface."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,validate_design,layout_contract
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.media_namespaces import normalize_authored_media
from core.response_schemas import design_schema
from core.work_templates import check_template_geometry,on_template_drawing
from tests.test_student_workbook import evidence_page,workbook_config
from tests.coherent_fixtures import exact_page,visual_examples


class VisualNamespaceBannerTests(unittest.TestCase):
    """Preserve all tasks and actual mechanisms while fixing unambiguous references."""

    def test_actual_banner_diagnostic_uses_template_as_drawing_response(self):
        """One mocked response yields a full-size blank banner and separate 50mm writing box."""
        fixture=json.loads((Path(__file__).parent/'fixtures/banner_on_template_layout.json').read_text())
        for band in ('3rd-4th','5th-6th'):
            raw=deepcopy(fixture['page']);before=deepcopy(raw);config=workbook_config(band)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                 patch('core.creative_generator.time.sleep'):
                page=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                    quality=config,expected_title=fixture['title'],require_coherent=True),'Activity design 5',
                    response_schema=design_schema({'render_mode':'authored','mechanic':'design'},config))
            self.assertEqual(api.chat.completions.create.call_count,1);self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['exercise']['captions'],before['exercise']['captions'])
            for question,old in zip(page['exercise']['questions'],before['exercise']['questions']):
                for key in old:self.assertEqual(question[key],old[key])
            self.assertEqual(page['exercise']['questions'][0]['_template_response_asset'],'banner_art')
            self.assertNotIn('_template_response_asset',page['exercise']['questions'][1])
            self.assertIn('height:50mm',page['html']);self.assertNotIn('height:55mm',page['html'])
            doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_template_geometry(doc)
            art=[]
            for box in doc.pages[0]._page_box.descendants():
                if box.element_tag=='img' and hasattr(box,'replacement'):art.append((box.width*25.4/96,box.height*25.4/96))
            self.assertEqual(len(art),1);self.assertGreaterEqual(art[0][0],167);self.assertGreaterEqual(art[0][1],94.5)

    def test_declared_authored_illustration_can_recover_from_visual_namespace(self):
        """Reproduce the pasted exact-visual error without pretending it is in the attachment."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page();raw['html']=raw['html'].replace('data-asset="weather"','data-visual="weather"')
            before=deepcopy(raw)
            page=validate_design(raw,12,quality=workbook_config(band),expected_title='Weather Evidence Lab',require_coherent=True)
            self.assertEqual(raw,before)
            self.assertEqual(page['images'],before['images'])
            self.assertEqual(page['html'].count('data-asset="weather"'),1);self.assertNotIn('data-visual',page['html'])
            for new,old in zip(page['exercise']['questions'],before['exercise']['questions']):
                self.assertEqual(new['prompt'],old['prompt']);self.assertEqual(new['answer'],old['answer'])

    def test_unknown_conflicting_and_exact_references_are_not_guessed(self):
        """Missing/duplicate computed diagrams remain explicit rather than becoming AI artwork."""
        self.assertFalse(on_template_drawing('Plan your banner design in the blank template above. Sketch flowers.', 'skull_symmetry'))
        self.assertFalse(on_template_drawing('On the blank right side of the skull template, mirror the motifs.', 'banner_plan'))
        raw=evidence_page();raw['html']=raw['html'].replace('data-asset="weather"','data-visual="unknown_puzzle"')
        with self.assertRaisesRegex(ValueError,"undeclared IDs:.*unknown_puzzle"):
            validate_design(raw,12,quality=workbook_config('3rd-4th'),expected_title='Weather Evidence Lab',require_coherent=True)
        raw=evidence_page();raw['html']=raw['html'].replace('data-asset="weather"','data-asset="weather" data-visual="different"')
        original=deepcopy(raw);normalize_authored_media(raw);self.assertEqual(raw,original)
        raw=exact_page(visual_examples()[0]);original=deepcopy(raw)
        normalize_authored_media(raw);self.assertEqual(raw,original)
        raw=evidence_page();raw['html']+='<img data-visual="weather" style="width:50mm;height:50mm"/>'
        with self.assertRaisesRegex(ValueError,'repeated HTML IDs/counts'):
            validate_design(raw,12,quality=workbook_config('3rd-4th'),expected_title='Weather Evidence Lab',require_coherent=True)


if __name__=='__main__':unittest.main()
