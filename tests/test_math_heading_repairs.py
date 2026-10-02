"""Math field repair must not introduce unbound titles or invalid name containers."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class MathHeadingRepairTests(unittest.TestCase):
    """Preserve student questions while fixing calculations and ordinary page metadata."""

    def validate(self,page):
        """Run upper-grade shared specification and real print validation."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
                               expected_title='Innovation Studio',require_coherent=True)

    def math_page(self):
        """Supply one wrong declared result with otherwise coherent original task data."""
        page=authored_page()
        page['exercise']['questions']=[dict(id='2',prompt='A class has 12 pencils and receives 8 more. How many pencils are there?',answer='21 pencils, with 12 initially and 8 new.',space_mm=25,
                                          calculation={'expression':'12+8','answer':21})]
        page['html']=page['html'].replace('question_1','question_2')
        return page

    def test_math_retry_preserves_layout_art_and_printed_question(self):
        """Only the identified calculation and answer fields survive from a drifting response."""
        bad=self.math_page();good=deepcopy(bad)
        good['exercise']['questions'][0].update(answer='20',calculation={'expression':'12+8','answer':20},
                                             prompt='An unrelated task',space_mm=0)
        good['html']='<p>Legacies in Innovation and Art</p>';good['images']=None
        api=Mock()
        def response(page):
            """Produce a complete mock provider response."""
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        api.chat.completions.create.side_effect=[response(bad),response(good)]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 1')
        question=result['exercise']['questions'][0]
        self.assertEqual(question['prompt'],bad['exercise']['questions'][0]['prompt'])
        self.assertEqual(question['space_mm'],25)
        self.assertEqual(question['answer'],'20')
        self.assertEqual(question['calculation']['answer'],20)
        self.assertEqual(result['source_layout'],bad['html'])
        self.assertEqual(result['images'],bad['images'])
        self.assertIn('Correct ONLY the calculation and answer fields',
                      api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])
        self.assertIn('evaluates to 20, not 21',
                      api.chat.completions.create.call_args.kwargs['messages'][-1]['content'])
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_single_unbound_primary_heading_uses_planned_activity_title(self):
        """A pack headline drafted in the activity's h1 cannot override the planned title."""
        page=authored_page();page['html']=page['html'].replace('data-content="title"','').replace('></h1>',
                    '>Legacies in Innovation and Art: Hispanic Heritage Month Studio Journal</h1>')
        result=self.validate(page)
        self.assertIn('Innovation Studio',result['html'])
        self.assertNotIn('Legacies in Innovation',result['html'])
        self.assertEqual(result['exercise'],page['exercise'])

    def test_additional_heading_is_not_silently_removed_as_title(self):
        """An independently supplied contextual h1 requires a canonical caption when title is bound."""
        page=authored_page();page['html']+='<h1>Another unbound instruction heading</h1>'
        with self.assertRaisesRegex(ValueError,'unbound wording'): self.validate(page)

    def test_name_labels_and_supported_text_slots_render_normally(self):
        """Static labels, emphatic text and small-heading tags can contain canonical text."""
        for container in ['label','strong','em','b','h5','h6']:
            with self.subTest(container=container):
                page=authored_page();page['html']+=f'<{container}>Name:</{container}>'
                result=self.validate(page)
                self.assertIn('Name: ____________________',result['html'])
                page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
                                  f'<{container} data-content="directions"></{container}>')
                self.assertIn(page['exercise']['directions'],self.validate(page)['html'])

    def test_graphics_are_still_invalid_text_slot_containers(self):
        """Accepting ordinary text tags does not swallow an image or table as task text."""
        for container in ['img','table','tr']:
            with self.subTest(container=container),self.assertRaisesRegex(ValueError,'text container'):
                page=authored_page();page['html']=page['html'].replace('<p data-content="directions"></p>',
                        f'<{container} data-content="directions"></{container}>' if container!='img' else '<img data-content="directions"/>')
                self.validate(page)
