"""Bind complete diagram identifiers while preserving strict task and answer ownership."""
from copy import deepcopy
import unittest

from core.content_binding import diagram_label
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class DiagramLabelBindingTests(unittest.TestCase):
    """Regress the Node A upper-grade failure and related standalone markers."""

    def validate(self,page):
        """Compile tasks and verify the real upper-grade print layout."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_node_labels_bind_without_provider_repair(self):
        """Preserve diagram markers and their formatting along with original tasks and art."""
        page=authored_page()
        page['html']+='<table><tr><td>Node A</td><td><strong>Node B</strong></td><td>Node C</td></tr></table>'
        original=deepcopy(page)
        result=self.validate(page)
        labels=result['exercise']['captions']
        self.assertEqual([c['text'] for c in labels],['Node A','Node B','Node C'])
        for c in labels:
            self.assertEqual(result['html'].count(c['text']),1)
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        self.assertEqual(page,original)

    def test_complete_related_identifiers_are_supported(self):
        """Allow a bounded family of markers, not arbitrary independent labels."""
        for text in ['Point 1','Station B','Zone 2:','Vertex C','Node A1','Node 30']:
            page=authored_page();page['html']+='<p>'+text+'</p>'
            with self.subTest(text=text):
                self.assertTrue(diagram_label(text))
                self.assertIn(text,self.validate(page)['html'])

    def test_marker_with_answer_or_instruction_remains_invalid(self):
        """A recognized prefix cannot hide a new action or a result."""
        for text in ['Node A: 12','Node A equals 12','Node A: Write your answer',
                     'Point 1 connects to Point 2','Node 31','Node AA','Step 1']:
            page=authored_page();page['html']+='<p>'+text+'</p>'
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'unbound wording'):
                self.validate(page)

    def test_repeated_marker_requires_explicit_semantic_layout_repair(self):
        """Do not silently remove a diagram marker that might identify a second location."""
        page=authored_page();page['html']+='<p>Node A</p><p>Node A</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page)

    def test_caption_limit_is_preserved(self):
        """Marker recovery cannot add unbounded printed text to a packed page."""
        page=authored_page()
        page['exercise']['captions']=[{'id':f'label_{i}','text':f'Context {i}'} for i in range(6)]
        page['html']+=''.join(f'<p data-content="caption_label_{i}"></p>' for i in range(6))
        page['html']+='<p>Node A</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page)


if __name__=='__main__':
    unittest.main()
