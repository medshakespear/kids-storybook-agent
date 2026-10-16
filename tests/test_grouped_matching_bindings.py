"""Recover complete blank metadata and caption-owned matching groups without new sources."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.activity_stimuli import normalize_stimulus_ids
from core.content_binding import combined_metadata_fields
from core.creative_generator import ask_json,validate_design,layout_contract
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document,activity_sheet_count
from core.student_workbook import check_response_width
from core.response_schemas import design_schema
from core.workbook_checks import printed_words
from tests.test_student_workbook import evidence_page,workbook_config


def matching_page():
    """Represent caption-owned headings/descriptions wrapped in incorrectly named source slots."""
    raw=evidence_page();exercise=raw['exercise']
    exercise.update(mechanic='text_matching',directions='Match each heading A-D with description 1-4. Use only the printed descriptions.',stimuli=[])
    captions=[('heading_title','Headings'),('head_a','A. Garden Care'),('head_b','B. Library Helpers'),
        ('head_c','C. Recycling'),('head_d','D. Animal Care'),('desc_title','Descriptions'),
        ('desc_1','1. Volunteers place returned books on shelves.'),
        ('desc_2','2. Neighbors water plants and remove weeds.'),
        ('desc_3','3. Workers feed pets and clean their living spaces.'),
        ('desc_4','4. Students separate paper and cans for collection.')]
    exercise['captions']=[{'id':i,'text':t} for i,t in captions]
    exercise['questions']=[{'id':'1','prompt':'Write the matching description number for each heading A-D.',
        'answer':'A-2, B-1, C-4, D-3.','space_mm':35},
        {'id':'2','prompt':'Which detail supports the match for Library Helpers?',
         'answer':'Volunteers place returned books on shelves.','space_mm':35}]
    start=raw['html'].index('<p data-content="stimulus_note_a"')
    end=raw['html'].index('</td>',start)
    groups=('<div data-content="stimulus_headings"><h3 data-content="caption_heading_title"></h3>'+
        ''.join(f'<p data-content="caption_head_{c}" style="margin:0"></p>' for c in 'abcd')+'</div>'+
        '<div data-content="stimulus_descriptions"><h3 data-content="caption_desc_title"></h3>'+
        ''.join(f'<p style="margin:0">{dict(captions)["desc_"+str(i)]}</p>' for i in range(1,5))+'</div>')
    raw['html']=raw['html'][:start]+groups+raw['html'][end:]
    return raw


class GroupedMatchingBindingTests(unittest.TestCase):
    """Exercise native retries and actual WeasyPrint checks for grades 3-4 and 5-6."""

    def ask(self,raw,band,title):
        """Validate a single retained model response with real local geometry recovery."""
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        config=workbook_config(band,simple=True)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(12,12,coherent=True),lambda x:validate_design(x,12,
                quality=config,expected_title=title,require_coherent=True),'Activity design 3',
                response_schema=design_schema({'render_mode':'authored','mechanic':raw['exercise']['mechanic']},config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        return page

    def test_blank_name_date_labels_allow_no_underscores_but_never_filled_values(self):
        """Only a whole pair of empty identification labels qualifies as metadata."""
        for value in ('Name:  Date:','Name:Date:','Name: ____\xa0\xa0Date: ____','Date: Name:'):
            self.assertIsNotNone(combined_metadata_fields(value),value)
        for value in ('Name: Ada Date:', 'Name: Name:', 'Name: Date: explain your choice.', 'Event: Date:'):
            self.assertIsNone(combined_metadata_fields(value),value)

    def test_bare_combined_labels_compile_once_in_both_bands(self):
        """Raw blank labels deduplicate with the deterministic header rather than cause repair."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page();raw['html']=raw['html'].replace('<p data-content="name"></p>',
                '<p style="font-size:12pt">Name: <span> </span> Date:</p>')
            for q,height in zip(raw['exercise']['questions'],(35,50)):q['space_mm']=height
            page=self.ask(raw,band,'Weather Evidence')
            words=printed_words(page['html'])
            self.assertEqual(words.count('Name:'),1);self.assertEqual(words.count('Date:'),1)
            self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])

    def test_grouped_matching_captions_print_once_without_invented_sources(self):
        """Both explicit caption slots and complete literal copies keep their original wording."""
        for band in ('3rd-4th','5th-6th'):
            raw=matching_page();before=deepcopy(raw);page=self.ask(raw,band,'Community Helpers Matching')
            self.assertEqual(raw,before);self.assertEqual(page['exercise']['stimuli'],[])
            self.assertEqual(page['exercise']['captions'],raw['exercise']['captions'])
            self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])
            self.assertNotIn('data-content="stimulus_headings"',page['html'])
            self.assertNotIn('data-content="stimulus_descriptions"',page['html'])
            text=printed_words(page['html'])
            for caption in raw['exercise']['captions']:self.assertEqual(text.count(caption['text']),1)
            doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_response_width(doc,page['quality_profile'])

    def test_real_sources_unknown_placeholders_and_partial_groups_are_preserved(self):
        """No unknown empty source, distinct text, media or duplicate caption is silently discarded."""
        for variant in ('declared','empty','partial','media','duplicate'):
            page=matching_page()
            if variant=='declared':page['exercise']['stimuli']=[{'id':'headings','text':'Independent retained source.'}]
            if variant=='empty':page['html']='<div data-content="stimulus_headings"></div>'
            if variant=='partial':page['html']=page['html'].replace('caption_head_a" style="margin:0"></p>','caption_head_a" style="margin:0">A different task.</p>')
            if variant=='media':page['html']=page['html'].replace('caption_head_a" style="margin:0"></p>','caption_head_a" style="margin:0"><img data-asset="weather"/></p>')
            if variant=='duplicate':page['html']=page['html'].replace('caption_head_b','caption_head_a')
            normalize_stimulus_ids(page,page['exercise'])
            self.assertIn('data-content="stimulus_headings"',page['html'],variant)
        page=matching_page();normalize_stimulus_ids(page,page['exercise']);once=deepcopy(page)
        normalize_stimulus_ids(page,page['exercise']);self.assertEqual(page,once)

    def test_uploaded_classification_diagnostic_uses_bounded_continuation(self):
        """Keep every original source, real table cell and full writing area in both bands."""
        fixture=json.loads((Path(__file__).parent/'fixtures/bulletin_classification_layout.json').read_text())
        for band in ('3rd-4th','5th-6th'):
            raw=deepcopy(fixture['page'])
            # Preserve the diagnostic's learning goal/table; the older-band
            # fixture uses grade-appropriate operands for its independent math.
            if band=='5th-6th':
                raw['exercise']['questions'][1].update(prompt='A school has 24 planning groups. Each group plans 18 decorations. How many decorations are planned?',
                    answer='432 decorations.',calculation={'expression':'24*18','answer':'432'})
            page=self.ask(raw,band,fixture['title'])
            self.assertEqual(activity_sheet_count(page),2)
            self.assertEqual(page['exercise']['stimuli'],raw['exercise']['stimuli'])
            self.assertEqual(page['exercise']['questions'],raw['exercise']['questions'])
            self.assertEqual(page['exercise']['captions'],raw['exercise']['captions'])
            doc=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
            check_document(doc,2);check_response_width(doc,page['quality_profile'])


if __name__=='__main__':unittest.main()
