"""Recover omitted organizational headings without inventing source facts or worksheet answers."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,merge_layout_repair,validate_design
from core.response_schemas import design_schema
from core.table_captions import prepare_table_captions,empty_table_header_slots
from tests.test_student_workbook import workbook_config


def food_comparison_page(header_id='th_feature'):
    """Match the reported missing-heading pattern in an original, explicitly fictional source task."""
    return {'images':[{'id':'food','prompt':'Two family tables with bread and fruit offerings. Bright orange, plum and leaf-green illustration, no lettering.'}],
        'exercise':{'render_mode':'authored','mechanic':'compare sources',
            'goal':'Compare details in two fictional accounts of a community food celebration.',
            'directions':'Read the two fictional accounts. Use their details to support your answers.',
            'stimuli':[{'id':'food_a','label':'Source A','text':'In this fictional account, Ana brings round bread to her family table. Her grandfather shares a story about baking with his mother.'},
                {'id':'food_b','label':'Source B','text':'In this fictional account, Luis brings fresh fruit to the community table. His aunt shares a memory about tending their garden.'}],
            'questions':[{'id':'1','prompt':'What is one difference between the foods Ana and Luis bring?','answer':'Ana brings round bread; Luis brings fresh fruit.','space_mm':35},
                {'id':'2','prompt':'What do both families do while sharing food? Use one detail from each source.','answer':'They share family memories: a story about baking and a memory about gardening.','space_mm':35}]},
        'html':'<h1 data-content="title" style="font-size:15pt;color:#B35716;margin:0 0 1mm"></h1>'
            '<p data-content="directions" style="margin:0 0 1mm"></p>'
            '<table style="width:186mm;table-layout:fixed;border-collapse:collapse"><tr>'
            '<td style="width:92mm;padding:0 2mm 0 0;vertical-align:top"><img data-asset="food" style="width:90mm;height:90mm"/></td>'
            '<td style="width:94mm;padding:0;vertical-align:top"><p data-content="stimulus_food_a" style="margin:0 0 2mm"></p>'
            '<p data-content="stimulus_food_b" style="margin:0"></p></td></tr></table>'
            '<table style="width:186mm;border-collapse:collapse;margin:1mm 0"><tr><th data-content="caption_'+header_id+'" style="background-color:#FFF2DF"></th></tr>'
            '<tr><td>Family food traditions</td></tr></table>'
            '<div data-content="question_1" style="margin:1mm 0"></div><div data-content="question_2" style="margin:1mm 0"></div>'}


class MissingTableHeaderTests(unittest.TestCase):
    """Use real content contracts and PDF layout checks for both supported grade bands."""

    def validate(self,page,band):
        """Measure the whole authored page with the actual student workbook configuration."""
        return validate_design(page,12,quality=workbook_config(band),
            expected_title='Food and Family Memories',require_coherent=True)

    def test_reported_th_feature_recovers_locally_in_both_grade_bands(self):
        """One response suffices; sources, questions, answers, art and writing heights stay pinned."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                raw=food_comparison_page();before=deepcopy(raw)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
                brief={k:raw['exercise'][k] for k in ('render_mode','mechanic')}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    page=ask_json(layout_contract(12,12,coherent=True),lambda value:self.validate(value,band),
                        'Activity design 2',response_schema=design_schema(brief,workbook_config(band)))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(raw,before);self.assertEqual(page['images'],before['images'])
                for key,value in before['exercise'].items():self.assertEqual(page['exercise'][key],value)
                headings={c['id']:c['text'] for c in page['exercise']['captions']}
                self.assertEqual(headings['th_feature'],'Feature')
                self.assertIn('Family food traditions',page['html'])
                self.assertEqual(page['html'].count('height:35mm'),2)

    def test_layout_repair_can_name_only_an_existing_empty_table_heading(self):
        """Opaque header IDs can receive a neutral label without accepting drifting model content."""
        for band in ('3rd-4th','5th-6th'):
            original=food_comparison_page('heading_x');before=deepcopy(original)
            with self.assertRaisesRegex(ValueError,'caption_heading_x'):self.validate(original,band)
            correction={'html':original['html'],'images':[],
                'exercise':{'captions':[{'id':'heading_x','text':'Feature'}],
                    'questions':[{'id':'1','prompt':'Changed question','answer':'Changed answer','space_mm':0}]}}
            merged=merge_layout_repair(original,correction);checked=self.validate(merged,band)
            self.assertEqual(checked['exercise']['captions'][0],{'id':'heading_x','text':'Feature'})
            self.assertEqual(checked['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(checked['exercise']['stimuli'],before['exercise']['stimuli'])
            self.assertEqual(checked['images'],before['images']);self.assertEqual(original,before)
            correction['html']=correction['html'].replace('caption_heading_x" style="background-color:#FFF2DF"></th>',
                'caption_heading_x" style="background-color:#FFF2DF"><strong>Feature</strong></th>')
            prefilled=self.validate(merge_layout_repair(original,correction),band)
            self.assertEqual(prefilled['exercise']['questions'],before['exercise']['questions'])
            self.assertEqual(prefilled['html'].count('Feature'),1)

    def test_missing_data_facts_and_unrelated_labels_cannot_be_invented(self):
        """Do not infer numbers, names, solutions or instructions from a missing slot's identifier."""
        for slot in ('th_calories','th_correct_answer','th_family_name'):
            page=food_comparison_page(slot);prepare_table_captions(page)
            self.assertNotIn(slot,{c['id'] for c in page['exercise'].get('captions',[])})
        base=food_comparison_page('heading_x')
        for text in ('120 calories','Ana brings bread.','Write your answer.','Correct answer: A'):
            correction={'html':base['html'],'exercise':{'captions':[{'id':'heading_x','text':text}]}}
            with self.assertRaisesRegex(ValueError,'already printed'):merge_layout_repair(base,correction)
        for markup in ('<table><tr><td data-content="caption_th_feature"></td></tr></table>',
                '<p data-content="caption_th_feature"></p>',
                '<th data-content="caption_th_feature"></th>',
                '<table><tr><th data-content="caption_th_feature">A factual statement</th></tr></table>'):
            original={'html':markup,'images':[],'exercise':{'render_mode':'authored'}}
            self.assertEqual(empty_table_header_slots(original),set())
            correction={'html':markup,'exercise':{'captions':[{'id':'th_feature','text':'Feature'}]}}
            with self.assertRaisesRegex(ValueError,'already printed'):merge_layout_repair(original,correction)
        correction={'html':base['html'].replace('<th','<td').replace('</th>','</td>'),
            'exercise':{'captions':[{'id':'heading_x','text':'Feature'}]}}
        with self.assertRaisesRegex(ValueError,'already printed'):merge_layout_repair(base,correction)

    def test_scoped_retry_completes_a_neutral_header_without_replacing_the_exercise(self):
        """The production repair path accepts organizational text and ignores drifting model tasks."""
        for band in ('3rd-4th','5th-6th'):
            original=food_comparison_page('heading_x')
            correction={'html':original['html'],'images':[],
                'exercise':{'captions':[{'id':'heading_x','text':'Feature'}],
                    'questions':[{'id':'1','prompt':'Unrelated task','answer':'Wrong','space_mm':0}]}}
            api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')]) for raw in (original,correction)]
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                 patch('core.creative_generator.time.sleep'):
                page=ask_json(layout_contract(12,12,coherent=True),lambda value:self.validate(value,band),'Activity design 2')
            self.assertEqual(api.chat.completions.create.call_count,2)
            self.assertEqual(page['exercise']['questions'],original['exercise']['questions'])
            self.assertEqual(page['images'],original['images'])
            messages=api.chat.completions.create.call_args.kwargs['messages']
            self.assertIn('originally EMPTY',messages[-1]['content'])

    def test_existing_headings_idempotence_and_table_limits_are_preserved(self):
        """Existing wording wins; repeated headers get separate slots and the 36-cell cap remains."""
        page=food_comparison_page();page['exercise']['captions']=[{'id':'th_feature','text':'Tradition'}]
        prepare_table_captions(page);self.assertEqual(page['exercise']['captions'][0]['text'],'Tradition')
        alias=food_comparison_page();alias['exercise']['captions']=[{'id':'caption_th_feature','text':'Tradition'}]
        self.assertEqual(empty_table_header_slots(alias),set())
        prepare_table_captions(alias);self.assertEqual(alias['exercise']['captions'][0]['text'],'Tradition')
        page=food_comparison_page();page['html']+='<table><tr><th data-content="caption_th_feature"></th></tr></table>'
        first=prepare_table_captions(page);self.assertEqual(prepare_table_captions(page),first)
        self.assertEqual(len([c for c in page['exercise']['captions'] if c['text']=='Feature']),2)
        too_many=food_comparison_page();too_many['html']='<table><tr>'+''.join(
            f'<th data-content="caption_th_feature"></th>' for _ in range(37))+'</tr></table>'
        with self.assertRaisesRegex(ValueError,'36'):prepare_table_captions(too_many)

    def test_header_retry_uses_the_real_table_allowance_when_binding_failed_early(self):
        """Twenty-five retained table cells do not suddenly become excess prose captions."""
        original=food_comparison_page('heading_x')
        original['_caption_context_limit']=6
        original['exercise']['captions']=[{'id':f'entry_{n}','text':f'Retained detail {n}'} for n in range(25)]
        rows=''.join('<tr>'+''.join(f'<td data-content="caption_entry_{n}"></td>' for n in range(i,i+5))+'</tr>' for i in range(0,25,5))
        original['html']='<table><tr><th data-content="caption_heading_x"></th></tr>'+rows+'</table>'
        before=deepcopy(original)
        correction={'html':original['html'],'exercise':{'captions':[{'id':'heading_x','text':'Feature'}]}}
        repaired=merge_layout_repair(original,correction)
        self.assertEqual(repaired['exercise']['captions'][:-1],before['exercise']['captions'])
        self.assertEqual(repaired['exercise']['captions'][-1],{'id':'heading_x','text':'Feature'})
        self.assertEqual(original,before)
