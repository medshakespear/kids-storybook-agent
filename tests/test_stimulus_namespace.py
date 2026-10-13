"""Normalize source namespace typos without replacing evidence or changing tasks."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.activity_stimuli import merge_missing_sources,normalize_stimulus_ids
from core.creative_generator import ask_json,layout_contract,validate_design
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class StimulusNamespaceTests(unittest.TestCase):
    """Cover both active grades, provider retries and collision safeguards."""

    def page(self):
        """Supply two real source cards with prefixed IDs and single-prefix HTML slots."""
        page=authored_page(mechanic='compare_scenarios')
        page['exercise']['stimuli']=[
            {'id':'stimulus_placard_text','text':'Fictional placard: The model bridge is 40 cm long.'},
            {'id':'stimulus_student_notes','text':'Fictional student notes: The same model is 20 cm wide.'}]
        page['exercise']['questions'][0].update(prompt='Compare the two records. Describe one measured feature.',
            answer='Accept an accurate comparison of the bridge length and width.',space_mm=25)
        page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<p data-content="directions"></p><p data-content="stimulus_placard_text"></p>'
            '<p data-content="stimulus_student_notes"></p>')
        return page

    def config(self,band):
        """Use the actual mixed activity source and caption allowances."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,items_per_page=2)

    def test_prefix_mismatch_needs_no_provider_repair_in_both_grades(self):
        """The two source texts, task, answer, illustration and writing space stay intact."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.page();original=deepcopy(page);config=self.config(band)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'test')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title='Museum Records',require_coherent=True),
                        'Activity design 2',response_schema=design_schema(
                            {'render_mode':'authored','mechanic':'compare_scenarios'},config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual([s['id'] for s in result['exercise']['stimuli']],['placard_text','student_notes'])
                for source in original['exercise']['stimuli']:
                    self.assertEqual(result['html'].count(source['text']),1)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('height:25mm',result['html'])
                self.assertEqual(page,original)

    def test_single_double_and_repeated_namespace_references_agree(self):
        """Mixed single/double slots normalize coherently and are idempotent."""
        for sid,slot in [('stimulus_placard_text','stimulus_stimulus_placard_text'),
                         ('placard_text','stimulus_stimulus_placard_text'),
                         ('stimulus_stimulus_placard_text','stimulus_placard_text')]:
            with self.subTest(sid=sid,slot=slot):
                page=self.page();page['exercise']['stimuli'][0]['id']=sid
                page['html']=page['html'].replace('data-content="stimulus_placard_text"',f'data-content="{slot}"')
                normalize_stimulus_ids(page,page['exercise'])
                self.assertIn('data-content="stimulus_placard_text"',page['html'])
                self.assertNotIn('stimulus_stimulus_',page['html'])
                after=deepcopy(page);normalize_stimulus_ids(page,page['exercise'])
                self.assertEqual(page,after)

    def test_missing_source_merge_accepts_prefixed_correction_and_retains_existing_text(self):
        """A genuine missing card can be supplied once without rewriting the old evidence."""
        page=self.page();page['exercise']['stimuli'].pop();original=deepcopy(page)
        correction=self.page();correction['exercise']['stimuli'][0]['text']='An unwanted replacement.'
        result=merge_missing_sources(page,correction)
        self.assertEqual(result['exercise']['stimuli'][0]['text'],original['exercise']['stimuli'][0]['text'])
        self.assertEqual(result['exercise']['stimuli'][1]['id'],'student_notes')
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        self.assertEqual(page,original)

    def test_collisions_duplicate_slots_and_unknown_evidence_still_fail(self):
        """Never merge distinct cards or invent a missing source from an alias."""
        page=self.page();page['exercise']['stimuli'].append({'id':'placard_text','text':'Different evidence.'})
        with self.assertRaisesRegex(ValueError,'collide'):
            normalize_stimulus_ids(page,page['exercise'])
        page=self.page();page['html']+='<p data-content="stimulus_stimulus_placard_text"></p>'
        config=self.config('3rd-4th')
        with self.assertRaisesRegex(ValueError,'already printed'):
            validate_design(page,13,quality=config,expected_title='Museum Records',require_coherent=True)
        page=self.page();page['exercise']['stimuli'].pop()
        with self.assertRaisesRegex(ValueError,'unknown'):
            validate_design(page,13,quality=config,expected_title='Museum Records',require_coherent=True)

    def test_literal_content_is_not_rewritten_as_an_attribute(self):
        """Only real slot attributes change; source text, work areas and other attributes survive."""
        page=self.page();page['html']+='<p>stimulus_stimulus_placard_text</p><div style="height:20mm"></div>'
        page['html']=page['html'].replace('<p data-content="stimulus_placard_text"',
            '<p title="stimulus_stimulus_placard_text" data-content="stimulus_stimulus_placard_text"')
        normalize_stimulus_ids(page,page['exercise'])
        self.assertIn('title="stimulus_stimulus_placard_text"',page['html'])
        self.assertIn('>stimulus_stimulus_placard_text</p>',page['html'])
        self.assertIn('height:20mm',page['html'])
