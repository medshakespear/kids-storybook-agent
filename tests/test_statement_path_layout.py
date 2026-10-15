"""Keep repaired route cards, large art and working space within the same A4 page."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.response_schemas import design_schema
from core.statement_path_layout import statement_path_layouts
from core.statement_path_repair import merge_repair
from tests import test_statement_path_repair as repairs
from tests import test_statement_maze_and_artwork as fixtures


class StatementPathLayoutTests(unittest.TestCase):
    """Use the production scoped retry loop with real WeasyPrint page measurements."""

    def crowded_page(self):
        """Retain a route whose old stacked composition has no room for its added links."""
        page=repairs.StatementPathRepairTests().source_page()
        page['html']='<div style="width:120mm;padding:18mm">'+page['html']+'</div>'
        return page

    def validate(self,page,band):
        """Compile the complete shared exercise and check actual grade-specific geometry."""
        case=fixtures.StatementMazeAndArtworkTests();config=case.profile(band)
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title=case.diagnostic()['title'],require_coherent=True,
            brief={'render_mode':'authored','mechanic':'statement_path'})

    def generate(self,page,band,responses):
        """Mock only transport; keep all content binding and local layout recovery active."""
        config=fixtures.StatementMazeAndArtworkTests().profile(band);api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(response)),finish_reason='stop')]) for response in responses]
        brief={'render_mode':'authored','mechanic':'statement_path'}
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                lambda raw:self.validate(raw,band),'Activity design 1',response_schema=design_schema(brief,config))
        return result,api

    def prepared(self,page,band):
        """Use the trusted recovery source produced by the actual failing validator."""
        try:
            self.validate(page,band)
        except ValueError as exc:
            return deepcopy(exc.layout_source)
        self.fail('The regression fixture must require measured layout recovery')

    def test_missing_endpoints_then_overflow_finishes_with_one_content_repair_both_grades(self):
        """A scoped route addition no longer needs a series of full-page geometry retries."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.crowded_page();original=deepcopy(page)
                correction=repairs.StatementPathRepairTests().route_update(page)
                repaired=merge_repair(page,correction)
                with self.assertRaisesRegex(ValueError,'Design overflow'):
                    self.validate(repaired,band)
                result,api=self.generate(page,band,[page,correction])
                self.assertEqual(api.chat.completions.create.call_count,2)
                for field in ('questions','stimuli','goal','directions'):
                    self.assertEqual(result['exercise'][field],original['exercise'][field])
                self.assertEqual(result['exercise']['captions'],correction['exercise']['captions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('START: A',result['html']);self.assertIn('FINISH: E',result['html'])
                for source in original['exercise']['stimuli']: self.assertIn(source['text'],result['html'])
                for height in (12,22): self.assertIn(f'height:{height}mm',result['html'])
                self.assertEqual(result['html'].count('data-asset="owl_reporter"'),1)
                second=api.chat.completions.create.call_args_list[1].kwargs
                self.assertEqual(set(second['response_format']['json_schema']['schema']['properties']),{'exercise'})
                self.assertEqual(page,original)

    def test_complete_route_recovers_without_another_model_call_both_grades(self):
        """The fallback works for already-complete original pages as well as repaired ones."""
        for band in ('3rd-4th','5th-6th'):
            page=self.crowded_page()
            page=merge_repair(page,repairs.StatementPathRepairTests().route_update(page))
            result,api=self.generate(page,band,[page])
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])

    def test_source_table_relationships_and_independent_writing_panel_survive(self):
        """Do not flatten a real route data table or discard a standalone blank surface."""
        for band in ('3rd-4th','5th-6th'):
            page=self.crowded_page()
            page=merge_repair(page,repairs.StatementPathRepairTests().route_update(page))
            labels=[{'id':'record_heading','text':'Fictional museum record'},
                {'id':'record_year','text':'Opened in 1985'}]
            page['exercise']['captions']+=labels
            page['html']+='<table style="width:175mm"><tr><th colspan="2" data-content="caption_record_heading"></th></tr><tr><td colspan="2" data-content="caption_record_year"></td></tr></table>'
            page['html']+='<div style="height:10mm;border:0.4mm solid #167E80"></div>'
            original=deepcopy(page);source=self.prepared(page,band)
            config=fixtures.StatementMazeAndArtworkTests().profile(band)
            candidates=list(statement_path_layouts(source,config['minimum_text_pt'],config['visual_area_mm2']))
            self.assertTrue(candidates);successes=[]
            for candidate in candidates:
                self.assertIn('colspan="2"',candidate['html'])
                self.assertIn('height:10mm',candidate['html'])
                try: successes.append(self.validate(candidate,band))
                except ValueError: continue
            self.assertTrue(successes)
            for result in successes:
                self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
                self.assertEqual(result['exercise']['stimuli'],original['exercise']['stimuli'])
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])

    def test_incomplete_routes_unbound_wording_bad_math_and_repeated_sources_cannot_be_rescued(self):
        """A layout fallback establishes no missing facts, route branches or answer correctness."""
        band='3rd-4th';config=fixtures.StatementMazeAndArtworkTests().profile(band)
        page=self.crowded_page();source=self.prepared(page,band)
        self.assertEqual(list(statement_path_layouts(source,12,8000)),[])
        page=merge_repair(page,repairs.StatementPathRepairTests().route_update(page))
        for defect in ('unbound','repeat','math'):
            broken=deepcopy(page)
            if defect=='unbound': broken['html']+='<p>Invent an unrelated task.</p>'
            elif defect=='repeat': broken['html']+='<p data-content="stimulus_start"></p>'
            else:
                broken['exercise']['questions'][0].update(prompt='Calculate 34+23.',answer='58',
                    calculation={'expression':'34+23','answer':'58'})
            broken['_recovery_config']=config
            self.assertEqual(list(statement_path_layouts(broken,12,8000)),[])

    def test_impossible_workspace_still_fails_without_shrinking_or_discarding_it(self):
        """A route cannot pass by hiding an oversized independent writing panel."""
        page=self.crowded_page()
        page=merge_repair(page,repairs.StatementPathRepairTests().route_update(page))
        page['html']+='<div style="height:280mm;border:0.4mm solid #167E80"></div>'
        source=self.prepared(page,'3rd-4th')
        candidates=list(statement_path_layouts(source,12,8000));self.assertTrue(candidates)
        for candidate in candidates:
            self.assertIn('height:280mm',candidate['html'])
            with self.assertRaisesRegex(ValueError,'Design overflow'):
                self.validate(candidate,'3rd-4th')
