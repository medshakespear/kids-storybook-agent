"""Repair planned rendering modes without regenerating curriculum or weakening exact tasks."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,validate_plan,merge_plan_mode_repair
from core.page_contract import validate_brief
from tests.test_plan_mechanics import plan_for


class PlanModeRecoveryTests(unittest.TestCase):
    """Keep the proposed task while normalizing only clear mode intent."""

    def test_missing_mode_recovers_from_supported_tool(self):
        """A declared maze or open craft supplies unambiguous planner mode evidence."""
        raw=plan_for(['maze','drawing','shadow matching','craft'])
        for p in raw['pages']:
            p.pop('render_mode')
        original=deepcopy(raw)
        result=validate_plan(raw,4,require_coherent=True)
        self.assertEqual([p['render_mode'] for p in result['pages']],['exact','authored','exact','authored'])
        self.assertEqual(result['pages'][2]['mechanic_constraints'],{'mode':'shadow'})
        self.assertEqual(raw,original)

    def test_supported_mode_synonyms_normalize(self):
        """Equivalent exact/authored vocabulary does not require another API call."""
        for mode,mechanic,expected in [('SVG','maze','exact'),('deterministic','count','exact'),
                                       ('AI authored','drawing','authored'),('open-ended','craft','authored')]:
            raw=plan_for([mechanic],mode)
            self.assertEqual(validate_plan(raw,1,require_coherent=True)['pages'][0]['render_mode'],expected)

    def test_ambiguous_missing_mode_identifies_page_and_value(self):
        """Do not guess between open creative work and an unsupported closed puzzle."""
        raw=plan_for(['drawing','jigsaw']);raw['pages'][1].pop('render_mode')
        with self.assertRaisesRegex(ValueError,r'Planned page 2 .*received None'):
            validate_plan(raw,2,require_coherent=True)

    def test_mode_only_retry_keeps_all_original_concepts(self):
        """Only the mode correction is accepted from a response that drifts other fields."""
        original=plan_for(['drawing','maze'],'authored')
        original['pages'][1]['render_mode']='unknown'
        correction={'title':'Wrong book','pages':[dict(page_number=2,render_mode='exact',mechanic='sort',
                    title='Unrelated task',activity_concept='Replace the maze') ]}
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in [original,correction]]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json('Create the complete plan.',lambda r:validate_plan(r,2,require_coherent=True),'Creative plan')
        self.assertEqual(result['title'],original['title'])
        self.assertEqual(result['pages'][1]['mechanic'],'maze')
        for key in ['title','learning_goal','activity_concept','layout_brief']:
            self.assertEqual(result['pages'][1][key],original['pages'][1][key])
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertIn('Repair ONLY the render_mode',api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])

    def test_repair_requires_explicit_unambiguous_page_number(self):
        """No plan page is selected by position in an incomplete correction response."""
        original=plan_for(['maze'])
        for correction in [{'pages':[{'render_mode':'exact'}]},
                           {'pages':[{'page_number':True,'render_mode':'exact'}]},
                           {'pages':[{'page_number':1,'render_mode':'exact or authored'}]},
                           {'pages':[{'page_number':1,'render_mode':'exact'}]*2}]:
            with self.subTest(correction=correction),self.assertRaises(ValueError):
                merge_plan_mode_repair(original,correction,1)

    def test_design_stage_still_requires_an_explicit_mode(self):
        """Planner recovery must not guess a mode for a partially generated exercise."""
        with self.assertRaisesRegex(ValueError,'render_mode'):
            validate_brief({'mechanic':'maze'},planning=False)


if __name__=='__main__':
    unittest.main()
