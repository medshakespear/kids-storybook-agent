"""Recover complete contextual prose instead of forcing it into short captions."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.authored_wording import merge_authored_wording
from core.creative_generator import ask_json,layout_contract,validate_design
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page

BODY=('An opinion tells how someone feels, but a fact can be checked and proved. '
      'In this studio, transform a personal preference into a testable statement '
      'and describe which observations would help check it.')


class AuthoredWordingRepairTests(unittest.TestCase):
    """Exercise scoped repairs and real print geometry for both active bands."""

    def page(self):
        """Supply a retained statement-writing task and one unbound explanatory paragraph."""
        page=authored_page(mechanic='rewrite_statements')
        page['exercise']['directions']='Read the studio paragraph. Write a statement and explain how to check it.'
        page['exercise']['questions'][0].update(prompt='Write a testable statement about a plant shelter. Explain how to check it.',
            answer='Accept a checkable statement and relevant observations or measurements.',space_mm=25)
        page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<p data-content="directions"></p><p>'+BODY+'</p>')
        return page

    def correction(self,page):
        """Bind the complete original paragraph without moving it into captions."""
        correction=deepcopy(page)
        correction['exercise']['passage']=BODY
        correction['html']=correction['html'].replace('<p>'+BODY+'</p>','<p data-content="passage"></p>')
        return correction

    def config(self,band):
        """Use the production varied-activity profile without altering QCM mode."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    context_caption_limit=24,stimulus_limit=8,items_per_page=2)

    def test_production_repairs_full_prose_in_two_calls_for_both_grades(self):
        """The reported error gets a text-binding repair, not a captions-only layout schema."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.page();original=deepcopy(page);corrected=self.correction(page)
                # Only allowed binding fields may be adopted from a drifting response.
                corrected['images']=[]
                corrected['exercise']['questions'][0].update(answer='Unwanted replacement.',space_mm=0)
                api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')]) for raw in (page,corrected)]
                config=self.config(band);brief={'render_mode':'authored','mechanic':'rewrite_statements'}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title='Opinion Studio',require_coherent=True),
                        'Activity design 4',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,2)
                self.assertEqual(result['html'].count(BODY),1)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('height:25mm',result['html'])
                message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
                self.assertIn('TEXT BINDING',message)
                self.assertIn('VERBATIM',message)
                schema=api.chat.completions.create.call_args.kwargs['response_format']['json_schema']['schema']
                self.assertIn('passage',schema['properties']['exercise']['properties'])
                self.assertEqual(page,original)

    def test_existing_passage_must_be_retained_before_the_complete_addition(self):
        """Existing canonical prose cannot be rewritten during text-binding recovery."""
        page=self.page();page['exercise']['passage']='The studio is a fictional classroom activity.'
        page['html']+='<p data-content="passage"></p>'
        correction=self.correction(page)
        correction['html']=correction['html'].replace('<p data-content="passage"></p>','',1)
        correction['exercise']['passage']=page['exercise']['passage']+' '+BODY
        result=merge_authored_wording(page,correction)
        self.assertEqual(result['exercise']['passage'],correction['exercise']['passage'])
        correction['exercise']['passage']=BODY
        with self.assertRaisesRegex(ValueError,'retain existing'):
            merge_authored_wording(page,correction)

    def test_printed_task_instructions_bind_as_directions_for_both_grades(self):
        """Whole imperative wording clarifies the retained rewrite task without key drift."""
        instruction=('Read the subjective school lunch opinions below. Transform each into a verifiable, '
                     'objective statement that could be checked by observation.')
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page(mechanic='rewrite_statements')
                page['exercise']['directions']='Read the lunch opinions and rewrite them.'
                page['exercise']['questions'][0].update(prompt='Rewrite each lunch opinion as a verifiable statement.',
                    answer='Accept a statement that can be checked through observation.',space_mm=25)
                page['html']=page['html'].replace('<p data-content="directions"></p>',
                    '<p data-content="directions"></p><p>'+instruction+'</p>')
                original=deepcopy(page);good=deepcopy(page)
                good['exercise']['directions']+=' '+instruction
                good['html']=good['html'].replace('<p>'+instruction+'</p>','')
                good['exercise']['questions'][0]['answer']='An unwanted rewritten key.'
                api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')]) for raw in (page,good)]
                config=self.config(band);brief={'render_mode':'authored','mechanic':'rewrite_statements'}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title='Lunch Opinion Studio',require_coherent=True),
                        'Activity design 6',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,2)
                self.assertEqual(result['html'].count(instruction),1)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('height:25mm',result['html'])

    def test_instruction_binding_cannot_add_new_actions_or_quantities(self):
        """Clarification is scoped to the retained task; fragments and new tasks still fail."""
        for instruction in ('Calculate 17 + 4.','Rewrite 17 different statements.',
                            'Write an entirely new task. Draw a poster.'):
            page=self.page();page['html']=page['html'].replace(BODY,instruction)
            correction=deepcopy(page);correction['exercise']['directions']+=' '+instruction
            correction['html']=correction['html'].replace('<p>'+instruction+'</p>','')
            with self.subTest(instruction=instruction),self.assertRaisesRegex(ValueError,'complete original paragraphs'):
                merge_authored_wording(page,correction)
        instruction='Read the examples. Transform the opinions into statements that can be checked.'
        page=self.page();page['html']=page['html'].replace(BODY,instruction)
        correction=deepcopy(page);correction['exercise']['passage']=instruction
        correction['html']=correction['html'].replace('<p>'+instruction+'</p>','<p data-content="passage"></p>')
        with self.assertRaisesRegex(ValueError,'complete original paragraphs'):
            merge_authored_wording(page,correction)

    def test_fragment_paraphrase_and_deleted_prose_are_rejected(self):
        """No shortened caption workaround, new words or dropped task tail can pass."""
        for text in (BODY[:100],BODY.replace('personal preference','a different scenario'),
                     'An opinion is a preference. Write anything you like.'):
            page=self.page();correction=self.correction(page);correction['exercise']['passage']=text
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'complete original paragraphs'):
                merge_authored_wording(page,correction)
        page=self.page();correction=deepcopy(page);correction['html']=correction['html'].replace('<p>'+BODY+'</p>','')
        with self.assertRaisesRegex(ValueError,'cannot discard'):
            merge_authored_wording(page,correction)

    def test_pure_extra_commands_and_exact_puzzles_do_not_use_prose_repair(self):
        """An unanswered additional action cannot become factual passage decoration."""
        page=self.page();page['html']=page['html'].replace(BODY,'Draw three extra flowers.')
        correction=deepcopy(page);correction['exercise']['passage']='Draw three extra flowers.'
        correction['html']=correction['html'].replace('Draw three extra flowers.','')
        with self.assertRaisesRegex(ValueError,'complete original paragraphs'):
            merge_authored_wording(page,correction)
        correction=deepcopy(page)
        correction['exercise']['captions']=[{'id':'extra','text':'Draw three extra flowers.'}]
        correction['html']=correction['html'].replace('<p>Draw three extra flowers.</p>',
            '<p data-content="caption_extra"></p>')
        with self.assertRaisesRegex(ValueError,'hide additional commands'):
            merge_authored_wording(page,correction)
        page=self.page();page['exercise']['render_mode']='exact'
        with self.assertRaisesRegex(ValueError,'shared authored'):
            merge_authored_wording(page,self.correction(page))

    def test_complete_short_heading_binds_alongside_the_prose(self):
        """One repair can bind both contextual prose and its original heading."""
        page=self.page();page['html']+='<h3>Studio Context</h3>'
        correction=self.correction(page)
        correction['html']=correction['html'].replace('<h3>Studio Context</h3>','<h3 data-content="caption_context"></h3>')
        correction['exercise']['captions']=[{'id':'context','text':'Studio Context'}]
        result=merge_authored_wording(page,correction)
        self.assertEqual(result['exercise']['passage'],BODY)
        self.assertIn({'id':'context','text':'Studio Context'},result['exercise']['captions'])

    def test_blank_metadata_is_not_mistaken_for_missing_prose(self):
        """Canonical Name/Date placeholders may replace only the original blank fields."""
        page=self.page();page['html']+='<p>Name: __________ Date: __________</p>'
        correction=self.correction(page)
        correction['html']=correction['html'].replace('<p>Name: __________ Date: __________</p>',
            '<p data-content="name"></p><p data-content="date"></p>')
        result=merge_authored_wording(page,correction)
        self.assertEqual(result['exercise']['passage'],BODY)
