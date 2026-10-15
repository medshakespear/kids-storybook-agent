"""Recover omitted canonical reading content without inventing facts or discarding student work."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.reading_bindings import restore_reading_slots,declare_reading_headings
from core.response_schemas import design_schema
from core.content_binding import CanonicalTextContainers
from tests.test_missing_table_headers import food_comparison_page
from tests.test_student_workbook import workbook_config

PASSAGE=('In this fictional town, Ana brings round bread to a family table. '
         'Her grandfather shares a story about baking with his mother. '
         'Luis brings fresh fruit to the community table. His aunt shares a memory '
         'about tending their garden. Both families share memories while preparing food.')


def omitted_reading_page():
    """Reproduce the missing passage and caption_context_reading pattern using a complete shared task."""
    page=food_comparison_page();page['exercise'].pop('stimuli')
    page['exercise'].update(passage=PASSAGE,captions=[{'id':'context_reading','text':'A Community Reading'}])
    page['html']=page['html'].replace('<p data-content="stimulus_food_a" style="margin:0 0 2mm"></p>','')
    page['html']=page['html'].replace('<p data-content="stimulus_food_b" style="margin:0"></p>','')
    return page


def source_heading_page():
    """Reproduce caption_source_heading adjacent to the retained stimulus_altar_text source."""
    page=food_comparison_page()
    page['exercise']['stimuli']=[{'id':'altar_text','label':'Reading Source','text':PASSAGE}]
    page['html']=page['html'].replace('<p data-content="stimulus_food_a" style="margin:0 0 2mm"></p>',
        '<h2 data-content="caption_source_heading" style="font-size:13pt;margin:0 0 1mm"></h2>'
        '<p data-content="stimulus_altar_text" style="margin:0"></p>')
    page['html']=page['html'].replace('<p data-content="stimulus_food_b" style="margin:0"></p>','')
    return page


def plain_text(markup):
    """Read printable text runs without hiding or normalizing away any task wording."""
    parts=[];parser=HTMLParser(convert_charrefs=True);parser.handle_data=parts.append
    parser.feed(markup);parser.close();return ' '.join(' '.join(parts).split())


class ReadingBindingsTests(unittest.TestCase):
    """Use native retry behavior and actual print validation for both active grade bands."""

    def validate(self,page,band):
        """Compile shared content, then require real A4 pagination, font and visual checks."""
        return validate_design(page,12,quality=workbook_config(band),expected_title='Stories at the Table',require_coherent=True)

    def test_omitted_passage_and_reading_heading_are_restored_after_one_response(self):
        """Every canonical word, answer, image and writing area survives without a model rewrite."""
        for band in ('3rd-4th','5th-6th'):
            for existing in ('neither','heading','passage'):
                with self.subTest(band=band,existing=existing):
                    raw=omitted_reading_page()
                    if existing!='neither':
                        slot='caption_context_reading' if existing=='heading' else 'passage'
                        raw['html']=raw['html'].replace('<div data-content="question_1"',f'<p data-content="{slot}"></p><div data-content="question_1"')
                    before=deepcopy(raw);api=Mock()
                    api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
                    brief={k:raw['exercise'][k] for k in ('render_mode','mechanic')}
                    with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                         patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                         patch('core.creative_generator.time.sleep'):
                        page=ask_json(layout_contract(12,12,coherent=True),lambda value:self.validate(value,band),
                            'Activity design 1',response_schema=design_schema(brief,workbook_config(band)))
                    self.assertEqual(api.chat.completions.create.call_count,1)
                    for key,value in before['exercise'].items():
                        if key!='captions':self.assertEqual(page['exercise'][key],value)
                    self.assertIn(before['exercise']['captions'][0],page['exercise']['captions'])
                    self.assertEqual(page['images'],before['images']);self.assertEqual(raw,before)
                    text=plain_text(page['html'])
                    self.assertEqual(text.count(PASSAGE),1)
                    self.assertEqual(text.count('A Community Reading'),1)
                    self.assertLess(text.index('A Community Reading'),text.index(PASSAGE))
                    self.assertLess(text.index(PASSAGE),text.index(before['exercise']['questions'][0]['prompt']))
                    self.assertEqual(page['html'].count('height:35mm'),2)

    def test_missing_source_heading_reuses_the_adjacent_sources_retained_label(self):
        """The heading binds once; source text, source ID and answers are preserved exactly."""
        for band in ('3rd-4th','5th-6th'):
            raw=source_heading_page();before=deepcopy(raw);page=self.validate(raw,band)
            self.assertEqual(page['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(page['images'],before['images']);self.assertEqual(raw,before)
            captions={c['id']:c['text'] for c in page['exercise']['captions']}
            self.assertEqual(captions['source_heading'],'Reading Source')
            self.assertEqual(plain_text(page['html']).count('Reading Source'),1)
            self.assertEqual(plain_text(page['html']).count(PASSAGE),1)
            declared=source_heading_page()
            declared['exercise']['captions']=[{'id':'source_heading','text':'Reading Source'}]
            declared['html']=declared['html'].replace('<h2 data-content="caption_source_heading" style="font-size:13pt;margin:0 0 1mm"></h2>','')
            restored=self.validate(declared,band)
            self.assertEqual(plain_text(restored['html']).count('Reading Source'),1)
            self.assertEqual(plain_text(restored['html']).count(PASSAGE),1)

    def test_already_printed_formatted_passage_is_bound_without_an_extra_copy(self):
        """Whole-text binding precedes restoration, including mixed inline formatting."""
        page=omitted_reading_page()
        printed=PASSAGE.replace('Ana','<strong>Ana</strong>')
        page['html']=page['html'].replace('<div data-content="question_1"','<p>'+printed+'</p><div data-content="question_1"')
        checked=self.validate(page,'3rd-4th')
        self.assertEqual(plain_text(checked['html']).count(PASSAGE),1)
        self.assertEqual(checked['source_layout'].count('data-content="passage"'),1)

    def test_restoration_uses_a_flow_container_and_preserves_every_other_node(self):
        """A question in a table cell must not cause div/p children to be inserted into tr."""
        layout='<table><tr><td data-content="question_1"></td></tr></table><div style="height:70mm;border:1px solid blue"></div>'
        blocks={'passage':PASSAGE,'question_1':'A question'}
        restored=restore_reading_slots(layout,blocks,{'render_mode':'authored'},workbook_config('3rd-4th'))
        self.assertTrue(restored.startswith('<div data-content="passage"'))
        old=CanonicalTextContainers({});old.feed(layout);old.close()
        new=CanonicalTextContainers({});new.feed(restored);new.close()
        self.assertEqual(new.root[1:],old.root)
        self.assertIsNone(restore_reading_slots(restored,blocks,{'render_mode':'authored'},workbook_config('3rd-4th')))
        self.assertIsNone(restore_reading_slots('<p>No question slot.</p>',blocks,{'render_mode':'authored'},workbook_config('3rd-4th')))
        self.assertIsNone(restore_reading_slots(layout,blocks,{'render_mode':'authored'},{}))

    def test_unknown_labels_duplicates_and_partial_passages_remain_errors(self):
        """Do not fabricate thematic titles, remove duplicate readings or erase partial raw prose."""
        page=omitted_reading_page();page['html']+='<p data-content="passage"></p><p data-content="passage"></p>'
        with self.assertRaisesRegex(ValueError,'already printed'):self.validate(page,'3rd-4th')
        page=source_heading_page();page['html']=page['html'].replace('caption_source_heading','caption_invented_label')
        with self.assertRaisesRegex(ValueError,'caption_invented_label'):self.validate(page,'3rd-4th')
        page=omitted_reading_page();page['html']+='<p>Only half of an invented reading is printed here.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):self.validate(page,'3rd-4th')
        page=source_heading_page();page['exercise']['captions']=[{'id':'source_heading','text':'Retained Title'}]
        self.assertIn('Retained Title',self.validate(page,'3rd-4th')['html'])
        exercise={'render_mode':'authored','questions':[]}
        declare_reading_headings('<p data-content="caption_source_heading"></p>',exercise,workbook_config('3rd-4th'))
        self.assertNotIn('captions',exercise)
        exercise={'render_mode':'authored','passage':PASSAGE}
        declare_reading_headings('<p data-content="caption_source_heading">Unprovided factual content.</p>',exercise,workbook_config('3rd-4th'))
        self.assertNotIn('captions',exercise)

    def test_unfit_reading_content_still_fails_without_truncating_or_shrinking_answers(self):
        """Restoring required content never bypasses actual bounds or student writing-space checks."""
        page=omitted_reading_page();page['exercise']['passage']=' '.join([PASSAGE]*4)
        for q in page['exercise']['questions']:q['space_mm']=80
        before=deepcopy(page)
        with self.assertRaisesRegex(ValueError,'Design overflow') as raised:self.validate(page,'3rd-4th')
        retained=raised.exception.layout_source
        self.assertEqual(retained['exercise']['passage'],before['exercise']['passage'])
        self.assertEqual(retained['exercise']['questions'],before['exercise']['questions'])
        self.assertIn('data-content="passage"',retained['html'])
        self.assertEqual(page,before)
