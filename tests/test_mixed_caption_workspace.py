"""Mixed-mode label capacity and blank writing-line regressions."""
from copy import deepcopy
import unittest
from core.content_binding import caption_budget_available, validate_caption_budget
from core.creative_generator import validate_design
from core.page_contract import BoundLayout
from core.pipeline import load_grade_config
from core.response_schemas import exercise_schema
from tests.coherent_fixtures import authored_page


class MixedCaptionWorkspaceTests(unittest.TestCase):
    """Keep complete authored content while distinguishing blank workspace from tasks."""

    def test_blank_lines_are_retained_without_accepting_unbound_wording(self):
        """Underscores are workspace; a task appended to them remains an error."""
        parser=BoundLayout({'title':'Test'})
        parser.feed('<p>_______________</p>')
        self.assertIn('_______________',''.join(parser.parts))
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            BoundLayout({'title':'Test'}).feed('<p>_______________ explain why</p>')

    def test_mixed_captions_and_blank_workspace_print_for_both_grades(self):
        """The reported combination prints without dropping labels or student questions."""
        for band in ('3rd-4th','5th-6th'):
            config=deepcopy(load_grade_config()[band])
            config.update(purposeful_activity_layout=False,context_caption_limit=24,table_caption_limit=36)
            page=authored_page()
            page['exercise']['captions']=[{'id':f'label_{i}','text':f'Garden zone {i}'} for i in range(8)]
            labels=''.join(f'<span data-content="caption_label_{i}" style="margin-right:2mm"></span>' for i in range(8))
            page['html']=page['html'].replace('<div data-content="question_1"', '<p>'+labels+'</p><p>_______________</p><div data-content="question_1"')
            result=validate_design(page,config['student_font_pt'],quality=config,expected_title='Garden Design',require_coherent=True)
            self.assertIn('_______________',result['html'])
            self.assertEqual(len(result['exercise']['captions']),8)
            self.assertEqual(result['_caption_context_limit'],24)
            self.assertEqual(result['exercise']['questions'],page['exercise']['questions'])

    def test_table_cells_do_not_consume_layout_repair_context_budget(self):
        """A table-heavy page can retain additional short labels during local repairs."""
        captions=[{'id':f'cell{i}','text':str(i)} for i in range(30)]
        table_ids={c['id'] for c in captions}
        self.assertTrue(caption_budget_available(captions,'Context label',context_limit=24,table_ids=table_ids))
        labels=[{'id':f'label{i}','text':'Context label'} for i in range(24)]
        validate_caption_budget(captions+labels,context_limit=24,table_ids=table_ids)
        self.assertFalse(caption_budget_available(captions+labels,'New context',context_limit=24,table_ids=table_ids))
        with self.assertRaises(ValueError):validate_caption_budget(labels)

    def test_mixed_schema_and_exact_schema_use_distinct_limits(self):
        """Mixed authored pages get room for labels without relaxing the exact puzzle schema."""
        config=dict(load_grade_config()['5th-6th'],context_caption_limit=24,table_caption_limit=36)
        self.assertEqual(exercise_schema({'render_mode':'authored','mechanic':'compare'},config)['properties']['captions']['maxItems'],68)
        self.assertEqual(exercise_schema({'render_mode':'exact','mechanic':'count'},config)['properties']['captions']['maxItems'],14)


if __name__=='__main__':unittest.main()
