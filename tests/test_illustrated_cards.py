"""Replay the uploaded four-illustration sequencing overflow without extra API calls."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,validate_design,layout_contract
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.illustrated_cards import illustrated_source_cards
from core.response_schemas import design_schema
from core.student_workbook import check_response_width
from tests.test_student_workbook import workbook_config
from tests.test_reading_bindings import plain_text


def steps_fixture():
    """Load retained exercise content and layout, excluding transport diagnostics."""
    return json.loads((Path(__file__).parent/'fixtures/ofrenda_illustrated_steps_layout.json').read_text())


class IllustratedCardsTests(unittest.TestCase):
    """Keep paired art, full source wording and full-width handwriting for grades 3-6."""

    def test_actual_diagnostic_finishes_from_one_response_for_both_bands(self):
        """Measure all four enlarged pictures and the requested 40/50mm responses."""
        fixture=steps_fixture()
        for band in ('3rd-4th','5th-6th'):
            config=workbook_config(band);raw=deepcopy(fixture['page']);before=deepcopy(raw)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                 patch('core.creative_generator.time.sleep'):
                result=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                    quality=config,expected_title=fixture['title'],require_coherent=True),'Activity design 3',
                    response_schema=design_schema({'render_mode':'authored','mechanic':'sequencing'},config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(raw,before)
            self.assertEqual(result['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(result['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(result['exercise']['directions'],before['exercise']['directions'])
            self.assertEqual(result['images'],before['images'])
            text=plain_text(result['html'])
            for source in before['exercise']['stimuli']:
                self.assertEqual(text.count(source['text']),1)
            doc=HTML(string=document_markup([fragment(result,True)],12),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_response_width(doc,result['quality_profile'])
            art={};work={}
            for box in doc.pages[0]._page_box.descendants():
                el=box.element
                if el is None:continue
                if box.element_tag=='img':art.setdefault(id(el),box.width*box.height*(25.4/96)**2)
                if box.element_tag=='span' and 'solid #809AA6' in el.get('style',''):
                    work.setdefault(id(el),(box.width*25.4/96,box.border_height()*25.4/96))
            self.assertEqual(len(art),4);self.assertGreaterEqual(sum(art.values()),config['visual_area_mm2'])
            self.assertTrue(all(a>=config['visual_area_mm2']/4 for a in art.values()))
            self.assertEqual(len(work),2);self.assertTrue(all(w>=150 for w,h in work.values()))
            for (_,actual),expected in zip(work.values(),(40,50)):self.assertGreaterEqual(actual,expected-.1)
            self.assertEqual(result['exercise']['captions'],[])

    def candidates(self,raw):
        """Use the same opt-in recovery metadata as the production retry path."""
        fixture=steps_fixture();raw['_recovery_config']=fixture['config'];raw['_recovery_title']=fixture['title']
        return list(illustrated_source_cards(raw,12,8000))

    def test_distinct_caption_evidence_and_independent_workspaces_are_never_removed(self):
        """A nonidentical caption or extra drawing surface must retain its original layout."""
        raw=steps_fixture()['page'];raw['exercise']['captions'][1]['text']='A distinct source detail that must not disappear.'
        self.assertEqual(self.candidates(raw),[])
        raw=steps_fixture()['page'];raw['html']+='<div style="height:25mm;border:1px solid #111"> </div>'
        self.assertEqual(self.candidates(raw),[])
        raw=steps_fixture()['page'];raw['html']+='<p>Additional retained source information.</p>'
        self.assertEqual(self.candidates(raw),[])

    def test_images_cannot_be_reassigned_by_manifest_order(self):
        """Pair only assets and sources sharing an actual authored card container."""
        raw=steps_fixture()['page'];raw['html']=raw['html'].replace('data-asset="img_step2"','data-asset="img_step1"')
        self.assertEqual(self.candidates(raw),[])
        raw=steps_fixture()['page'];raw['images'].reverse()
        result=self.candidates(raw)[0]
        self.assertLess(result['html'].index('img_step1'),result['html'].index('stimulus_step_one'))
        self.assertLess(result['html'].index('img_step4'),result['html'].index('stimulus_step_four'))
        self.assertEqual(result['images'],raw['images'])
        raw=steps_fixture()['page'];raw['_recovery_config']={}
        self.assertEqual(list(illustrated_source_cards(raw,12,8000)),[])


if __name__=='__main__':unittest.main()
