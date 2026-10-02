"""Bind harmless worksheet metadata without authorizing independent exercise wording."""
from copy import deepcopy
import unittest

from core.creative_generator import validate_design
from core.layout_recovery import single_illustration_recovery
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class StandardLabelBindingTests(unittest.TestCase):
    """Regress Zone ID and Date retries using real upper-grade print validation."""

    def validate(self,page):
        """Compile and measure one authored student page."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_zone_header_and_blank_date_bind_locally(self):
        """Keep the exact contextual label, original question and artwork."""
        page = authored_page()
        page['html'] += '<table><tr><th>Zone ID</th></tr></table><p>Date: _________________</p>'
        original = deepcopy(page)
        result = self.validate(page)
        self.assertIn({'id':'zone_label_1','text':'Zone ID'},result['exercise']['captions'])
        self.assertIn('Date: ____________________',result['html'])
        self.assertIn('Zone ID',result['html'])
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(page,original)

    def test_formatted_blank_date_binds_whole_container(self):
        """Formatting inside the standard field cannot trigger nested inferred-slot errors."""
        page = authored_page()
        page['html'] += '<p><strong>Date:</strong> _________________</p>'
        self.assertIn('Date: ____________________',self.validate(page)['html'])

    def test_date_slot_is_optional_and_explicit_slot_works(self):
        """Existing pages need no date field; explicitly authored date slots are supported."""
        self.validate(authored_page())
        page = authored_page(); page['html'] += '<p data-content="date"></p>'
        self.assertIn('Date: ____________________',self.validate(page)['html'])

    def test_independent_task_wording_is_still_rejected(self):
        """Known headings cannot hide extra questions or numerical answer drafts."""
        for markup in ['<p>Date: _________________ Draw three flowers.</p>',
                       '<th>Zone ID: Circle zone 3.</th>',
                       '<p><strong>Zone ID</strong> Answer: 12.</p>']:
            page = authored_page(); page['html'] += markup
            with self.subTest(markup=markup),self.assertRaisesRegex(ValueError,'unbound wording'):
                self.validate(page)

    def test_local_recomposition_retains_bound_metadata(self):
        """The printable recovery must preserve the contextual label and date field."""
        page = authored_page(); page['html'] += '<p>Zone ID</p><p>Date: __________</p>'
        recovered = single_illustration_recovery(page,11,6000)
        self.assertIsNotNone(recovered)
        # The recovery compiler registered the caption; retain it in the source
        # specification rather than requiring the provider to recreate the label.
        result = self.validate(recovered)
        self.assertIn('Date: ____________________',result['html'])
        self.assertIn('Zone ID',result['html'])


if __name__ == '__main__':
    unittest.main()
