"""Replay the skull-side-panel diagnostic with drawing directly on the work material."""
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
from core.work_templates import prepare_work_template,check_template_geometry
from core.page_contract import compile_exercise
from tests.test_student_workbook import workbook_config
from tests.test_reading_bindings import plain_text


def skull_fixture():
    """Read the retained actual page without provider logs or credentials."""
    return json.loads((Path(__file__).parent/'fixtures/skull_template_sidebar_layout.json').read_text())


class IntegratedTemplateTests(unittest.TestCase):
    """Keep writing on its intended surface without duplicating drawing space."""

    def test_actual_page_fits_after_one_response_for_both_grades(self):
        """Keep the 150x110 template, math response and additional 32mm practice panel."""
        fixture=skull_fixture()
        for band in ('3rd-4th','5th-6th'):
            config=workbook_config(band);raw=deepcopy(fixture['page']);before=deepcopy(raw)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                 patch('core.creative_generator.time.sleep'):
                page=ask_json(layout_contract(12,12,coherent=True),lambda value:validate_design(value,12,
                    quality=config,expected_title=fixture['title'],require_coherent=True),'Activity design 8',
                    response_schema=design_schema({'render_mode':'authored','mechanic':'draw'},config))
            self.assertEqual(api.chat.completions.create.call_count,1);self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['exercise']['captions'],before['exercise']['captions'])
            for new,old in zip(page['exercise']['questions'],before['exercise']['questions']):
                for key in old:self.assertEqual(new[key],old[key])
            self.assertEqual(page['images'][0]['local_template'],'skull_symmetry')
            self.assertEqual(page['exercise']['questions'][0]['_template_response_asset'],'skull_template')
            self.assertNotIn('_template_response_asset',page['exercise']['questions'][1])
            self.assertIn('height: 32mm',page['source_layout'])
            self.assertIn('height:40mm',page['html']);self.assertNotIn('height:55mm',page['html'])
            text=plain_text(page['html'])
            for q in before['exercise']['questions']:self.assertIn(q['prompt'],text)
            self.assertIn(before['exercise']['stimuli'][0]['text'],text)
            doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_template_geometry(doc)
            art={};boxes={}
            for box in doc.pages[0]._page_box.descendants():
                el=box.element
                if el is None:continue
                if box.element_tag=='img':art.setdefault(id(el),(box.width*25.4/96,box.height*25.4/96))
                if box.element_tag=='span' and 'solid #809AA6' in el.get('style',''):
                    boxes.setdefault(id(el),(box.width*25.4/96,box.border_height()*25.4/96))
            self.assertEqual(len(art),1)
            w,h=next(iter(art.values()));self.assertGreaterEqual(w,149);self.assertGreaterEqual(h,109)
            self.assertEqual(len(boxes),1)
            w,h=next(iter(boxes.values()));self.assertGreaterEqual(w,150);self.assertGreaterEqual(h,39.9)

    def test_markers_are_derived_not_trusted_and_written_explanations_keep_boxes(self):
        """A model cannot suppress unrelated questions or explanation/practice writing."""
        for prompt in ('Explain in two sentences how symmetry works.',
                       'On the blank right side of the skull template, draw and write two sentences.',
                       'Draw a skull in the space below.',
                       'On the blank right side of the skull template, mirror a motif. Use the space below for practice.'):
            page=skull_fixture()['page'];q=page['exercise']['questions'][0]
            q.update(prompt=prompt,_template_response_asset='skull_template')
            prepare_work_template(page,workbook_config('3rd-4th'))
            self.assertNotIn('_template_response_asset',q)
        page=skull_fixture()['page'];config=workbook_config('3rd-4th')
        prepare_work_template(page,config);once=deepcopy(page);prepare_work_template(page,config)
        self.assertEqual(page,once)

    def test_compiler_requires_the_actual_template_and_matching_task(self):
        """Internal response markers cannot suppress math or unrelated answer boxes."""
        config=workbook_config('3rd-4th');page=skull_fixture()['page']
        page['exercise']['questions'][0]['_template_response_asset']='skull_template'
        with self.assertRaisesRegex(ValueError,'declared local drawing surface'):
            compile_exercise(page,config,'Symmetry Studio')
        page=skull_fixture()['page'];prepare_work_template(page,config)
        page['exercise']['questions'][1]['_template_response_asset']='skull_template'
        with self.assertRaisesRegex(ValueError,'declared local drawing surface'):
            compile_exercise(page,config,'Symmetry Studio')


if __name__=='__main__':unittest.main()
