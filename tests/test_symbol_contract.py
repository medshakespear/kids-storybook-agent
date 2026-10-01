"""Friendly exact symbols accept cosmetic variants while preserving puzzle meaning."""
import copy
import unittest
import xml.etree.ElementTree as ET

from core.task_visuals import symbol, build_visual, icon, COLORS, SHAPES
from tests.test_exercise_quality import visual_fixtures


class SymbolContractTests(unittest.TestCase):
    """Exercise graphics and their keys share the same canonical symbols."""

    def test_cosmetic_symbol_variants_are_normalized_without_guessing(self):
        """Capitalization, plurals, British spelling and exact palette hex are unambiguous."""
        self.assertEqual(symbol(dict(shape=' Pumpkins ',colour=' Orange ',size=' LARGE ')),
                         dict(shape='pumpkin',color='orange',size='large'))
        self.assertEqual(symbol(dict(shape='Leaves',color='#ed8936')),dict(shape='leaf',color='orange',size='large'))
        self.assertEqual(symbol(dict(shape='Ghosts',color='Grey')),dict(shape='ghost',color='gray',size='large'))
        for raw in [dict(shape='witch',color='orange'),dict(shape='ghost',color='rainbow'),
                    dict(shape=['ghost'],color='white'),dict(shape='bat',color={}),dict(shape='star')]:
            with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,'supported shape and color'):
                symbol(raw)

    def test_halloween_vectors_and_sort_answers_use_supported_symbols(self):
        """Real bat/ghost vector paths work with exact grouping and white/black palettes."""
        spec=dict(id='halloween',question=1,kind='sort',attribute='shape',items=[
            dict(shape='Ghosts',color='White'),dict(shape='Bats',color='Black'),
            dict(shape='ghost',color='pink'),dict(shape='bat',color='brown')])
        svg,key=build_visual(spec)
        ET.fromstring(svg)
        self.assertIn('Ghost: 1, 3',key)
        self.assertIn('Bat: 2, 4',key)
        self.assertIn(COLORS['white'],svg)
        self.assertNotEqual(icon(symbol(dict(shape='ghost',color='white')),0,0),
                            icon(symbol(dict(shape='bat',color='white')),0,0))
        for shape in SHAPES:
            ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg">'+icon(symbol(dict(shape=shape,color='teal')),0,0)+'</svg>')

    def test_symbol_error_identifies_item_and_permitted_choices(self):
        """A repair can address the precise defective symbol rather than redesigning a page."""
        spec=copy.deepcopy(visual_fixtures()[0])
        spec['items'][2]['shape']='witch'
        with self.assertRaisesRegex(ValueError,'Visual sorting, item 3') as failure:
            build_visual(spec)
        self.assertIn("shape='witch'",str(failure.exception))
        self.assertIn('Shapes:',str(failure.exception))
        self.assertIn('Colors:',str(failure.exception))
