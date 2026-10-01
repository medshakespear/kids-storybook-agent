"""Regressions drawn from the broken Pumpkin Patch PDF, without paid API calls."""
import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

from weasyprint import HTML
from core.creative_generator import validate_design
from core.creative_layout import fragment, document_markup, data_only_fetcher, check_document
from core.exercise_quality import calculate, validate_exercises, validate_audit, proofread_pack
from core.pipeline import load_grade_config
from core.task_visuals import build_visual, maze_data, page_visuals, answer_text
from tests.test_creative_design import design_fixture


def visual_fixtures():
    """Provide exact puzzles resembling the failed task types in the user's example."""
    items = [dict(shape='pumpkin', color='orange' if i%2 else 'teal', size='large') for i in range(8)]
    return [dict(id='sorting',kind='sort',question=1,attribute='color',items=items),
            dict(id='differences',kind='differences',question=1,items=items[:6],changes=[
                dict(index=1,field='color',value='red'),dict(index=3,field='size',value='small'),
                dict(index=5,field='shape',value='leaf')]),
            dict(id='maze',kind='maze',question=1,rows=6,cols=7,seed=12,tokens=3)]


def exact_page(spec):
    """Use an original freeform layout around one exact graphic with ample work space."""
    title = {'maze':'Pumpkin Trail', 'differences':'Leaf Detectives', 'sort':'Harvest Sort'}[spec['kind']]
    return dict(title=title, page_number=1, images=[], visuals=[spec], calculations=[], answers='',
                html=f'<h1 style="font-size:25pt;color:#157F82">{title}</h1>'
                '<p style="font-size:14pt">Name: ____________________</p>'
                f'<img data-visual="{spec["id"]}" style="width:175mm;height:150mm"/>'
                '<div style="border:0.5mm solid #157F82;border-radius:5mm;height:40mm;padding:4mm">'
                '<p style="font-size:14pt">Try your task here. You can draw or write.</p></div>')


class ExactVisualTests(unittest.TestCase):
    """Require functional, measurable graphics and answers linked to their source data."""

    def test_all_components_render_without_cloudflare(self):
        """Each component is valid XML, prints on one A4 page, and has a computed key."""
        for spec in visual_fixtures():
            with self.subTest(kind=spec['kind']):
                svg, key = build_visual(spec)
                ET.fromstring(svg)
                page = exact_page(spec)
                validated = validate_design(page,14,quality=load_grade_config()['1st-2nd'],expected_title=page['title'])
                self.assertIn('data:image/svg+xml;base64',fragment(validated))
                doc = HTML(string=document_markup([fragment(validated)],14),url_fetcher=data_only_fetcher).render()
                check_document(doc,1)
                self.assertEqual(answer_text(page),key)

    def test_maze_has_unique_solution_and_exact_stars(self):
        """A connected tree of cells has exactly one route; the printed star count matches."""
        spec = visual_fixtures()[2]
        passages, path = maze_data(spec['rows'],spec['cols'],spec['seed'])
        self.assertEqual(len(passages),spec['rows']*spec['cols']-1)
        reachable, queue = {(0,0)}, [(0,0)]
        while queue:
            cell = queue.pop()
            for edge in passages:
                if cell in edge:
                    nxt = next(iter(edge-{cell}))
                    if nxt not in reachable:
                        reachable.add(nxt);queue.append(nxt)
        self.assertEqual(len(reachable),42)
        self.assertEqual(path[0],(0,0));self.assertEqual(path[-1],(5,6))
        self.assertTrue(all(frozenset((a,b)) in passages for a,b in zip(path,path[1:])))
        svg,key = build_visual(spec)
        self.assertEqual(svg.count('fill="#F2C94C"'),3)
        self.assertIn('3 stars',key)

    def test_differences_not_empty_or_invented(self):
        """Both rows are drawn, with distinct and genuinely changed positions only."""
        spec = visual_fixtures()[1]
        svg,key = build_visual(spec)
        self.assertIn('1, 3, 5',key)
        self.assertIn('Compare rows A and B',svg)
        for changes in [[dict(index=1,field='color',value='teal')],
                        [dict(index=1,field='color',value='red')]*2]:
            with self.assertRaises(ValueError):
                build_visual(dict(spec,changes=changes))

    def test_sort_covers_every_item_once(self):
        """Grouping from the visible trait cannot leave unclassified gourds."""
        svg,key = build_visual(visual_fixtures()[0])
        self.assertIn('Teal: 1, 3, 5, 7',key)
        self.assertIn('Orange: 2, 4, 6, 8',key)
        self.assertIn('Sort the pictures by color',svg)
        with self.assertRaises(ValueError):
            build_visual(dict(visual_fixtures()[0],attribute='tall-and-curly'))

    def test_broken_sample_patterns_are_rejected(self):
        """The empty differences and fake scenic maze cannot pass as usable exercises."""
        for text in ['Find the 5 differences in these two rows.', 'Trace the maze and collect 3 stars.']:
            page = dict(design_fixture(),html='<p>'+text+'</p>')
            with self.assertRaises(ValueError):
                validate_exercises(page,load_grade_config()['1st-2nd'])

    def test_new_designs_never_substitute_art(self):
        """Missing prompts and mismatched IDs must be repaired rather than guessed."""
        cfg = load_grade_config()['1st-2nd']
        for mutate in ['missing','blank','excess']:
            page = design_fixture()
            if mutate == 'missing':
                page['html'] = page['html'].replace('data-asset="scene"','data-asset="wrong"')
            elif mutate == 'blank':
                page['images'][0]['prompt'] = ''
            else:
                page['images'] = [dict(id=f'asset{i}',prompt='A different required object.') for i in range(5)]
            with self.subTest(case=mutate), self.assertRaises(ValueError):
                validate_design(page,14,quality=cfg)

    def test_tiny_decorative_thumbnail_fails_quality_floor(self):
        """A mascot thumbnail cannot satisfy the younger-grade visual area requirement."""
        page = design_fixture()
        page['html'] = '<h1>Test</h1><img data-asset="scene" style="width:30mm;height:30mm"/>'
        with self.assertRaisesRegex(ValueError,'Visuals are too small'):
            validate_design(page,14,quality=load_grade_config()['1st-2nd'])

    def test_safe_arithmetic_and_grade_bounds(self):
        """Wrong answers, code injection, division by zero and advanced results fail."""
        self.assertEqual(calculate('45 + 23'),68)
        self.assertEqual(calculate('90 - (50 + 25)'),15)
        for expression in ['__import__("os")','2**99','1/0','a+3']:
            with self.assertRaises(ValueError):calculate(expression)
        page = exact_page(visual_fixtures()[0])
        page['calculations'] = [dict(question='2',expression='45+23',answer=67)]
        with self.assertRaisesRegex(ValueError,'equals 68'):
            validate_exercises(page,load_grade_config()['1st-2nd'])

    def test_title_and_key_stay_synchronized(self):
        """A page cannot silently print a title different from its answer-key entry."""
        with self.assertRaisesRegex(ValueError,'exact planned'):
            validate_exercises(exact_page(visual_fixtures()[0]),{},'A different title')

    def test_missing_proofreading_verdict_not_approved(self):
        """Every page needs an explicit content result, without invented approvals."""
        for raw in [{}, {'pages':[]}, {'pages':[{'page_number':1,'issues':[]},{'page_number':1,'issues':[]}]}]:
            with self.assertRaises(ValueError):validate_audit(raw,{1,2})

    def test_proofreading_repairs_only_flagged_page_without_image_input(self):
        """Text-only correction keeps valid pages and rechecks the final key."""
        pack = dict(grade_band='1st-2nd', pages=[exact_page(s) for s in visual_fixtures()])
        original = pack['pages'][0]
        calls = []
        def ask(prompt,validator,label,tokens):
            """Emulate a concrete text defect followed by corrected content."""
            calls.append(prompt)
            return validator({'pages':[{'page_number':i,'issues':['Wrong written answer'] if len(calls)==1 and i==2 else []} for i in (1,2,3)]})
        repair = Mock(side_effect=lambda n,page,issues:dict(page,answers='Corrected open response.'))
        proofread_pack(pack,ask,repair)
        repair.assert_called_once()
        self.assertEqual(repair.call_args.args[0],2)
        self.assertIs(pack['pages'][0],original)
        self.assertEqual(pack['content_checks']['repair_rounds'],1)
        self.assertNotIn('image_url',calls[0]);self.assertNotIn('base64',calls[0])

    def test_decimal_math_is_exact_and_numeric_only(self):
        """Upper-grade money/fraction arithmetic avoids binary rounding and executable syntax."""
        from fractions import Fraction
        self.assertEqual(calculate(' 0.1 + 0.2 '),Fraction('0.3'))
        self.assertEqual(calculate('12.50+7.25'),Fraction('19.75'))
        self.assertEqual(calculate('3/4+1/8'),Fraction('7/8'))
        self.assertEqual(calculate('4 x 3'),12)
        self.assertEqual(calculate('20*15/100'),3)
        for expression in ['x+8=20','15%*20','£12+3','2**3','1e3+1','True+1','float(2)']:
            with self.subTest(expression=expression),self.assertRaises(ValueError):
                calculate(expression)
        page=exact_page(visual_fixtures()[0])
        page['html']+='<p>2. Add 12.50 + 7.25.</p>'
        page['calculations']=[dict(question='2',expression='12.50+7.25',answer='19.75')]
        validate_exercises(page,load_grade_config()['5th-6th'])
        self.assertIn(dict(expression='12.50+7.25',result='79/4'),page['computed_math'])
        page['calculations'][0]['expression']='x+8=20'
        with self.assertRaisesRegex(ValueError,'Question 2: calculation expression'):
            validate_exercises(page,load_grade_config()['5th-6th'])
        page['calculations'][0]=dict(question='2',expression='0.1+0.2',answer='0.3')
        with self.assertRaisesRegex(ValueError,'whole-number'):
            validate_exercises(page,load_grade_config()['1st-2nd'])

    def test_calculation_question_normalizes_explicit_labels_without_inventing_them(self):
        """Numeric task labels and harmless whitespace do not require another AI request."""
        for reference in [1,' 1 ']:
            page=exact_page(visual_fixtures()[0])
            page['calculations']=[dict(question=reference,expression='2+3',answer=5)]
            validate_exercises(page,load_grade_config()['Pre-K-K'])
            self.assertEqual(page['calculations'][0]['question'],'1')
        for reference in [None,' ',True,0,1.5,{},'x'*21]:
            page=exact_page(visual_fixtures()[0])
            page['calculations']=[dict(question=reference,expression='2+3',answer=5)]
            with self.subTest(reference=reference),self.assertRaisesRegex(ValueError,'calculations item 1'):
                validate_exercises(page,load_grade_config()['Pre-K-K'])
        page=exact_page(visual_fixtures()[0])
        page['calculations']=[dict(expression='2+3',answer=5)]
        with self.assertRaisesRegex(ValueError,'requires question'):
            validate_exercises(page,load_grade_config()['Pre-K-K'])
        self.assertNotIn('question',page['calculations'][0])
        page['calculations']=[dict(question=1,expression='2+3',answer=5),
                              dict(question=' 1 ',expression='3+2',answer=5)]
        with self.assertRaisesRegex(ValueError,'must be unique'):
            validate_exercises(page,load_grade_config()['Pre-K-K'])
