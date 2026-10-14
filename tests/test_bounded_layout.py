"""Break the overflow/small-art loop with verified, bounded content rearrangements."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.bounded_layout import bounded_authored_layouts
from core.creative_generator import ask_json, layout_contract, validate_design
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class BoundedLayoutTests(unittest.TestCase):
    """Keep table relationships, answers, source facts, assets and full-width workspace."""

    def config(self,band):
        """Use the real varied-activity font and visual floors."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
            stimulus_limit=8,context_caption_limit=24,table_caption_limit=36,items_per_page=2)

    def page(self):
        """Supply a correct exercise with incompatible narrow panels and large decoration."""
        page=authored_page(mechanic='design_compare')
        page['exercise'].update(directions='Read the fictional museum notes and compare the models.',
            stimuli=[{'id':'notes','text':'Fictional museum notes: Students build two plant shelter models. The first has a wide roof and open sides. The second has a narrow roof and closed sides. A display doorway is 80 cm wide. Students compare the model measurements before choosing how to arrange their exhibit.'}],
            captions=[{'id':'feature','text':'Model'},{'id':'width','text':'Width'},
                {'id':'a','text':'Model A'},{'id':'a_width','text':'70 cm'},
                {'id':'b','text':'Model B'},{'id':'b_width','text':'90 cm'}],
            questions=[{'id':'1','prompt':'Explain which model fits the doorway. Use a measurement as evidence.',
                'answer':'Model A fits: its 70 cm width is less than the 80 cm doorway.','space_mm':25},
                {'id':'2','prompt':'Design an exhibit label explaining one useful feature of the model.',
                'answer':'Accept an accurate model feature and a clear label design.','space_mm':35}])
        page['html']=('<div style="width:110mm;padding:25mm">'
            '<h1 data-content="title"></h1><p data-content="name"></p><p data-content="directions"></p>'
            '<div style="width:60mm;padding:20mm"><img data-asset="scene" style="width:50mm;height:60mm"/></div>'
            '<p data-content="stimulus_notes" style="padding:12mm;width:55mm"></p>'
            '<table style="width:80mm;border-collapse:collapse"><tr>'
            '<th data-content="caption_feature"></th><th data-content="caption_width"></th></tr>'
            '<tr><td data-content="caption_a"></td><td data-content="caption_a_width"></td></tr>'
            '<tr><td data-content="caption_b"></td><td data-content="caption_b_width"></td></tr></table>'
            '<div data-content="question_1"></div><div data-content="question_2"></div>'
            '<div style="height:10mm;border:0.4mm solid #167E80"></div></div>')
        return page

    def test_real_loop_fixture_fits_after_one_provider_response_in_both_grades(self):
        """The solver jointly budgets art and text while retaining all exercise data."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.page();original=deepcopy(page);config=self.config(band)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                brief={'render_mode':'authored','mechanic':'design_compare'}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title='Museum Model Studio',require_coherent=True,brief=brief),
                        'Activity design 2',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                for field in ('questions','stimuli','captions'):
                    self.assertEqual(result['exercise'][field],original['exercise'][field])
                self.assertEqual(result['images'],original['images'])
                for height in (10,25,35): self.assertIn(f'height:{height}mm',result['html'])
                self.assertIn('70 cm',result['html']);self.assertIn('90 cm',result['html'])
                self.assertIn('<table',result['html'])
                self.assertEqual(page,original)

    def test_invalid_wording_is_not_removed_and_infeasible_workspace_still_fails(self):
        """Do not publish by dropping instructions or an oversized independent work panel."""
        config=self.config('3rd-4th');page=self.page()
        page['_recovery_config']=config;page['_recovery_title']='Museum Model Studio'
        page['html']+='<p>Invent an unrelated unkeyed task.</p>'
        self.assertEqual(list(bounded_authored_layouts(page,12,8000)),[])
        page=self.page();page['_recovery_config']=config;page['_recovery_title']='Museum Model Studio'
        page['html']+='<div style="height:280mm;border:0.4mm solid #167E80"></div>'
        candidates=list(bounded_authored_layouts(page,12,8000));self.assertTrue(candidates)
        for candidate in candidates:
            self.assertIn('height:280mm',candidate['html'])
            with self.assertRaisesRegex(ValueError,'Design overflow'):
                validate_design(candidate,config['student_font_pt'],quality=config,
                    expected_title='Museum Model Studio',require_coherent=True)

    def test_changed_draft_receives_its_own_bounded_recovery_budget(self):
        """Eight failures on draft one cannot prevent testing a valid second draft."""
        raw=authored_page();raw['html']='first'
        second=deepcopy(raw);second['html']='second'
        api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(p)),finish_reason='stop')]) for p in (raw,second)]

        def candidates(page,font,area):
            """Simulate bounded failed placements followed by a new feasible draft."""
            if page['html']=='second':
                result=deepcopy(page);result['_fit']=True;yield result
            else:
                for n in range(8):
                    result=deepcopy(page);result['_candidate']=n;yield result

        def validate(page):
            """Inject geometric failures to exercise budget ownership independently of rendering."""
            if page.get('_fit'): return page
            raise ValueError('Visuals are too small: use at least 8000 square mm')

        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.layout_recovery.layout_recovery_candidates',side_effect=candidates), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json('Minimum student font: 12pt',validate,'Activity design 2',response_schema={'type':'object'})
        self.assertTrue(result['_fit'])
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_multiple_illustrations_remain_substantial_square_panels(self):
        """Every image retains its identity and the multi-panel area rule passes in both grades."""
        for band in ('3rd-4th','5th-6th'):
            for count in (2,3,4):
                with self.subTest(band=band,count=count):
                    config=self.config(band);page=self.page()
                    page['images']=[{'id':f'scene_{n}','prompt':page['images'][0]['prompt']} for n in range(count)]
                    page['html']=page['html'].replace('<img data-asset="scene" style="width:50mm;height:60mm"/>',
                        ''.join(f'<img data-asset="scene_{n}" style="width:40mm;height:40mm"/>' for n in range(count)))
                    page['_recovery_config']=config;page['_recovery_title']='Museum Model Studio'
                    successes=[]
                    for candidate in bounded_authored_layouts(page,config['minimum_text_pt'],config['visual_area_mm2']):
                        try:
                            result=validate_design(candidate,config['student_font_pt'],quality=config,
                                expected_title='Museum Model Studio',require_coherent=True)
                        except ValueError:
                            continue
                        successes.append(result)
                        self.assertEqual(result['images'],page['images'])
                        self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])
                        for image in page['images']:
                            self.assertEqual(result['html'].count('data-asset="'+image['id']+'"'),1)
                        import re
                        for width,height in re.findall(r'width:([0-9]+)mm;height:([0-9]+)mm;object-fit:contain',result['html']):
                            self.assertEqual(width,height)
                    self.assertTrue(successes)
