"""Replay the real ofrenda diagnostic without shrinking artwork, fonts or answer areas."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.bounded_layout import bounded_authored_layouts
from core.content_binding import CanonicalTextContainers
from core.creative_generator import ask_json,layout_contract,validate_design
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.response_schemas import design_schema
from core.student_workbook import check_response_width,consolidate_response_panels
from tests.test_student_workbook import workbook_config


def diagnostic_fixture():
    """Load only the sanitized failed page and title, with no provider credentials or logs."""
    return json.loads((Path(__file__).parent/'fixtures'/'ofrenda_layout.json').read_text())


class OfrendaRecoveryTests(unittest.TestCase):
    """Use actual PDF pagination and the same bounded retry path as production."""

    def test_uploaded_table_page_fits_after_one_provider_response_in_both_bands(self):
        """All rows, sources and tasks survive, with a large square image and 95mm of writing."""
        fixture=diagnostic_fixture()
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                config=workbook_config(band);raw=deepcopy(fixture['page']);original=deepcopy(raw)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
                brief={k:raw['exercise'][k] for k in ('render_mode','mechanic')}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(12,12,coherent=True),
                        lambda page:validate_design(page,12,quality=config,expected_title=fixture['title'],
                            require_coherent=True,brief=brief),'Activity design 1',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                for key in ('questions','stimuli','captions','directions','goal','mechanic'):
                    self.assertEqual(result['exercise'][key],original['exercise'][key])
                self.assertEqual(result['images'],original['images']);self.assertEqual(raw,original)
                self.assertNotIn('min-height:18mm',result['source_layout'].replace(' ',''))
                self.assertNotIn('min-height:22mm',result['source_layout'].replace(' ',''))
                parser=CanonicalTextContainers({});parser.feed(result['source_layout']);parser.close()
                tables=[]
                def walk(node):
                    """Confirm the reference table keeps its original five three-column rows."""
                    if isinstance(node,str) or 'comment' in node: return
                    if node['tag']=='table': tables.append(node)
                    for child in node['children']: walk(child)
                for node in parser.root: walk(node)
                reference=next(t for t in tables if any(isinstance(c,dict) and c.get('tag')=='thead' for c in t['children']))
                def rows(node):
                    """Inspect row relationships rather than flattening captions to a text list."""
                    if isinstance(node,str) or 'comment' in node: return []
                    if node['tag']=='tr': return [[dict(c['attrs']).get('data-content') for c in node['children'] if isinstance(c,dict)]]
                    return [r for c in node['children'] for r in rows(c)]
                self.assertEqual(rows(reference),[['caption_'+c['id'] for c in original['exercise']['captions'][i:i+3]] for i in range(0,15,3)])
                doc=HTML(string=document_markup([fragment(result,True)],12),url_fetcher=data_only_fetcher).render()
                check_document(doc,1);check_response_width(doc,result['quality_profile'])
                printed_runs=[b.text for b in doc.pages[0]._page_box.descendants() if hasattr(b,'text')]
                self.assertTrue(any('Cempasúchil' in text for text in printed_runs))
                self.assertTrue(any('Traditional' in text for text in printed_runs))
                boxes={};art=[]
                for box in doc.pages[0]._page_box.descendants():
                    element=getattr(box,'element',None)
                    if element is None: continue
                    if box.element_tag=='img': art.append(box.width*box.height*(25.4/96)**2)
                    if box.element_tag=='span' and 'solid #809AA6' in element.get('style',''):
                        boxes.setdefault(id(element),(box.width*25.4/96,box.height*25.4/96))
                self.assertEqual(len(boxes),2)
                self.assertTrue(all(w>=150 for w,h in boxes.values()))
                self.assertGreaterEqual(min(h for w,h in boxes.values()),44)
                self.assertGreaterEqual(max(h for w,h in boxes.values()),49)
                self.assertGreaterEqual(max(art),config['visual_area_mm2'])

    def test_independent_workspace_is_preserved_and_infeasible_page_still_fails(self):
        """A large, separate panel must never disappear to manufacture a passing page."""
        fixture=diagnostic_fixture();raw=fixture['page'];config=workbook_config('3rd-4th')
        raw['html']+='<div style="height:280mm;border:0.4mm solid #167E80"></div>'
        raw['_recovery_config']=config;raw['_recovery_title']=fixture['title']
        candidates=list(bounded_authored_layouts(raw,12,8000));self.assertTrue(candidates)
        for candidate in candidates:
            self.assertIn('height:280mm',candidate['html'])
            with self.assertRaisesRegex(ValueError,'Design overflow'):
                validate_design(candidate,12,quality=config,expected_title=fixture['title'],require_coherent=True)


class ResponseConsolidationTests(unittest.TestCase):
    """The duplicate-space repair is deliberately narrower than general blank-panel removal."""

    def test_only_one_empty_adjacent_smaller_box_is_absorbed_idempotently(self):
        """Canonical response space stays larger than the redundant authored rectangle."""
        markup='<div data-content="question_1"></div> \n<div style="min-height:18mm;border:1px dashed #999;margin-bottom:3mm"></div>'
        questions=[{'id':'1','space_mm':45}];config={'student_workbook':True}
        result=consolidate_response_panels(markup,questions,config)
        self.assertNotIn('min-height:18mm',result)
        self.assertIn('question_1',result)
        self.assertEqual(consolidate_response_panels(result,questions,config),result)
        self.assertEqual(questions,[{'id':'1','space_mm':45}])

    def test_legacy_content_and_ambiguous_or_meaningful_work_surfaces_stay(self):
        """Never absorb a labeled, repeated, oversized, non-mm or non-adjacent surface."""
        prefix='<div data-content="question_1"></div>'
        blank='<div style="height:18mm;border:1px solid #999"></div>'
        cases=[blank+blank,
            '<div style="height:60mm;border:1px solid #999"></div>',
            '<div style="height:18px;border:1px solid #999"></div>',
            '<div style="height:18mm;border:1px solid #999">Draw here.</div>',
            '<div data-content="caption_space" style="height:18mm;border:1px solid #999"></div>',
            '<div style="height:18mm;border:1px solid #999"><span></span></div>',
            '<div style="height:18mm;border:1px solid #999;background-color:#eee"></div>',
            '<p>Separate workspace</p>'+blank,
            '<div style="height:18mm;border:1px solid #999"><img data-asset="scene"/></div>']
        for suffix in cases:
            markup=prefix+suffix
            self.assertEqual(consolidate_response_panels(markup,[{'id':'1','space_mm':45}],{'student_workbook':True}),markup)
        self.assertEqual(consolidate_response_panels(prefix+blank,[{'id':'1','space_mm':45}],{}),prefix+blank)
