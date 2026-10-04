"""Regress name_label metadata and inadequate three-illustration compositions."""
from copy import deepcopy
import unittest
from core.creative_generator import validate_design
from core.layout_recovery import layout_recovery_candidates
from core.illustration_gallery import illustration_gallery, gallery_minimum_height
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class ThreePanelRecoveryTests(unittest.TestCase):
    """Retain artwork and response areas while fitting early-grade visual exercises."""
    def page(self):
        """Create three illustrated tasks with canonical response spaces."""
        page=authored_page()
        page['exercise']['directions']='Look at the garden pictures. Draw three helpful ideas.'
        page['exercise']['questions']=[{'id':str(i),'prompt':prompt,'answer':'Accept a helpful garden idea.','space_mm':20}
            for i,prompt in enumerate(('Draw a tool to carry water.','Draw a shelter for a plant.','Draw a way to save water.'),1)]
        page['images']=[{'id':'scene'+str(i),'prompt':'A clear original garden scene without lettering.'} for i in range(1,4)]
        page['html']='<h1 data-content="title"></h1><p data-content="name_label"></p><p data-content="directions"></p>'
        page['html']+=''.join(f'<img data-asset="scene{i}" style="width:40mm;height:36mm"/>' for i in range(1,4))
        page['html']+=''.join(f'<div data-content="question_{i}"></div>' for i in range(1,4))
        return page

    def validate(self,page, purposeful=False):
        """Run actual font, artwork area, binding and A4 bounds checks."""
        config=load_grade_config()['1st-2nd'];config['purposeful_activity_layout']=purposeful
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title='Garden Helpers',require_coherent=True,
            brief={'title':'Garden Helpers','render_mode':'authored','mechanic':'design shelter'} if purposeful else None)

    def test_name_label_alias_binds_to_existing_metadata(self):
        """An alternate name label is interpreted as the canonical field."""
        page=self.page()
        page['html']=page['html'].replace('width:40mm;height:36mm','width:58mm;height:60mm')
        result=self.validate(page)
        self.assertIn('Name:',result['html'])
        self.assertNotIn('name_label',result['html'])

    def test_balanced_gallery_recovers_all_three_assets_and_tasks(self):
        """The first lossless candidate meets visual targets without an oversized main image."""
        page=self.page();original=deepcopy(page)
        candidates=list(layout_recovery_candidates(page,13,10000))
        self.assertEqual(len(candidates),2)
        result=self.validate(candidates[0])
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        for i in range(1,4):
            self.assertIn(f'data-asset="scene{i}"',result['source_layout'])
        self.assertEqual(page,original)

    def test_initial_canonical_presentation_uses_substantial_panels(self):
        """Production presentation prevents the tiny-art defect before provider repair."""
        page=self.page()
        result=self.validate(page,purposeful=True)
        self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])
        self.assertIn('<table',result['source_layout'])
        self.assertEqual(result['html'].count('height:20mm'),3)

    def test_gallery_fits_two_and_four_panel_variants(self):
        """Panel gutters and table columns fit the printable width at both count limits."""
        for count in (2,4):
            with self.subTest(count=count):
                page=self.page()
                page['images']=[{'id':f'scene{i}','prompt':'A clear garden illustration without lettering.'} for i in range(1,count+1)]
                page['html']='<h1 data-content="title"></h1><p data-content="directions"></p>'
                page['html']+=illustration_gallery([a['id'] for a in page['images']],gallery_minimum_height(count,10000))
                page['html']+=''.join(f'<div data-content="question_{i}"></div>' for i in range(1,4))
                result=self.validate(page)
                self.assertEqual(len(result['images']),count)
                self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])

    def test_alias_does_not_allow_duplicate_name_fields(self):
        """Two equivalent metadata fields still fail rather than printing twice."""
        page=self.page();page['html']+='<p data-content="name"></p>'
        with self.assertRaisesRegex(ValueError,'content slot: name; already printed'):
            self.validate(page)

    def test_gallery_budget_and_invalid_ids(self):
        """Gallery markup meets dimensions without external images or unsafe identifiers."""
        height=gallery_minimum_height(3,10000)
        markup=illustration_gallery(['a','b','c'],height)
        self.assertEqual(markup.count('data-asset='),3)
        self.assertIn('height:61.0000mm',markup)
        with self.assertRaises(ValueError):
            illustration_gallery(['a','../b'],height)
