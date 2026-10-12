"""Long comparison sources remain intact without consuming short caption slots."""
from copy import deepcopy
import unittest
from core.activity_stimuli import prepare_stimuli
from core.creative_generator import validate_design, density_guidance
from core.pipeline import load_grade_config
from core.response_schemas import exercise_schema
from tests.coherent_fixtures import authored_page


SOURCES=[
    'Fictional case: A class chooses reusable bottles for a field trip. Students refill them at a safe drinking-water point and carry them in their own bags.',
    'Fictional case: Another class shares a poster listing useful supplies. Students compare the list with their plans before choosing what to bring on the trip.',
    'Fictional case: A third class reviews the route with a teacher. Students plan breaks and agree to ask the teacher for help if they need to change the plan.',
    'Fictional case: A fourth class checks the weather forecast with a teacher. Students discuss which clothing suits the conditions without making absolute safety promises.',
]


class ActivityStimuliTests(unittest.TestCase):
    """Bind complete source blocks with grade-aware layout guidance and unchanged tasks."""

    def test_reported_four_overlong_captions_move_to_source_slots_and_fit_both_grades(self):
        """Four short scenarios, substantial artwork and writing space fit on one A4 page."""
        for band in ('3rd-4th','5th-6th'):
            config=dict(load_grade_config()[band],purposeful_activity_layout=False,stimulus_limit=4,
                        context_caption_limit=24,table_caption_limit=36)
            page=authored_page(mechanic='compare_scenarios')
            page['exercise'].update(goal='Compare fictional planning choices.',directions='Read the four fictional cases. Compare two planning choices.',
                                    captions=[{'id':f's{i}_text','text':text} for i,text in enumerate(SOURCES,1)])
            page['exercise']['questions']=[{'id':'1','prompt':'Choose two cases. Explain how their planning choices differ.',
                                         'answer':'Accept an accurate comparison of two distinct planning choices from the fictional cases.','space_mm':25}]
            page['html']=('<h1 data-content="title" style="font-size:20pt;color:#167E80"></h1><p data-content="directions"></p>'
                          '<table style="width:175mm;border-collapse:collapse"><tr><td style="vertical-align:top">'
                          '<img data-asset="scene" style="width:90mm;height:90mm"/></td><td style="vertical-align:top">'+
                          ''.join(f'<p data-content="caption_s{i}_text" style="margin:0 0 2mm;line-height:1.15"></p>' for i in range(1,5))+
                          '</td></tr></table><div data-content="question_1" style="margin-top:3mm"></div>')
            original=deepcopy(page)
            result=validate_design(page,config['student_font_pt'],quality=config,expected_title='Planning Choices',require_coherent=True)
            self.assertEqual(page,original)
            self.assertEqual([s['text'] for s in result['exercise']['stimuli']],SOURCES)
            self.assertEqual(result['exercise']['captions'],[])
            for text in SOURCES:self.assertIn(text,result['html'])
            self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
            import re
            dimensions=re.search(r'data-asset="scene" style="width:([0-9.]+)mm;height:([0-9.]+)mm',result['html'])
            self.assertGreaterEqual(float(dimensions[1]),90)
            self.assertGreaterEqual(float(dimensions[2]),90)

    def test_migration_preserves_text_and_does_not_invent_missing_sources(self):
        """Only supplied overlong text becomes a stimulus; empty labels remain errors."""
        page=authored_page();page['exercise']['captions']=[{'id':'s1','text':SOURCES[0]},{'id':'empty','text':''}]
        page['html']='<p data-content="caption_s1"></p>'
        items=prepare_stimuli(page,page['exercise'])
        self.assertEqual(items,[{'id':'s1','text':SOURCES[0]}])
        self.assertIn('data-content="stimulus_s1"',page['html'])
        self.assertEqual(page['exercise']['captions'],[{'id':'empty','text':''}])

    def test_source_ids_collisions_are_not_silently_overwritten(self):
        """An existing source cannot be replaced by a different migrated caption."""
        page=authored_page();page['exercise'].update(stimuli=[{'id':'s1','text':'Existing source.'}],captions=[{'id':'s1','text':SOURCES[0]}])
        with self.assertRaisesRegex(ValueError,'collide'):prepare_stimuli(page,page['exercise'])

    def test_dense_mixed_sources_request_content_revision_only_after_overflow(self):
        """A layout-only loop cannot solve excessive retained source text."""
        from core.activity_stimuli import source_density_repair
        draft={'exercise':{'stimuli':[{'id':'case','text':' '.join(['information']*160)}]}}
        prompt=density_guidance(dict(load_grade_config()['3rd-4th'],stimulus_limit=4))
        result=source_density_repair(draft,prompt,'Design overflow: expected 1 pages, got 2')
        self.assertIn('complete revised exercise',result)
        self.assertIn('160',result)
        self.assertIn('90',result)
        self.assertIsNone(source_density_repair(draft,prompt,'Visuals are too small'))
        self.assertIsNone(source_density_repair(draft,'Ordinary legacy layout','Design overflow: expected 1 pages, got 2'))

    def test_short_sources_and_unrelated_errors_do_not_unlock_content_changes(self):
        """Ordinary reflow retains its existing source and answer specification."""
        from core.activity_stimuli import source_density_repair
        prompt=density_guidance(dict(load_grade_config()['5th-6th'],stimulus_limit=4))
        draft={'exercise':{'stimuli':[{'id':'case','text':'A short retained source.'}]}}
        self.assertIsNone(source_density_repair(draft,prompt,'Design overflow: expected 1 pages, got 2'))
        self.assertIsNone(source_density_repair(draft,prompt,'Question answer is incorrect'))

    def test_schema_and_density_are_opt_in_only(self):
        """QCM and ordinary exact-puzzle profiles do not receive source blocks or new geometry."""
        base=load_grade_config()['3rd-4th'];mixed=dict(base,stimulus_limit=4)
        brief={'render_mode':'authored','mechanic':'compare'}
        self.assertNotIn('stimuli',exercise_schema(brief,base)['properties'])
        schema=exercise_schema(brief,mixed)
        self.assertEqual(schema['properties']['stimuli']['maxItems'],4)
        self.assertIn('90x90mm',density_guidance(mixed))
        self.assertNotIn('stimuli',density_guidance(base))


if __name__=='__main__':unittest.main()
