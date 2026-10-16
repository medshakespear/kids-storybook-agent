"""Dense real diagnostics must retain references and full handwriting across bounded A4 sheets."""
from copy import deepcopy
from collections import Counter
import json
from pathlib import Path
import re
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,validate_design,layout_contract
from core.creative_layout import (document_markup,fragment,data_only_fetcher,check_document,
    activity_sheet_count,workbook_sheet_count,preflight_pack,pack_markup)
from core.continuation_layout import continuation_boundaries
from core.response_schemas import design_schema
from core.student_workbook import check_response_width
from core.work_templates import check_template_geometry
from tests.test_student_workbook import workbook_config,evidence_page
from tests.test_reading_bindings import plain_text
from tests.test_missing_table_headers import food_comparison_page


NAMES=('dense_vocabulary_layout.json','dense_banner_motif_table_layout.json','dense_landmark_table_layout.json')


def fixture(name):
    """Load the actual retained page without logs or credentials."""
    return json.loads((Path(__file__).parent/'fixtures'/name).read_text())


class ContinuationLayoutTests(unittest.TestCase):
    """Exercise native retries, physical page counting and final answer-sheet placement."""

    def ask(self,f,band):
        """Keep a single model response; perform geometry recovery locally."""
        config=workbook_config(band);raw=deepcopy(f['page']);before=deepcopy(raw);api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                quality=config,expected_title=f['title'],require_coherent=True),'Activity design 8',
                response_schema=design_schema({'render_mode':'authored','mechanic':raw['exercise']['mechanic']},config))
        self.assertEqual(api.chat.completions.create.call_count,1);self.assertEqual(raw,before)
        page['title']=f['title']
        return page

    def test_all_three_uploaded_pages_complete_for_both_bands(self):
        """Preserve every field, real table cell and 50mm full-width response area."""
        for name in NAMES:
            f=fixture(name)
            for band in ('3rd-4th','5th-6th'):
                with self.subTest(name=name,band=band):
                    page=self.ask(f,band);self.assertEqual(activity_sheet_count(page),2)
                    self.assertEqual(continuation_boundaries(page['html']),1)
                    self.assertEqual(page['exercise']['stimuli'],f['page']['exercise']['stimuli'])
                    self.assertEqual(page['exercise']['captions'],f['page']['exercise']['captions'])
                    for new,old in zip(page['exercise']['questions'],f['page']['exercise']['questions']):
                        for key,value in old.items():
                            if key=='prompt':value=re.sub(r'\b(table|cards?|terms?|steps?|template|sources?|passage|illustration) above\b',r'\1 on the reference page',value,flags=re.I)
                            self.assertEqual(new[key],value)
                    doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
                    check_document(doc,2);check_response_width(doc,page['quality_profile']);check_template_geometry(doc)
                    self.assertTrue(any(getattr(b,'element_tag','')=='img' for b in doc.pages[0]._page_box.descendants()))
                    seen=set();boxes=[]
                    for sheet in doc.pages:
                        for b in sheet._page_box.descendants():
                            e=b.element
                            if e is not None and b.element_tag=='span' and 'solid #809AA6' in e.get('style','') and id(e) not in seen:
                                seen.add(id(e));boxes.append((b.width*25.4/96,b.border_height()*25.4/96))
                    self.assertEqual(len(boxes),2);self.assertTrue(all(w>=150 and h>=49.9 for w,h in boxes))
                    text=plain_text(page['html'])
                    for source,count in Counter(s['text'] for s in f['page']['exercise']['stimuli']).items():self.assertEqual(text.count(source),count)
                    if name.startswith('dense_vocabulary'):
                        self.assertEqual(page['source_layout'].count('height:18mm'),4)
                    if name.startswith('dense_landmark'):
                        self.assertEqual(page['source_layout'].count('<tr'),5)

    def test_fifteen_page_workbook_and_answer_key_use_actual_physical_counts(self):
        """Ten activities with three continuations publish as 15 sheets, key last."""
        config=workbook_config('3rd-4th');dense=[self.ask(fixture(n),'3rd-4th') for n in NAMES]
        simple=validate_design(evidence_page(),12,quality=config,expected_title='Weather Evidence Lab',require_coherent=True)
        simple['title']='Weather Evidence Lab'
        pages=dense+[deepcopy(simple) for _ in range(7)]
        pack={'cover':{'html':'<h1 style="font-size:24pt">Workbook QA</h1>','images':[]},'pages':pages}
        self.assertEqual(workbook_sheet_count(pack),15)
        preflight_pack(pack,config)
        doc=HTML(string=pack_markup(pack,config,True),url_fetcher=data_only_fetcher).render()
        self.assertEqual(len(doc.pages),15)
        last=' '.join(getattr(b,'text','') for b in doc.pages[-1]._page_box.descendants())
        self.assertIn('Answer Key',last)
        pack['pages']=[deepcopy(dense[0]) for _ in range(10)]
        with self.assertRaisesRegex(ValueError,'16-page print budget'):preflight_pack(pack,config)

    def test_unknown_symbolic_header_gets_only_its_neutral_label(self):
        """An empty TH may receive Symbolic, never a fact or a classification answer."""
        raw=food_comparison_page();raw['html']=raw['html'].replace('caption_th_feature','caption_th_symbolic')
        page=validate_design(raw,12,quality=workbook_config('3rd-4th'),expected_title='Compare Sources',require_coherent=True)
        self.assertIn({'id':'th_symbolic','text':'Symbolic'},page['exercise']['captions'])
        self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])

    def test_qcm_and_unapproved_multisheet_fragments_stay_single_sheet(self):
        """Only the varied opt-in profile can use exactly one trusted continuation boundary."""
        self.assertEqual(activity_sheet_count({'html':'<p>break-before:page is lesson text.</p>'}),1)
        with self.assertRaises(ValueError):activity_sheet_count({'html':'<div style="break-before:page"></div>'})
        with self.assertRaises(ValueError):activity_sheet_count({'html':'<div style="break-before:page"></div>'*2,
            'quality_profile':{'allow_activity_continuations':True}})

    def test_pipeline_reports_physical_download_page_count(self):
        """Delivery metadata includes continuation sheets instead of counting logical activities."""
        from core.pipeline import generate_book
        two={'html':'<div>Reference</div><div style="break-before:page">Responses</div>',
             'images':[],'quality_profile':{'allow_activity_continuations':True}}
        one={'html':'<p>Activity</p>','images':[]}
        pack={'title':'Dense Workbook','theme':'Geography','grade_band':'3rd-4th',
              'cover':{'images':[]},'pages':[deepcopy(two) for _ in range(3)]+[deepcopy(one) for _ in range(7)]}
        def write_pdf(story,config,path):
            """Stand in for the separately measured PDF builder during publication metadata testing."""
            Path(path).write_bytes(b'%PDF-test')
        with tempfile.TemporaryDirectory() as folder,patch('core.pipeline.text_provider_names'), \
             patch('core.pipeline.image_provider_name'),patch('core.pipeline.generate_varied_pack',return_value=pack), \
             patch('core.pipeline.generate_activity_images'),patch('core.pipeline.build_activity_pdf',side_effect=write_pdf):
            result,path=generate_book(theme='Geography',grade_band='3rd-4th',book_type='varied_activities',output_dir=folder)
            self.assertTrue(path.is_file());self.assertEqual(result['page_count'],15)


if __name__=='__main__':unittest.main()
