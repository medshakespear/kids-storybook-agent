"""Print decoration and caption recovery must not replace tasks or reduce useful artwork."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design,merge_layout_repair
from core.creative_layout import clean_style
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class CaptionLayoutRecoveryTests(unittest.TestCase):
    """Regress the shadow -> tiny art -> unbound heading -> unknown caption chain."""

    def validate(self,page):
        """Compile and measure a first/second-grade worksheet."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Detectives',require_coherent=True)

    def labelled_page(self):
        """Add an original complete context heading outside canonical content."""
        page=authored_page()
        page['html']=page['html'].replace('<p data-content="directions">',
                         '<h2 style="font-size:14pt">Gather, Add, and Grow!</h2><p data-content="directions">')
        return page

    def bound_correction(self):
        """Return a layout with a real caption and sufficient main art."""
        page=self.labelled_page()
        page['html']=page['html'].replace('>Gather, Add, and Grow!</h2>',
                                       ' data-content="caption_banner"></h2>')
        page['exercise']['captions']=[{'id':'banner','text':'Gather, Add, and Grow!'}]
        return page

    def ask(self,responses):
        """Run production retries with mocked text responses and real print checks."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in responses]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 2')
        return result,api

    def test_decorative_shadows_are_dropped_without_redesign(self):
        """Unsupported visual effects have no role in printable task content."""
        self.assertEqual(clean_style('color:teal;box-shadow:2mm 2mm 3mm gray;text-shadow:1px 1px gray'),'color:teal')
        with self.assertRaisesRegex(ValueError,'resource'):
            clean_style('box-shadow:url(https://example.com/a)')

    def test_binding_repair_accepts_existing_heading_but_pins_tasks_and_images(self):
        """Caption binding can succeed without adopting drifting exercise fields."""
        original=self.labelled_page();correction=self.bound_correction()
        correction['images']=None
        correction['exercise']['questions'][0].update(prompt='An unrelated task',answer='Wrong',space_mm=0)
        result,api=self.ask([original,correction])
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        self.assertEqual(result['images'],original['images'])
        self.assertIn('Gather, Add, and Grow!',result['html'])
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_small_art_then_caption_recovery_preserves_both_repairs(self):
        """Fix meaningful image size, then a raw heading, without losing canonical captions."""
        original=authored_page();original['html']=original['html'].replace('width:175mm;height:75mm','width:28mm;height:24mm')
        enlarged=self.labelled_page()
        corrected=self.bound_correction();corrected['images']=None
        # Exercise the author-directed path independently of the new local rescue.
        with patch('core.layout_recovery.single_illustration_recovery',return_value=None):
            result,api=self.ask([original,enlarged,corrected])
        self.assertEqual(api.chat.completions.create.call_count,3)
        self.assertEqual(result['images'],original['images'])
        self.assertIn('width:175mm;height:75mm',result['html'])
        self.assertEqual(result['exercise']['captions'],[{'id':'banner','text':'Gather, Add, and Grow!'}])

    def test_caption_alias_is_rebound_by_identical_text(self):
        """A renamed caption references the retained caption; no new label is invented."""
        original=self.bound_correction();correction=deepcopy(original)
        correction['exercise']['captions']=[{'id':'context','text':'Gather, Add, and Grow!'}]
        correction['html']=correction['html'].replace('caption_banner','caption_context')
        result=self.validate(merge_layout_repair(original,correction))
        self.assertEqual(result['exercise']['captions'],original['exercise']['captions'])
        self.assertIn('data-content="caption_banner"',result['source_layout'])

    def test_missing_caption_with_explicit_original_text_can_be_bound(self):
        """An undeclared prefilled caption retains its complete existing wording."""
        original=self.labelled_page();original['html']=original['html'].replace('>Gather, Add, and Grow!',
                                                          ' data-content="caption_banner">Gather, Add, and Grow!')
        result,api=self.ask([original,self.bound_correction()])
        self.assertIn('Gather, Add, and Grow!',result['html'])
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_new_or_changed_caption_text_is_not_silently_accepted(self):
        """A layout-only retry cannot invent new wording or overwrite existing captions."""
        for original in [self.labelled_page(),self.bound_correction()]:
            correction=self.bound_correction();correction['exercise']['captions'][0]['text']='Count exactly seven plants.'
            with self.assertRaises(ValueError):
                merge_layout_repair(original,correction)

    def test_identical_empty_caption_duplicates_print_once(self):
        """Redundant empty caption slots can be removed without losing tasks or artwork."""
        page=self.bound_correction();page['html']+='<p data-content="caption_banner"></p>'
        result=self.validate(page)
        self.assertEqual(result['html'].count('Gather, Add, and Grow!'),1)
        self.assertEqual(result['images'],page['images'])

    def test_unknown_empty_caption_and_duplicate_question_remain_invalid(self):
        """Do not guess an undeclared empty label or discard a real exercise task."""
        page=authored_page();page['html']+='<p data-content="caption_context"></p>'
        with self.assertRaisesRegex(ValueError,'available slots'):
            self.validate(page)
        page=authored_page();page['html']+='<p data-content="question_1"></p>'
        with self.assertRaisesRegex(ValueError,'already printed'):
            self.validate(page)


if __name__=='__main__':
    unittest.main()
