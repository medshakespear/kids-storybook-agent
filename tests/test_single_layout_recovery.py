"""Single-illustration recovery preserves verified content and cannot mask true defects."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.layout_recovery import single_illustration_recovery
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class SingleLayoutRecoveryTests(unittest.TestCase):
    """Use real print geometry and shared content validation for recovery candidates."""

    def validate(self,page):
        """Measure a first/second-grade student worksheet."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_recomposition_fits_large_square_art_and_keeps_task_and_workspace(self):
        """Recover source layout with extreme panel height without changing the activity."""
        original=authored_page();original['html']='<div style="height:300mm">'+original['html']+'</div>'
        snapshot=deepcopy(original)
        rescue=single_illustration_recovery(original,13,10000)
        result=self.validate(rescue)
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['images'],original['images'])
        self.assertIn('width:102mm;height:102mm',result['html'])
        self.assertIn('height:45mm',result['html'])
        self.assertEqual(original,snapshot)

    def test_malformed_layout_retry_can_recover_original_page_locally(self):
        """JSON failure during layout repair must not force another complete rewrite."""
        original=authored_page();original['html']=original['html'].replace('height:75mm','height:300mm')
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=s),finish_reason='stop')]) for s in [json.dumps(original),'{"html":"broken" "x":1}']]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 4')
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(api.chat.completions.create.call_count,2)
        message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('Return JSON containing html only',message)

    def test_unbound_content_cannot_be_discarded_by_recovery(self):
        """An extra instruction or undeclared caption must be resolved explicitly."""
        for extra in ['<p>Draw three more flowers.</p>','<p data-content="caption_unknown"></p>']:
            page=authored_page();page['html']+=extra
            self.assertIsNone(single_illustration_recovery(page,13,10000))

    def test_invalid_math_cannot_be_hidden_by_recomposition(self):
        """Math verification remains mandatory before a rescue layout is produced."""
        page=authored_page();page['exercise']['questions'][0].update(prompt='Calculate 4 + 3',answer='8',
                                          calculation={'expression':'4+3','answer':8})
        self.assertIsNone(single_illustration_recovery(page,13,10000))

    def test_multiple_images_are_not_forced_into_a_generic_layout(self):
        """Complex scene relationships stay with the author-directed repair path."""
        page=authored_page();page['images'].append({'id':'another','prompt':'Another purposeful original subject.'})
        self.assertIsNone(single_illustration_recovery(page,13,10000))

    def test_untracked_blank_working_panels_are_not_dropped(self):
        """Preserve any workspace whose purpose is absent from canonical space_mm."""
        page=authored_page();page['html']+='<div style="height:80mm;border:1mm solid teal"></div>'
        self.assertIsNone(single_illustration_recovery(page,13,10000))


if __name__=='__main__':
    unittest.main()
