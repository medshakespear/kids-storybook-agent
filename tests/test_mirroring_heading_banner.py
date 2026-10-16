"""Distinguish mirroring headings from commands and fit two-asset banner tasks."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.authored_wording import merge_authored_wording
from core.content_binding import instruction_heading
from core.creative_generator import ask_json,validate_design,layout_contract
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.response_schemas import design_schema
from core.student_workbook import check_response_width
from core.work_templates import check_template_geometry
from tests.test_student_workbook import workbook_config,evidence_page
from tests.test_reading_bindings import plain_text


class MirroringHeadingBannerTests(unittest.TestCase):
    """Keep exact existing wording, diagram geometry and separate student response areas."""

    def test_actual_two_asset_diagnostic_finishes_from_one_response_for_both_bands(self):
        """Retain decorative artwork, a full-sized blank banner and 50/35mm answer areas."""
        f=json.loads((Path(__file__).parent/'fixtures/banner_two_assets_layout.json').read_text())
        for band in ('3rd-4th','5th-6th'):
            raw=deepcopy(f['page']);before=deepcopy(raw);config=workbook_config(band)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                 patch('core.creative_generator.time.sleep'):
                page=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                    quality=config,expected_title=f['title'],require_coherent=True),'Activity design 7',
                    response_schema=design_schema({'render_mode':'authored','mechanic':'write'},config))
            self.assertEqual(api.chat.completions.create.call_count,1);self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(len(page['images']),2)
            self.assertEqual(page['images'][0],before['images'][0])
            for asset in page['images']:self.assertEqual(page['html'].count('data-asset="'+asset['id']+'"'),1)
            self.assertIn('height:50mm',page['html']);self.assertIn('height:35mm',page['html'])
            self.assertIn(before['exercise']['stimuli'][0]['text'],plain_text(page['html']))
            doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_template_geometry(doc);check_response_width(doc,page['quality_profile'])

    def test_reported_heading_binds_locally_without_changing_any_instruction(self):
        """Reproduce the separately pasted label; do not claim it occurred in the attachment."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page();raw['html']=raw['html'].replace('<p data-content="directions"',
                '<h3 style="font-size:12pt;margin:0">Design Rules for Mirroring:</h3><p data-content="directions"')
            before=deepcopy(raw);page=validate_design(raw,12,quality=workbook_config(band),
                expected_title='Weather Evidence Lab',require_coherent=True)
            self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['questions'][0]['prompt'],before['exercise']['questions'][0]['prompt'])
            self.assertEqual(page['exercise']['directions'],before['exercise']['directions'])
            labels=[c for c in page['exercise']['captions'] if c['text']=='Design Rules for Mirroring:']
            self.assertEqual(len(labels),1);self.assertEqual(plain_text(page['html']).count(labels[0]['text']),1)

    def test_scoped_authored_repair_accepts_only_the_complete_original_heading(self):
        """A retained heading may be a caption; new instructions remain prohibited."""
        original=evidence_page();original['html']+='<h3>Design Rules for Mirroring:</h3>'
        correction=deepcopy(original);correction['exercise']['captions']=[{'id':'rules','text':'Design Rules for Mirroring:'}]
        correction['html']=correction['html'].replace('<h3>Design Rules for Mirroring:</h3>',
            '<h3 data-content="caption_rules"></h3>')
        result=merge_authored_wording(original,correction)
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        self.assertEqual(result['exercise']['captions'],correction['exercise']['captions'])
        for label in ('Design Rules for Mirroring: Draw three new symbols.',
                      'Design Rules for Mirroring: Write a paragraph.',
                      'Design Rules for Mirroring: Draw', 'Design Rules for Mirroring'):
            self.assertFalse(instruction_heading(label))
        changed=deepcopy(correction);changed['exercise']['captions'][0]['text']='Design Rules for Mirroring: Draw three new symbols.'
        with self.assertRaises(ValueError):merge_authored_wording(original,changed)


if __name__=='__main__':unittest.main()
