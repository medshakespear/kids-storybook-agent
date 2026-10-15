"""Regress mixed arithmetic, grid, caption and placeholder failures in both active grades."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.math_result_recovery import repair_declared_result
from core.print_grid import normalize_print_grid
from core.response_schemas import design_schema
from tests.test_missing_table_headers import food_comparison_page
from tests.test_student_workbook import workbook_config
from tests.test_reading_bindings import plain_text


def result_page():
    """Combine the reported prose result mismatch with an oversized printable composition."""
    page=food_comparison_page()
    page['exercise']['questions'][1].update(
        prompt='Calculate 2*14+2*6. How many decorative shapes are there in total?',
        answer='The total number of decorative shapes is 56.',
        calculation={'expression':'2*14+2*6','answer':40})
    page['html']='<div style="width:110mm;padding:20mm">'+page['html']+'</div>'
    return page


class MixedErrorChainTests(unittest.TestCase):
    """Run real page compilation and measured print recovery without live AI calls."""

    def validate(self,page,band):
        """Use the production student workbook configuration and complete layout checks."""
        config=workbook_config(band)
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title='Community Design Studio',require_coherent=True)

    def ask(self,responses,band):
        """Drive the native scoped-repair flow using one or more fixture responses."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(p)),finish_reason='stop')]) for p in responses]
        config=workbook_config(band)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                lambda raw:self.validate(raw,band),'Activity design 5',
                response_schema=design_schema({'render_mode':'authored','mechanic':'compare sources'},config))
        return page,api

    def test_prose_result_then_overflow_finishes_from_one_response(self):
        """Recompute only the result token before jointly measuring text, art and answer space."""
        for band in ('3rd-4th','5th-6th'):
            raw=result_page();before=deepcopy(raw)
            page,api=self.ask([raw],band)
            self.assertEqual(api.chat.completions.create.call_count,1)
            q=page['exercise']['questions'][1]
            self.assertEqual(q['answer'],'The total number of decorative shapes is 40.')
            for field in ('prompt','space_mm','calculation'):
                self.assertEqual(q[field],before['exercise']['questions'][1][field])
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['images'],before['images'])
            self.assertEqual(page['html'].count('height:35mm'),2)
            self.assertEqual(raw,before)

    def test_result_sentences_do_not_rewrite_conditions_or_multiple_numbers(self):
        """Only a single affirmative result is identified; semantic criteria stay untouched."""
        for answer in ('Accept a drawing with 56 shapes.','The total is at least 56.',
                'If the total is 56, accept the design.','The total is 56, compared with 40.',
                'The total is not 56.'):
            page=result_page();page['exercise']['questions'][1]['answer']=answer
            self.assertIsNone(repair_declared_result(page,'2'),answer)

    def test_weighted_grid_and_full_row_spans_preserve_order_and_all_cells(self):
        """Use proportional table columns; never reorder positioned areas or invent omitted cells."""
        markup='<div style="display:grid;grid-template-columns:2fr 1fr;gap:2mm">'
        markup+='<p style="grid-column:1 / -1">Heading</p><p>Left</p><p>Right</p>'
        markup+='<div style="grid-column:span 2;height:40mm;border:1px solid blue"></div></div>'
        checked=normalize_print_grid(markup,allow_weighted=True)
        self.assertNotIn('grid-',checked)
        self.assertIn('colspan="2"',checked)
        self.assertIn('width:66.666667%',checked)
        self.assertIn('width:33.333333%',checked)
        self.assertIn('height:40mm',checked)
        self.assertLess(checked.index('Heading'),checked.index('Left'))
        self.assertLess(checked.index('Left'),checked.index('Right'))
        self.assertEqual(normalize_print_grid(checked,allow_weighted=True),checked)
        from weasyprint import HTML
        from core.creative_layout import document_markup
        doc=HTML(string=document_markup([checked],12)).render()
        cells=[b for b in doc.pages[0]._page_box.descendants()
               if b.element_tag=='td' and b.__class__.__name__=='TableCellBox']
        self.assertAlmostEqual(cells[1].width/cells[2].width,2,places=3)
        for style in ('grid-template-columns:2fr 1fr;grid-template-areas:"a b"',
                'grid-template-columns:0fr 1fr','grid-template-columns:2fr 1fr;grid-auto-flow:column'):
            with self.assertRaises(ValueError):
                normalize_print_grid('<div style=\'display:grid;'+style+'\'><p>Retain me</p></div>',allow_weighted=True)

    def test_grid_design_title_and_thumbnail_recover_locally(self):
        """Grid conversion feeds the normal art/spacing solver rather than another design call."""
        for band in ('3rd-4th','5th-6th'):
            raw=food_comparison_page()
            raw['html']=raw['html'].replace('width:90mm;height:90mm','width:35mm;height:37mm')
            raw['html']=raw['html'].replace('<p data-content="directions" style="margin:0 0 1mm"></p>',
                '<div style="display:grid;grid-template-columns:2fr 1fr;gap:2mm">'
                '<p data-content="directions"></p><p data-content="name"></p></div>'
                '<h2 style="font-size:13pt;margin:1mm 0">Day of the Dead: Design Challenge</h2>')
            before=deepcopy(raw);page,api=self.ask([raw],band)
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertIn('Day of the Dead: Design Challenge',plain_text(page['html']))
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(page['images'],before['images'])
            self.assertEqual(page['html'].count('height:35mm'),2)
            self.assertEqual(raw,before)

    def test_paragraph_label_and_repeated_empty_question_bind_once(self):
        """The retained paragraph owns its heading; an extra empty slot adds no second task."""
        for band in ('3rd-4th','5th-6th'):
            page=food_comparison_page()
            page['exercise']['stimuli'][0]['id']='error_paragraph'
            page['html']=page['html'].replace('stimulus_food_a','stimulus_error_paragraph')
            page['exercise']['captions']=[{'id':'error_paragraph_label','text':'Paragraph to Examine'}]
            page['html']+='<div data-content="question_1"></div>'
            before=deepcopy(page);checked=self.validate(page,band)
            text=plain_text(checked['html'])
            self.assertEqual(text.count('Paragraph to Examine'),1)
            self.assertLess(text.index('Paragraph to Examine'),text.index(before['exercise']['stimuli'][0]['text']))
            self.assertEqual(checked['html'].count('height:35mm'),2)
            self.assertEqual(checked['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(checked['images'],before['images'])
            self.assertEqual(page,before)

    def test_unsupported_grid_retry_pins_every_existing_exercise_field(self):
        """A CSS-only retry cannot replace questions, keys, source cards or illustration prompts."""
        for band in ('3rd-4th','5th-6th'):
            raw=food_comparison_page()
            fixed=raw['html']
            raw['html']='<div style=\'display:grid;grid-template-columns:1fr 1fr;grid-template-areas:"a b"\'>'+fixed+'</div>'
            correction={'html':fixed,'images':[], 'exercise':{'questions':[
                {'id':'1','prompt':'Replace the original question.','answer':'Wrong replacement.','space_mm':1}]}}
            checked,api=self.ask([raw,correction],band)
            self.assertEqual(api.chat.completions.create.call_count,2)
            self.assertEqual(checked['exercise']['questions'],raw['exercise']['questions'])
            self.assertEqual(checked['exercise']['stimuli'],raw['exercise']['stimuli'])
            self.assertEqual(checked['images'],raw['images'])

    def test_meaningful_duplicate_questions_remain_errors(self):
        """Unverified extra task wording and independent work surfaces cannot disappear."""
        page=food_comparison_page()
        page['html']+='<div data-content="question_1">Explain an unrelated new task.</div>'
        with self.assertRaisesRegex(ValueError,'already printed'):
            self.validate(page,'3rd-4th')
