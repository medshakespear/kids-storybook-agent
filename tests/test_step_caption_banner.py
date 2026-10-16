"""Replay baking-card and banner diagnostics plus missing-step/pixel-gap errors."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,validate_design,layout_contract
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.response_schemas import design_schema
from core.print_grid import normalize_print_grid
from core.source_art_manifest import expand_source_art
from core.student_workbook import check_response_width,consolidate_response_panels
from core.work_templates import check_template_geometry
from tests.test_student_workbook import workbook_config
from tests.test_reading_bindings import plain_text


def fixture(name):
    """Load retained authored content without request logs or secrets."""
    return json.loads((Path(__file__).parent/'fixtures'/name).read_text())


class StepCaptionBannerTests(unittest.TestCase):
    """Preserve source cards, derived art identities and full writing dimensions."""

    def ask(self,raw,band,title):
        """Exercise the actual provider-response, local recovery and print-validation path."""
        config=workbook_config(band);api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                quality=config,expected_title=title,require_coherent=True),'Activity design 3',
                response_schema=design_schema({'render_mode':'authored','mechanic':raw['exercise']['mechanic']},config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        doc=HTML(string=document_markup([fragment(result,True)],12),url_fetcher=data_only_fetcher).render()
        check_document(doc,1);check_response_width(doc,result['quality_profile']);check_template_geometry(doc)
        return result,doc

    def test_baking_diagnostic_keeps_four_distinct_step_briefs_and_sources(self):
        """Each numbered picture derives from its actual card, not a repeated generic image."""
        f=fixture('baking_step_cards_layout.json')
        for band in ('3rd-4th','5th-6th'):
            raw=deepcopy(f['page']);before=deepcopy(raw);page,doc=self.ask(raw,band,f['title'])
            self.assertEqual(raw,before);self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(page['exercise']['captions'],before['exercise']['captions'])
            text=plain_text(page['html'])
            for source,asset in zip(before['exercise']['stimuli'],page['images']):
                self.assertEqual(text.count(source['text']),1)
                self.assertIn(source['text'],asset['prompt']);self.assertIn(before['images'][0]['prompt'],asset['prompt'])
                self.assertEqual(page['html'].count('data-asset="'+asset['id']+'"'),1)
            self.assertEqual(len(page['images']),4)
            self.assertIn('height:35mm',page['html']);self.assertIn('height:50mm',page['html'])

    def test_reported_missing_step_captions_restore_beside_matching_sources(self):
        """Reproduce the separately pasted caption_step1..4 slots without inventing labels."""
        f=fixture('baking_step_cards_layout.json');raw=f['page']
        for source in raw['exercise']['stimuli']:
            raw['exercise']['captions'].append({'id':source['id'],'text':source['label']})
        raw['html']=raw['html'].replace('display: flex; gap: 8px;',
            'display:grid;grid-template-columns:repeat(2,1fr);gap:8px;')
        for band in ('3rd-4th','5th-6th'):
            page,_=self.ask(raw,band,f['title']);text=plain_text(page['html'])
            for source in raw['exercise']['stimuli']:
                self.assertEqual(text.count(source['label']),1)
                self.assertIn(source['text'],text)
            self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])

    def test_banner_diagnostic_keeps_full_template_and_both_fifty_mm_answers(self):
        """Consolidate only the identical direction/caption and keep all design-guide text."""
        f=fixture('banner_full_width_layout.json')
        for band in ('3rd-4th','5th-6th'):
            raw=deepcopy(f['page']);page,doc=self.ask(raw,band,f['title'])
            self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])
            self.assertEqual(page['exercise']['stimuli'],raw['exercise']['stimuli'])
            self.assertEqual(page['html'].count('height:50mm'),2)
            text=plain_text(page['html']);self.assertEqual(text.count(raw['exercise']['directions']),1)
            self.assertIn(raw['exercise']['stimuli'][0]['text'],text)
            measured=[]
            for box in doc.pages[0]._page_box.descendants():
                if box.element_tag=='img' and hasattr(box,'replacement'):
                    measured.append((box.width*25.4/96,box.height*25.4/96))
            self.assertEqual(len(measured),1);self.assertGreaterEqual(measured[0][0],167);self.assertGreaterEqual(measured[0][1],94.5)

    def test_absolute_grid_gaps_preserve_physical_spacing(self):
        """Convert absolute units and zero; reject percentages, negative and relative units."""
        for gap,spacing in [('8px','2.116667mm 2.116667mm'),('6pt 0','0mm 2.116667mm'),('0px','0mm 0mm'),('0.2cm','2mm 2mm')]:
            result=normalize_print_grid('<div style="display:grid;grid-template-columns:1fr 1fr;gap:'+gap+'"><p>First</p><p>Second</p></div>')
            self.assertIn('border-spacing:'+spacing,result)
            self.assertLess(result.index('First'),result.index('Second'))
        for gap in ('-2mm','10%','1em','calc(2mm + 1px)','auto'):
            with self.assertRaises(ValueError):normalize_print_grid('<div style="display:grid;grid-template-columns:1fr 1fr;gap:'+gap+'"><p>A</p><p>B</p></div>')

    def test_ambiguous_art_series_and_unrelated_headers_remain_strict(self):
        """An unrelated image ID or missing caption cannot be guessed from list order."""
        f=fixture('baking_step_cards_layout.json');raw=f['page'];before=deepcopy(raw)
        raw['html']=raw['html'].replace('pan_de_muerto_making_4','another_subject')
        expand_source_art(raw,f['config']);self.assertEqual(raw['images'],before['images'])
        raw=deepcopy(before);raw['exercise']['captions'].append({'id':'unrelated','text':'Different contextual information'})
        with self.assertRaisesRegex(ValueError,'missing.*caption_unrelated'):
            validate_design(raw,12,quality=f['config'],expected_title=f['title'],require_coherent=True)

    def test_duplicate_padded_panel_consolidation_preserves_larger_independent_work(self):
        """Count padding in physical height; no truncation of an oversized extra surface."""
        q=[{'id':'1','prompt':'Explain the process.','space_mm':35}]
        for size,pad,removed in [('35px','6px',True),('34mm','2mm',False)]:
            markup='<div data-content="question_1"></div><div style="height:'+size+';padding:'+pad+';border:1px solid #888"></div>'
            result=consolidate_response_panels(markup,q,{'student_workbook':True})
            self.assertEqual('padding:'+pad not in result,removed)


if __name__=='__main__':unittest.main()
