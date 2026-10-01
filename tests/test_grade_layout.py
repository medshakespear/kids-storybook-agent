"""Regressions for readable Pre-K layouts and actionable page repair feedback."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from weasyprint import HTML
from core.creative_generator import ask_json, layout_contract, validate_design
from core.creative_layout import fragment, document_markup, data_only_fetcher
from core.pipeline import load_grade_config


class GradeLayoutTests(unittest.TestCase):
    """Keep font floors and worksheet response space consistent across render passes."""

    def page(self):
        """Return a large visual and a usable response area for a preschool task."""
        return dict(images=[dict(id='pumpkin',prompt='A large orange pumpkin.')],
                    answers='Open response: accept a decorated pumpkin.',
                    html='<h2>Decorate a pumpkin</h2><p style="font-size:12px">Draw a face.</p>'
                         '<img data-asset="pumpkin" style="width:175mm;height:100mm"/>'
                         '<div style="height:60mm;border:1mm solid teal">Your face goes here.</div>')

    def test_preschool_font_floor_applies_before_fit_and_final_render(self):
        """A small model caption is raised locally rather than consuming another API call."""
        fixed = validate_design(self.page(),15,quality=load_grade_config()['Pre-K-K'])
        self.assertIn('font-size:14pt',fragment(fixed,True))
        doc=HTML(string=document_markup([fragment(fixed,True)],15),url_fetcher=data_only_fetcher).render()
        self.assertEqual(len(doc.pages),1)
        boxes=[b for b in doc.pages[0]._page_box.descendants() if getattr(b,'text','')]
        self.assertTrue(all(b.style['font_size']*.75 >= 14-.01 for b in boxes))
        self.assertIn('height:60mm',fixed['html'])

    def test_quality_page_compacts_excess_spacing_without_reducing_work_area(self):
        """Large cosmetic outer margins can be reduced without changing the task height."""
        page=self.page()
        page['html']='<div style="padding-top:110mm">'+page['html']+'</div>'
        fixed=validate_design(page,15,quality=load_grade_config()['Pre-K-K'])
        self.assertIn('padding-top:6mm',fixed['html'])
        self.assertIn('height:60mm',fixed['html'])
        self.assertIn('height:100mm',fixed['html'])

    def test_impossible_height_reports_measured_overflow(self):
        """Unfit essential workspace still fails with useful geometry for the model."""
        page=self.page()
        page['html']+='<div style="height:300mm">Draw here.</div>'
        with self.assertRaisesRegex(ValueError,'expected 1 pages, got'):
            validate_design(page,15,quality=load_grade_config()['Pre-K-K'])

    def test_repair_uses_grade_floor_instead_of_global_11pt(self):
        """Overflow correction cannot instruct Gemini to violate the next validation check."""
        api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({'ok':True})),finish_reason='stop')])
        calls=[]
        def validate(raw):
            """Fail the first draft with the same reported overflow as the production log."""
            calls.append(raw)
            if len(calls)==1:raise ValueError('Design overflow: expected 1 pages, got 2')
            return raw
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            ask_json(layout_contract(15,14),validate,'Activity design 3')
        repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('below 14pt',repair)
        self.assertIn('never omit the images list',repair)
        self.assertNotIn('below 11pt',repair)

    def test_illustration_repair_keeps_exact_visual_references(self):
        """A manifest repair supports both real artwork and Python-rendered puzzles."""
        api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({'ok':True})),finish_reason='stop')])
        attempts=[]
        def validate(raw):
            """Reproduce the reported illustration-list error once."""
            attempts.append(raw)
            if len(attempts)==1:raise ValueError('Supply 1-4 meaningful illustrations, or exact visuals with images=[]')
            return raw
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            ask_json(layout_contract(12,12),validate,'Activity design 1')
        repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('OR data-visual',repair)
        self.assertIn('images=[] is allowed ONLY',repair)
        self.assertNotIn('Every <img> in html must use data-asset',repair)

    def test_unsupported_overflow_style_does_not_trigger_activity_recomposition(self):
        """CSS syntax correction must not redesign or lose an otherwise usable exercise."""
        api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({'ok':True})),finish_reason='stop')])
        attempts=[]
        def validate(raw):
            """Reject one unsupported style, then accept the corrected unit."""
            attempts.append(raw)
            if len(attempts)==1:raise ValueError('CSS overflow may not hide, clip or scroll printable content; remove it')
            return raw
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            ask_json(layout_contract(12,12),validate,'Activity design 1')
        repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertNotIn('Recompose this same activity',repair)
