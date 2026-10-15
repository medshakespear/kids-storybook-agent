"""Regressions for the uploaded four-card sequencing layout and duplicated source labels."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,layout_contract,validate_design
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.response_schemas import design_schema
from core.student_workbook import adjacent_source_labels,check_response_width
from tests.test_student_workbook import workbook_config


def sequence_fixture():
    """Read only the sanitized model page, without credentials or transport logs."""
    return json.loads((Path(__file__).parent/'fixtures'/'ofrenda_sequence_layout.json').read_text())


class SourceLabelRecoveryTests(unittest.TestCase):
    """Keep every canonical slot while avoiding repeated headings on the same source card."""

    def test_failed_sequence_page_fits_after_one_provider_response_in_both_bands(self):
        """Preserve all four steps, source IDs, answers, art and the requested 35/55mm work areas."""
        fixture=sequence_fixture()
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
                            require_coherent=True,brief=brief),'Activity design 3',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(raw,original);self.assertEqual(page['exercise'],original['exercise'])
                self.assertEqual(page['images'],original['images'])
                chunks=[];parser=HTMLParser(convert_charrefs=True);parser.handle_data=chunks.append
                parser.feed(page['html']);text=' '.join(chunks)
                for source in original['exercise']['stimuli']:
                    self.assertEqual(text.count(source['label']),1)
                    self.assertIn(source['text'],text)
                for caption in original['exercise']['captions']:
                    self.assertEqual(page['source_layout'].count('data-content="caption_'+caption['id']+'"'),1)
                doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
                check_document(doc,1);check_response_width(doc,page['quality_profile'])
                boxes={};art=[]
                for box in doc.pages[0]._page_box.descendants():
                    element=getattr(box,'element',None)
                    if element is None:continue
                    if box.element_tag=='img':art.append(box.width*box.height*(25.4/96)**2)
                    if box.element_tag=='span' and 'solid #809AA6' in element.get('style',''):
                        boxes.setdefault(id(element),(box.width*25.4/96,box.height*25.4/96))
                self.assertEqual(len(boxes),2)
                self.assertTrue(all(w>=150 for w,h in boxes.values()))
                self.assertGreaterEqual(min(h for w,h in boxes.values()),34)
                self.assertGreaterEqual(max(h for w,h in boxes.values()),54)
                self.assertGreaterEqual(max(art),config['visual_area_mm2'])

    def test_label_suppression_requires_exact_adjacent_caption_in_same_parent(self):
        """Wrong-card, distant, unbound and separate-column labels cannot suppress the real label."""
        source=[{'id':'card_a','label':'Step Card A','text':'Clean the table.'}]
        captions=[{'id':'label_a','text':'Step Card A'},{'id':'label_b','text':'Step Card B'}]
        title='<p data-content="caption_label_a"></p>'
        body='<div data-content="stimulus_card_a"></div>'
        config={'student_workbook':True}
        self.assertEqual(adjacent_source_labels(title+' \n'+body,source,captions,config),{'card_a'})
        for markup in (title+'<p>Other content</p>'+body,
                '<div>'+title+'</div><div>'+body+'</div>',
                '<p>Step Card A</p>'+body,
                '<p data-content="caption_label_b"></p>'+body,
                body+title):
            self.assertEqual(adjacent_source_labels(markup,source,captions,config),set())
        self.assertEqual(adjacent_source_labels(title+body,source,captions,{}),set())
        self.assertEqual(adjacent_source_labels(title+body,[{'id':1,'label':'Step Card A'}],captions,config),set())
        self.assertEqual(adjacent_source_labels(title+body,source,None,config),set())

    def test_missing_required_label_caption_is_not_silently_ignored(self):
        """A stale or undeclared caption remains a contract error, rather than disappearing."""
        fixture=sequence_fixture();page=fixture['page'];page['exercise']['captions'].pop(0)
        with self.assertRaisesRegex(ValueError,'Unknown or repeated exercise content slot'):
            validate_design(page,12,quality=workbook_config('3rd-4th'),expected_title=fixture['title'],require_coherent=True)
