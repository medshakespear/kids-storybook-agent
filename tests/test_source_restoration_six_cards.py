"""Replay the uploaded six-card diagnostic and the separately reported missing source pair."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.calculation_attachment import detach_writing_result,writing_length_text
from core.creative_generator import ask_json,layout_contract,validate_design
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.reading_bindings import restore_source_slots
from core.response_schemas import design_schema
from core.student_workbook import check_response_width,consolidate_response_panels
from tests.test_missing_table_headers import food_comparison_page
from tests.test_reading_bindings import plain_text
from tests.test_student_workbook import workbook_config


def six_card_fixture():
    """Read the retained user diagnostic without provider logs, tokens or secrets."""
    return json.loads((Path(__file__).parent/'fixtures'/'ofrenda_six_cards_layout.json').read_text())


class SourceRestorationSixCardTests(unittest.TestCase):
    """Use real grade contracts and PDF measurement with mocked provider responses."""

    def ask(self,raw,band,title):
        """Generate from one fixture response through the production retry and reflow code."""
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        config=workbook_config(band)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                lambda value:validate_design(value,config['student_font_pt'],quality=config,
                    expected_title=title,require_coherent=True),'Activity design 9',
                response_schema=design_schema({'render_mode':'authored','mechanic':raw['exercise']['mechanic']},config))
        return page,api

    def test_actual_six_card_diagnostic_completes_from_one_response_in_both_bands(self):
        """Keep every card, asset, prompt and 45/50mm answer area while dropping only stray math metadata."""
        fixture=six_card_fixture()
        for band in ('3rd-4th','5th-6th'):
            raw=deepcopy(fixture['page']);before=deepcopy(raw)
            page,api=self.ask(raw,band,fixture['title'])
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['exercise']['questions'][0],before['exercise']['questions'][0])
            question=page['exercise']['questions'][1]
            for field in ('id','prompt','space_mm'):self.assertEqual(question[field],before['exercise']['questions'][1][field])
            self.assertNotIn('calculation',question)
            self.assertEqual(question['answer'],'Explanation should state why the chosen item honors ancestors.')
            self.assertNotIn('Result is 5',page['answers'])
            self.assertEqual(page['images'],before['images'])
            text=plain_text(page['html'])
            for source in before['exercise']['stimuli']:
                self.assertEqual(text.count(source['text']),1)
            self.assertIn('Date:',text)
            self.assertIn('height:45mm',page['html']);self.assertIn('height:50mm',page['html'])
            self.assertNotIn('height:38mm',page['source_layout'].replace(' ',''))
            self.assertNotIn('height:42mm',page['source_layout'].replace(' ',''))
            config=workbook_config(band)
            doc=HTML(string=document_markup([fragment(page,True)],config['student_font_pt']),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_response_width(doc,page['quality_profile'])
            areas=[];seen=set();responses=[]
            for box in doc.pages[0]._page_box.descendants():
                element=box.element
                if element is None or id(element) in seen:continue
                if box.element_tag=='img':
                    seen.add(id(element));areas.append(box.width*box.height*(25.4/96)**2)
                if box.element_tag=='span' and 'solid #809AA6' in element.get('style',''):
                    seen.add(id(element));responses.append((box.width*25.4/96,box.height*25.4/96))
            self.assertEqual(len(areas),2);self.assertGreaterEqual(sum(areas),config['visual_area_mm2'])
            self.assertGreaterEqual(max(areas),config['visual_area_mm2']*.55)
            self.assertEqual(len(responses),2)
            self.assertTrue(all(w>=150 for w,h in responses))
            self.assertGreaterEqual(responses[0][1],44);self.assertGreaterEqual(responses[1][1],49)

    def test_missing_source_pair_is_restored_verbatim_before_questions(self):
        """Reproduce the pasted slot IDs without claiming they occurred in the other diagnostic."""
        for band in ('3rd-4th','5th-6th'):
            raw=food_comparison_page()
            for source,sid in zip(raw['exercise']['stimuli'],('source_one_text','source_two_text')):source['id']=sid
            raw['html']=raw['html'].replace('<p data-content="stimulus_food_a" style="margin:0 0 2mm"></p>','').replace('<p data-content="stimulus_food_b" style="margin:0"></p>','')
            before=deepcopy(raw);page,api=self.ask(raw,band,'Comparing Community Sources')
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(raw,before)
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            text=plain_text(page['html'])
            first,second=[s['text'] for s in before['exercise']['stimuli']]
            self.assertEqual(text.count(first),1);self.assertEqual(text.count(second),1)
            self.assertLess(text.index(first),text.index(second))
            self.assertLess(text.index(second),text.index(before['exercise']['questions'][0]['prompt']))
            self.assertEqual(page['html'].count('height:35mm'),2)

    def test_existing_source_heading_and_restored_card_print_the_label_once(self):
        """A retained caption must remain adjacent to its source, without a second generated label."""
        for band in ('3rd-4th','5th-6th'):
            raw=food_comparison_page()
            raw['exercise']['captions']=[{'id':'source_b_heading','text':'Source B'}]
            raw['html']=raw['html'].replace('<p data-content="stimulus_food_b" style="margin:0"></p>',
                '<p data-content="caption_source_b_heading"></p>')
            checked,_=self.ask(raw,band,'Comparing Community Sources')
            text=plain_text(checked['html'])
            self.assertEqual(text.count('Source B'),1)
            self.assertLess(text.index('Source B'),text.index(raw['exercise']['stimuli'][1]['text']))
            self.assertEqual(checked['exercise']['stimuli'],raw['exercise']['stimuli'])

    def test_partial_presence_and_table_boundaries_preserve_source_order(self):
        """Insert beside existing cards at flow boundaries; unknown references stay unknown."""
        exercise={'render_mode':'authored','stimuli':[{'id':'a'},{'id':'b'},{'id':'c'}]}
        blocks={'stimulus_a':'First','stimulus_b':'Second','stimulus_c':'Third','question_1':'Task'}
        for slot in ('stimulus_a','stimulus_b','stimulus_c'):
            layout=f'<table><tr><td><p data-content="{slot}"></p></td></tr></table><div data-content="question_1"></div>'
            result=restore_source_slots(layout,blocks,exercise,{'student_workbook':True})
            self.assertLess(result.index('stimulus_a'),result.index('stimulus_b'))
            self.assertLess(result.index('stimulus_b'),result.index('stimulus_c'))
            self.assertNotIn('<tr><div',result)
            self.assertEqual(restore_source_slots(result,blocks,exercise,{'student_workbook':True}),result)
        unknown='<div data-content="stimulus_unknown"></div><div data-content="question_1"></div>'
        self.assertIn('stimulus_unknown',restore_source_slots(unknown,blocks,exercise,{'student_workbook':True}))
        self.assertEqual(restore_source_slots(unknown,blocks,exercise,{}),unknown)

    def test_writing_length_is_not_math_but_actual_arithmetic_is_retained(self):
        """Only a verified isolated template clause in a qualitative criterion can be detached."""
        fixture=six_card_fixture();q=deepcopy(fixture['page']['exercise']['questions'][1])
        before=deepcopy(q);detach_writing_result(q)
        self.assertEqual(q['prompt'],before['prompt']);self.assertNotIn('calculation',q)
        self.assertNotIn('2-3',writing_length_text(q['prompt']))
        self.assertIn('12-8',writing_length_text('Explain why 12-8=4 in 2-3 sentences.'))
        for changes in ({'prompt':'Calculate 2*2+1. Write an explanation of why the result is useful.'},
                {'answer':'Result is 6. Explanation should state why the chosen item honors ancestors.'},
                {'answer':'The answer is 5 because five items are required.'},
                {'prompt':'Write an explanation of why the total number is 5.'}):
            other=deepcopy(before);other.update(changes);snapshot=deepcopy(other)
            detach_writing_result(other);self.assertEqual(other,snapshot)

    def test_pale_tinted_duplicate_box_does_not_remove_meaningful_panels(self):
        """Only one adjacent smaller blank answer surface qualifies, with no color-dependent task."""
        profile={'student_workbook':True};q=[{'id':'1','prompt':'Explain your choice.','space_mm':45}]
        prefix='<div data-content="question_1"></div>'
        panel='<div style="height:38mm;border:1px dashed #B23B00;border-radius:4px;background-color:#FFFAFA"></div>'
        self.assertNotIn('height:38mm',consolidate_response_panels(prefix+panel,q,profile))
        for prompt in ('Write in the pink box.','Shade the rectangle.','Compare the colored panels.'):
            self.assertEqual(consolidate_response_panels(prefix+panel,[dict(q[0],prompt=prompt)],profile),prefix+panel)
        for markup in (prefix+panel+panel,prefix+panel.replace('38mm','55mm'),prefix+panel.replace('><','>Extra task.<')):
            self.assertEqual(consolidate_response_panels(markup,q,profile),markup)
