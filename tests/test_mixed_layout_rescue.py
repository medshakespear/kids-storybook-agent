"""Recover mixed source pages with their actual grade and caption contracts."""
from copy import deepcopy
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import json

from core.creative_generator import validate_design, ask_json, layout_contract, density_guidance
from core.layout_recovery import layout_recovery_candidates, supporting_slot_ids
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


def source_page():
    """Return intact authored sources and labels with an excessively tall illustration."""
    page=authored_page(mechanic='compare_choices')
    page['exercise'].update(goal='Compare fictional community planning choices.',
        directions='Read the fictional case. Explain one useful planning choice.',
        captions=[{'id':f'label{i}','text':f'Planning topic {i}'} for i in range(8)],
        stimuli=[{'id':'case','text':'In this fictional case, two classes plan a community display. One chooses clear labels; the other tests whether visitors understand a map. Both ask for feedback before revising their work.'}])
    page['exercise']['questions'][0].update(prompt='Explain why testing the display with visitors may help improve it.',
        answer='Testing can reveal unclear features so students can revise the display.',space_mm=25)
    labels=''.join(f'<span data-content="caption_label{i}" style="margin-right:2mm"></span>' for i in range(8))
    page['html']=('<h1 data-content="title"></h1><p data-content="directions"></p><p>'+labels+'</p>'
                  '<p data-content="stimulus_case"></p><img data-asset="scene" style="width:90mm;height:250mm"/>'
                  '<div data-content="question_1"></div>')
    return page


class MixedLayoutRescueTests(unittest.TestCase):
    """Real print checking protects content while making recovery aware of new mixed fields."""

    def config(self,band):
        """Use the same opt-in profile as the production mixed generator."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,context_caption_limit=24,
                    stimulus_limit=4,table_caption_limit=36,items_per_page=2)

    def test_overflow_exception_retains_real_profile_and_canonical_sources(self):
        """Recovery can validate eight captions and source blocks instead of legacy six-only rules."""
        for band in ('3rd-4th','5th-6th'):
            config=self.config(band);original=source_page()
            try:
                # Exercise the fallback/profile path when direct art resizing
                # cannot offer a candidate; production now also has that route.
                with patch('core.small_overflow.recover_paginated_art',return_value=None):
                    validate_design(original,config['student_font_pt'],quality=config,expected_title='Community Planning',require_coherent=True)
            except ValueError as exc:
                source=exc.layout_source
            else:
                self.fail('Fixture should overflow before lossless recovery')
            self.assertEqual(source['_recovery_config'],config)
            self.assertEqual(source['exercise']['stimuli'],original['exercise']['stimuli'])
            successes=[]
            for rescue in layout_recovery_candidates(source,config['minimum_text_pt'],config['visual_area_mm2']):
                try:
                    result=validate_design(rescue,config['student_font_pt'],quality=config,expected_title='Community Planning',require_coherent=True)
                except ValueError:
                    continue
                successes.append(result)
            self.assertTrue(successes,band)
            for result in successes:
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
                self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
                self.assertIn('height:25mm',result['html'])

    def test_actual_json_flow_recovers_first_provider_response_without_another_call(self):
        """One malformed geometry response can become a measured page without API retry churn."""
        config=self.config('3rd-4th')
        brief={'render_mode':'authored','mechanic':'compare_choices'}
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(source_page())),finish_reason='stop')])
        prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
            page=ask_json(prompt,lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                          expected_title='Community Planning',require_coherent=True,brief=brief),
                          'Activity design 1',response_schema=design_schema(brief,config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        self.assertEqual(len(page['exercise']['captions']),8)
        self.assertEqual(len(page['exercise']['stimuli']),1)

    def test_tiny_artwork_is_enlarged_with_all_sources_and_questions_retained(self):
        """Tiny art and print-fit requirements are evaluated together in both bands."""
        for band in ('3rd-4th','5th-6th'):
            config=self.config(band);raw=source_page()
            raw['html']=raw['html'].replace('width:90mm;height:250mm','width:35mm;height:35mm')
            original=deepcopy(raw)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            brief={'render_mode':'authored','mechanic':'compare_choices'}
            prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
                result=ask_json(prompt,lambda candidate:validate_design(candidate,config['student_font_pt'],quality=config,
                    expected_title='Community Planning',require_coherent=True,brief=brief),'Activity design 1',
                    response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
            self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
            self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
            self.assertNotIn('width:35mm;height:35mm',result['html'])
            import re
            dimensions=re.search(r'data-asset="scene" style="width:([0-9.]+)mm;height:([0-9.]+)mm',result['html'])
            self.assertEqual(dimensions[1],dimensions[2])
            self.assertGreaterEqual(float(dimensions[1])**2,config['visual_area_mm2'])

    def test_source_heading_pairs_keep_original_slot_order(self):
        """Source headings stay adjacent to their corresponding excerpts during recovery."""
        page={'html':'<p data-content="caption_b"></p><p data-content="stimulus_two"></p><p data-content="caption_a"></p><p data-content="stimulus_one"></p>'}
        exercise={'captions':[{'id':'a','text':'Source A'},{'id':'b','text':'Source B'}],
                  'stimuli':[{'id':'one','text':'First excerpt.'},{'id':'two','text':'Second excerpt.'}]}
        self.assertEqual(supporting_slot_ids(page,exercise),['caption_b','stimulus_two','caption_a','stimulus_one'])

    def test_decorated_binding_uses_one_completion_for_both_active_grades(self):
        """Normalize complete styled instructions before measured mixed-page recovery."""
        for band in ('3rd-4th','5th-6th'):
            config=self.config(band);raw=source_page()
            raw['html']=raw['html'].replace('<p data-content="directions"></p>',
                '<p>Read the fictional case. <span style="padding:1mm;border-radius:2mm;background-color:#FFF7DE">Explain one useful planning choice.</span></p>')
            original=deepcopy(raw['exercise'])
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            brief={'render_mode':'authored','mechanic':'compare_choices'}
            prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
                result=ask_json(prompt,lambda candidate:validate_design(candidate,config['student_font_pt'],quality=config,
                    expected_title='Community Planning',require_coherent=True,brief=brief),'Activity design 1',
                    response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(result['exercise']['directions'],original['directions'])
            self.assertEqual(result['exercise']['questions'],original['questions'])
            self.assertEqual(result['exercise']['stimuli'],original['stimuli'])

    def test_data_tables_are_not_flattened_into_unrelated_labels(self):
        """Row/column associations must survive; canonical stack recovery declines real tables."""
        from tests.test_table_captions import table_page
        from core.layout_recovery import single_illustration_recovery
        config=self.config('3rd-4th')
        page=table_page();page['_recovery_config']=config;page['_recovery_title']='Community Hubs'
        self.assertIsNone(single_illustration_recovery(page,12,8000))


if __name__=='__main__':unittest.main()
