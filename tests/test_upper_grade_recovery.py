"""Regress long teacher criteria and tiny printable-bound spills."""
import unittest
from types import SimpleNamespace
from core.answer_limits import answer_character_limit
from core.response_schemas import design_schema, field_repair_schema
from core.small_overflow import recover_small_overflow


class UpperGradeRecoveryTests(unittest.TestCase):
    """Keep solution criteria and student workspace intact during recovery."""
    def test_teacher_answer_limits_are_grade_aware_and_match_schema(self):
        """A multi-part upper-grade criterion has room without lengthening student prompts."""
        brief={'render_mode':'authored','mechanic':'reasoning'}
        for font,limit in [(15,180),(14,180),(12,400),(11,400)]:
            config={'student_font_pt':font}
            self.assertEqual(answer_character_limit(config),limit)
            schema=design_schema(brief,config)
            answer=schema['properties']['exercise']['properties']['questions']['items']['properties']['answer']
            self.assertIn(f'at most {limit} characters',answer['description'])
        repair=field_repair_schema('3','answer',answer_limit=400)
        self.assertIn('400', repair['properties']['exercise']['properties']['questions']['items']['properties']['answer']['description'])

    def test_long_upper_grade_criterion_is_retained_in_shared_key(self):
        """The parser accepts all parts of a bounded teacher criterion without truncation."""
        from core.creative_generator import validate_design
        from tests.coherent_fixtures import authored_page
        page = authored_page()
        answer = ('Accept a tool design that identifies a practical purpose, explains how the parts work together, '
                  'describes safe materials, and justifies one design choice. The explanation should connect the '
                  'design to the stated need and include one reasonable improvement.')
        self.assertGreater(len(answer), 180)
        page['exercise']['questions'][0]['answer'] = answer
        result = validate_design(page, 11, quality={'student_font_pt':11,'minimum_text_pt':11,
            'items_per_page':4,'visual_area_mm2':6000}, expected_title='Design a Useful Tool', require_coherent=True)
        self.assertEqual(result['exercise']['questions'][0]['answer'], answer)
        self.assertIn(answer, result['answers'])

    def document(self, spill=1.2):
        """Represent the measured leaf geometry from the reported 1.2mm spill."""
        class Box:
            element_tag='span'
            def border_box_x(self):
                """Return a printable left boundary."""
                return 12*96/25.4
            def border_width(self):
                """Return a printable response width."""
                return 175*96/25.4
            def border_box_y(self):
                """Return the lower response area's start."""
                return 200*96/25.4
            def border_height(self):
                """Return the height that produces the measured overflow."""
                return (83+spill)*96/25.4
        root=SimpleNamespace(descendants=lambda:[Box()])
        return SimpleNamespace(pages=[SimpleNamespace(_page_box=root)])

    def test_small_spill_resizes_only_artwork(self):
        """All question wording, fonts and response heights remain byte-for-byte intact."""
        markup='<img data-asset="scene" style="width:175mm;height:80mm"/><p style="font-size:11pt">Explain your choice.</p><span style="height:60mm"></span>'
        candidate=recover_small_overflow(markup,self.document(),{'visual_area_mm2':6000})
        self.assertIsNotNone(candidate)
        self.assertIn('height:76.80mm',candidate)
        self.assertEqual(candidate.replace('height:76.80mm','height:80mm'),markup)

    def test_visual_floor_and_exact_labels_are_preserved(self):
        """Do not rescue a page by making art inadequate or shrinking exact puzzle labels."""
        for markup,area in [('<img data-asset="scene" style="width:175mm;height:35mm"/>',6000),
                            ('<img data-visual="puzzle" style="width:175mm;height:80mm"/>',6000),
                            ('<img data-asset="scene" style="width:175mm;height:60mm"/>',10500)]:
            self.assertIsNone(recover_small_overflow(markup,self.document(),{'visual_area_mm2':area}))
        self.assertIsNone(recover_small_overflow('<img data-asset="scene" style="width:175mm;height:80mm"/>',
                                                self.document(20),{'visual_area_mm2':6000}))
