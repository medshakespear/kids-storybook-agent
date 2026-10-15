"""Keep declared labels and protected media intact during local binding recovery."""
from copy import deepcopy
import unittest
from core.label_bindings import restore_declared_labels
from core.content_binding import bind_formatted_canonical_text
from core.creative_generator import validate_design
from tests.test_missing_table_headers import food_comparison_page
from tests.test_student_workbook import workbook_config
from tests.test_reading_bindings import plain_text


class LabelBindingsTests(unittest.TestCase):
    """Exercise both active grade bands and reject ambiguous semantic recovery."""

    def test_declared_metadata_and_flower_label_fit_real_pages(self):
        """Missing captions bind locally with unchanged answers, sources and writing boxes."""
        for band in ('3rd-4th','5th-6th'):
            page=food_comparison_page()
            page['exercise']['captions']=[{'id':'date_label','text':'Date:'},
                {'id':'event_label','text':'Event:'},{'id':'flower_label','text':'A garden flower'}]
            old_id=page['images'][0]['id'];page['images'][0]['id']='flower'
            page['html']=page['html'].replace('data-asset="'+old_id+'"','data-asset="flower"')
            page['html']+='<p>Event:</p>'
            before=deepcopy(page)
            checked=validate_design(page,12,quality=workbook_config(band),expected_title='Stories at the Table',require_coherent=True)
            self.assertEqual(page,before)
            self.assertEqual(checked['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(checked['images'],before['images'])
            self.assertEqual(checked['html'].count('height:35mm'),2)
            text=plain_text(checked['html'])
            for label in ('Event:','A garden flower'):self.assertEqual(text.count(label),1)
            for slot in ('caption_date_label','caption_event_label','caption_flower_label'):
                self.assertEqual(checked['source_layout'].count('data-content="'+slot+'"'),1)

    def test_media_and_nested_slots_are_separated_from_prefilled_text(self):
        """Every protected node survives and canonical text appears exactly once."""
        blocks={'caption_intro':'Retained introduction','title':'Page title'}
        layout='<div data-content="caption_intro">Retained introduction<img data-asset="flower" style="height:90mm"><p data-content="title"></p><div style="height:40mm;border:1px solid blue"></div></div>'
        result=bind_formatted_canonical_text(layout,blocks,separate_protected=True)
        parser_result=result
        self.assertEqual(result.count('data-content="caption_intro"'),1)
        self.assertEqual(result.count('data-asset="flower"'),1)
        self.assertIn('height:40mm',parser_result)
        self.assertIn('data-content="title"',result)
        self.assertTrue(result.startswith('<div >'))

    def test_nested_artwork_compiles_and_preserves_student_space(self):
        """A wrongly bound directions wrapper keeps its one illustration outside the filled text."""
        import re
        for band in ('3rd-4th','5th-6th'):
            page=food_comparison_page()
            page['exercise']['captions']=[{'id':'food_label','text':'Shared family tables'}]
            art=re.search(r'<img[^>]+/>',page['html']).group()
            page['html']=page['html'].replace(art,'')
            page['html']=page['html'].replace('<p data-content="directions" style="margin:0 0 1mm"></p>',
                '<div data-content="directions">'+page['exercise']['directions']+art+'</div>')
            checked=validate_design(page,12,quality=workbook_config(band),expected_title='Stories at the Table',require_coherent=True)
            self.assertEqual(checked['html'].count('data-asset="food"'),1)
            self.assertEqual(checked['html'].count('height:35mm'),2)
            self.assertEqual(plain_text(checked['html']).count('Shared family tables'),1)
            self.assertEqual(plain_text(checked['html']).count(page['exercise']['directions']),1)

    def test_ambiguous_asset_labels_and_new_facts_are_not_invented(self):
        """A missing association or meaningful event value remains a validation error."""
        exercise={'render_mode':'authored','captions':[{'id':'flower_label','text':'Petals'},
            {'id':'event_label','text':'Event: Invented festival'}]}
        blocks={'caption_flower_label':'Petals','caption_event_label':'Event: Invented festival'}
        layout='<div><img data-asset="flower_a"><img data-asset="flower_b"></div>'
        result=restore_declared_labels(layout,blocks,exercise,{'student_workbook':True})
        self.assertNotIn('data-content',result)
        self.assertNotIn('festival',result)
        unrelated='<div data-content="caption_flower_label">Different text<img data-asset="flower"></div>'
        self.assertIn('Different text',bind_formatted_canonical_text(unrelated,blocks,separate_protected=True))

    def test_protected_question_wrapper_remains_strict(self):
        """Do not duplicate a question's canonical response area by moving its graphics."""
        layout='<div data-content="question_1"><img data-asset="flower"></div>'
        self.assertIn('<div data-content="question_1">',bind_formatted_canonical_text(layout,{'question_1':'Task'}))
