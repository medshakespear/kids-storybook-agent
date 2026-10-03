"""Regression tests for text collision and usable blank work surfaces."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from weasyprint import HTML
from core.creative_layout import check_document, document_markup
from core.blank_templates import draw_blank_template, template_kind
from core.activity_presentation import prepare_activity_presentation


class PrintCollisionTests(unittest.TestCase):
    """Check actual rendered geometry, not just page count and outer boundaries."""
    def test_internal_overlap_is_rejected(self):
        """A heading can collide with text while everything remains on one page."""
        body = '<div style="height:5mm"><p>Native American Heritage Month</p></div><p>A passage about nature.</p>'
        doc = HTML(string=document_markup([body], 14)).render()
        with self.assertRaisesRegex(ValueError, 'Design overlap'):
            check_document(doc, 1)

    def test_normal_vertical_flow_is_accepted(self):
        """Ordinary paragraphs must not trigger false collision reports."""
        doc = HTML(string=document_markup(['<h1>Nature Journal</h1><p>Read the passage.</p><p>Write your ideas.</p>'],14)).render()
        check_document(doc, 1)

    def test_blanket_surface_is_actually_blank(self):
        """Student design space contains no pre-filled pattern or colors."""
        with tempfile.TemporaryDirectory() as folder:
            path = draw_blank_template('blanket', folder, 'blanket')
            with Image.open(path) as image:
                self.assertEqual(image.crop((150,110,1650,890)).getextrema(), ((255,255),)*3)
                self.assertEqual(image.size, (1800,1000))

    def test_template_detection_does_not_change_decorative_art(self):
        """Only an explicitly blank work surface can bypass image generation."""
        self.assertIsNone(template_kind({'directions': 'Look at a colorful blanket.'}))
        self.assertEqual(template_kind({'directions': 'Design the blank woven blanket template.'}), 'blanket')

    def test_authored_flow_keeps_questions_and_prints_starter(self):
        """Fix narrow columns and missing sentence stems while preserving the task."""
        exercise = {'render_mode':'authored', 'mechanic':'gratitude', 'goal':'Write a nature gratitude note.',
            'directions':'Read, then write two sentences.', 'passage':'Plants need water and soil.', 'captions':[],
            'questions':[{'id':'1','prompt':'Complete the first sentence to name something in nature.',
                'answer':"Accept sentences starting with 'I am thankful for...' naming nature.", 'space_mm':20},
                {'id':'2','prompt':'Complete the second sentence to explain why nature matters.',
                 'answer':'Accept a relevant explanation.', 'space_mm':20}]}
        page={'html':'<div style="height:5mm">unsafe columns</div>',
              'images':[{'id':'nature','prompt':'A nature scene.'}], 'exercise':exercise}
        result, _ = prepare_activity_presentation(page, {}, {'student_font_pt':14})
        self.assertIn('Start with: I am thankful for...', result['exercise']['questions'][0]['prompt'])
        self.assertIn('Write a sentence', result['exercise']['questions'][1]['prompt'])
        self.assertNotIn('height:5mm', result['html'])
        self.assertIn('data-content="passage"', result['html'])
        self.assertEqual(result['exercise']['questions'][1]['space_mm'], 20)

    def test_blank_template_is_routed_to_local_generation(self):
        """The blank work surface should not rely on Cloudflare complying with a prompt."""
        page={'images':[{'id':'blanket','prompt':'A patterned blanket.'}], 'exercise':{
            'render_mode':'authored','directions':'Color the blank blanket template.',
            'questions':[{'id':'1','prompt':'Create your own pattern.', 'space_mm':20}]}}
        result, _ = prepare_activity_presentation(page, {}, {})
        self.assertEqual(result['images'][0]['local_template'], 'blanket')


class LocalTemplateGenerationTests(unittest.TestCase):
    """Exercise the same asset pipeline used by cron and webhook generation."""
    def test_blank_template_needs_no_image_api_request(self):
        """The delivered work surface is a decoded local PNG, not an AI interpretation."""
        from unittest.mock import patch
        from core.creative_generator import generate_creative_images
        pack={'cover':{'images':[]}, 'pages':[{'images':[{'id':'blanket',
            'prompt':'Blank blanket.', 'local_template':'blanket'}]}], 'art_direction':'Blue and orange'}
        with tempfile.TemporaryDirectory() as folder, patch('core.creative_generator.generate_images') as provider:
            generate_creative_images(pack, {}, folder)
            provider.assert_not_called()
            self.assertTrue(Path(pack['pages'][0]['images'][0]['path']).exists())
            self.assertEqual(pack['image_validation']['checked'], 1)
            self.assertEqual(pack['image_review']['status'], 'disabled')
