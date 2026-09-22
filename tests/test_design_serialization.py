"""Regression coverage for malformed JSON feedback and renderer-supported gap spacing."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from weasyprint import HTML

from core.creative_generator import parse_design_json, ask_json
from core.creative_layout import clean_style, document_markup, check_document


class SerializationTests(unittest.TestCase):
    """Exercise actual provider-repair flow and flex spacing in the installed renderer."""

    def test_wrapped_json_and_invalid_json(self):
        """Only harmless fences are removed; broken syntax is not guessed."""
        self.assertEqual(parse_design_json('```json\n{"html":"<p>Hi</p>"}\n```'), {'html':'<p>Hi</p>'})
        with self.assertRaises(json.JSONDecodeError):
            parse_design_json('{"html":"<p>Hi</p>" "answers":"one"}')

    def test_json_failure_gets_serialization_repair(self):
        """A syntax error receives precise feedback and a less variable retry."""
        api = Mock()
        api.chat.completions.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"x":1 "y":2}'))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"x":1,"y":2}'))])]
        with patch('core.creative_generator.text_provider_names', return_value=['gemini']), patch('core.creative_generator.text_client', return_value=(api,'test')), patch('core.creative_generator.time.sleep'):
            result = ask_json('test', lambda x:x, 'Test design')
        self.assertEqual(result, {'x':1,'y':2})
        retry = api.chat.completions.create.call_args.kwargs
        self.assertIn('Repair JSON serialization only', retry['messages'][-1]['content'])
        self.assertEqual(retry['temperature'], 0.3)

    def test_flex_gap_is_rendered(self):
        """Verify actual measured gap rather than merely allowing the CSS name."""
        style = clean_style('display:flex;gap:5mm;row-gap:5mm;column-gap:5mm')
        markup = '<div style="' + style + '"><div style="width:40mm;height:20mm">A</div><div style="width:40mm;height:20mm">B</div></div>'
        document = HTML(string=document_markup([markup])).render()
        check_document(document, 1)
        boxes = [b for b in document.pages[0]._page_box.descendants() if b.element_tag == 'div' and type(b).__name__ == 'BlockBox']
        self.assertEqual(len(boxes), 2)
        gap = boxes[1].position_x - boxes[0].position_x - boxes[0].width
        self.assertAlmostEqual(gap, 5*96/25.4, places=2)
