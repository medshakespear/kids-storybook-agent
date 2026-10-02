"""Prevent and isolate planner options that belong to a different exact puzzle tool."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, validate_plan, merge_plan_constraints_repair
from core.response_schemas import plan_schema, mechanic_constraints_schema
from tests.test_plan_mechanics import plan_for


class PlanConstraintsRecoveryTests(unittest.TestCase):
    """Retain all planned curriculum while fixing only the invalid option object."""

    def test_schema_options_are_conditioned_on_the_tool(self):
        """Matching cannot receive sorting attributes; other tools cannot receive either."""
        branches=plan_schema(8)['properties']['pages']['items']['anyOf']
        for branch in branches:
            props=branch['properties']
            kinds=props['mechanic'].get('enum',[])
            if kinds==['matching']:
                self.assertEqual(set(props['mechanic_constraints']['properties']),{'mode'})
            elif kinds==['sort']:
                self.assertEqual(set(props['mechanic_constraints']['properties']),{'attribute'})
            else:
                self.assertNotIn('mechanic_constraints',props)
            self.assertFalse(branch['additionalProperties'])

    def test_two_reported_pages_repair_without_regenerating_the_plan(self):
        """An invalid option on page 1 then page 6 receives separate bounded corrections."""
        raw=plan_for(['matching','maze','count','pattern','balance','sort'])
        raw['pages'][0].update(title='Ghostly Greetings',mechanic_constraints={'attribute':'shape'})
        raw['pages'][5].update(title='Potion Ingredient Hunt',mechanic_constraints={'mode':'shadow'})
        original=deepcopy(raw)
        corrections=[{'pages':[{'page_number':1,'mechanic_constraints':{'mode':'shadow'},'mechanic':'maze','title':'Wrong'}]},
                     {'pages':[{'page_number':6,'mechanic_constraints':{'attribute':'color'}}]}]
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(value)),finish_reason='stop')]) for value in [raw,*corrections]]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json('Create an original Halloween plan.',lambda r:validate_plan(r,6,require_coherent=True),
                            'Creative plan',response_schema=plan_schema(6))
        self.assertEqual(raw,original)
        self.assertEqual(result['pages'][0]['mechanic_constraints'],{'mode':'shadow'})
        self.assertEqual(result['pages'][5]['mechanic_constraints'],{'attribute':'color'})
        for old,new in zip(original['pages'],result['pages']):
            for key in ['title','learning_goal','activity_concept','layout_brief','render_mode','mechanic']:
                self.assertEqual(old[key],new[key])
        self.assertEqual(api.chat.completions.create.call_count,3)
        for call in api.chat.completions.create.call_args_list[1:]:
            message=call.kwargs['messages'][-1]['content']
            self.assertIn('Repair ONLY mechanic_constraints',message)
            schema=call.kwargs['response_format']['json_schema']['schema']
            self.assertEqual(set(schema['properties']['pages']['items']['properties']),{'page_number','mechanic_constraints'})

    def test_nonconfigurable_tools_accept_only_empty_constraints(self):
        """Removing an unrelated metadata option must not substitute a different puzzle."""
        original=plan_for(['maze']);original['pages'][0]['mechanic_constraints']={'attribute':'color'}
        repaired=merge_plan_constraints_repair(original,{'pages':[{'page_number':1,'mechanic_constraints':{}}]},1)
        self.assertEqual(repaired['pages'][0]['mechanic'],'maze')
        self.assertEqual(repaired['pages'][0]['mechanic_constraints'],{})
        with self.assertRaisesRegex(ValueError,'supported rules'):
            merge_plan_constraints_repair(original,{'pages':[{'page_number':1,'mechanic_constraints':{'mode':'shadow'}}]},1)

    def test_repair_cannot_reverse_an_alias_rule(self):
        """A shadow matching brief cannot silently become identical matching."""
        original=plan_for(['shadow matching'])
        self.assertEqual(mechanic_constraints_schema('shadow matching')['properties']['mode']['enum'],['shadow'])
        with self.assertRaisesRegex(ValueError,'contradicts'):
            merge_plan_constraints_repair(original,{'pages':[{'page_number':1,'mechanic_constraints':{'mode':'identical'}}]},1)

    def test_repair_requires_one_explicit_page_and_object(self):
        """Null, missing, duplicated and boolean page identifiers cannot select an activity."""
        original=plan_for(['matching'])
        for pages in [[{'page_number':True,'mechanic_constraints':{}}],
                      [{'page_number':1,'mechanic_constraints':None}],
                      [{'page_number':1}],
                      [{'page_number':1,'mechanic_constraints':{}}]*2]:
            with self.subTest(pages=pages),self.assertRaises(ValueError):
                merge_plan_constraints_repair(original,{'pages':pages},1)


if __name__=='__main__':
    unittest.main()
