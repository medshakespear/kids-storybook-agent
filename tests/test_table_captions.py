"""Retain mixed-workbook table data without treating it as excess prose captions."""
from copy import deepcopy
import unittest

from core.content_binding import validate_caption_budget
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from core.response_schemas import exercise_schema
from core.table_captions import prepare_table_captions
from tests.coherent_fixtures import authored_page


def table_page():
    """Reproduce prefixed header IDs, one missing literal cell slot and unbound hub labels."""
    page=authored_page(mechanic='interpret_data')
    page['exercise'].update(goal='Compare supplied community hub data.',
                            directions='Use the table to compare how the hubs serve students.',
                            captions=[{'id':f'caption_col{i}','text':label} for i,label in enumerate(('Hub','Students','Days'),1)])
    page['exercise']['questions']=[{'id':'1','prompt':'Which hub serves the most students? Use one value from the table.',
                                  'answer':'Northside Hub serves the most students: 120.','space_mm':25}]
    header='<tr>'+''.join(f'<th data-content="caption_col{i}"></th>' for i in range(1,4))+'</tr>'
    data=[('Northside Hub','120','3'),('Southside Hub','100','3'),('Eastside Hub','90','2'),('Westside Hub','110','4')]
    rows=''
    for r,values in enumerate(data,1):
        rows+='<tr>'+''.join((f'<td data-content="caption_row{r}_c{c}">{value}</td>' if r==1 and c==1
                             else f'<td>{value}</td>') for c,value in enumerate(values,1))+'</tr>'
    table='<table style="width:175mm;border-collapse:collapse;font-size:12pt">'+header+rows+'</table>'
    page['html']=page['html'].replace('<div data-content="question_1"',table+'<div data-content="question_1"')
    return page


class TableCaptionTests(unittest.TestCase):
    """Bind real printed data while preserving limits on unrelated prose and tasks."""

    def test_reported_table_case_prints_in_both_active_grades(self):
        """More than six cells, prefixed header aliases and missing literal captions are retained."""
        for band in ('3rd-4th','5th-6th'):
            config=deepcopy(load_grade_config()[band]);config.update(purposeful_activity_layout=False,table_caption_limit=36)
            raw=table_page();before=deepcopy(raw)
            with self.subTest(band=band):
                page=validate_design(raw,config['student_font_pt'],quality=config,expected_title='Community Hubs',
                                     require_coherent=True,brief={'render_mode':'authored','mechanic':'interpret_data'})
                self.assertEqual(raw,before)
                self.assertEqual(len(page['exercise']['captions']),15)
                self.assertIn('Northside Hub',page['html'])
                self.assertIn('Southside Hub',page['html'])
                self.assertNotIn('data-content=',page['html'])
                self.assertEqual(page['html'].count('Northside Hub'),1)
                self.assertEqual(page['exercise']['questions'],before['exercise']['questions'])
                self.assertIn('width:175mm',page['html'])

    def test_duplicate_numeric_values_receive_distinct_cell_ids(self):
        """Repeated values in different rows print once each, without merging cells."""
        page=table_page()
        ids=prepare_table_captions(page)
        self.assertEqual(len(ids),15)
        threes=[c for c in page['exercise']['captions'] if c['text']=='3']
        self.assertEqual(len(threes),2)
        self.assertNotEqual(threes[0]['id'],threes[1]['id'])
        self.assertEqual(prepare_table_captions(page),ids)
        self.assertEqual(len(page['exercise']['captions']),15)

    def test_empty_unknown_cells_do_not_get_invented_data(self):
        """A missing value cannot be reconstructed from an answer or image brief."""
        page=table_page();page['html']=page['html'].replace('>Northside Hub</td>','></td>')
        prepare_table_captions(page)
        self.assertNotIn('row1_c1',{c['id'] for c in page['exercise']['captions']})
        self.assertIn('data-content="caption_row1_c1"',page['html'])

    def test_repeated_declared_headers_are_retained_with_distinct_slots(self):
        """Parallel tables can reuse a heading without a duplicate content-slot failure."""
        page=authored_page()
        page['exercise']['captions']=[{'id':'hub','text':'Hub'}]
        page['html']='<table><tr><th data-content="caption_hub"></th><th data-content="caption_hub"></th></tr></table>'
        ids=prepare_table_captions(page)
        self.assertEqual(len(ids),2)
        self.assertEqual([c['text'] for c in page['exercise']['captions']],['Hub','Hub'])
        self.assertEqual(page['html'].count('data-content="caption_hub"'),1)

    def test_commands_questions_and_answers_are_not_promoted_to_table_data(self):
        """Literal task instructions still need their proper question or directions slot."""
        for value in ('Calculate the total.','Which hub is largest?','Answer: Northside Hub'):
            page=authored_page();page['html']=f'<table><tr><td>{value}</td></tr></table>'
            self.assertEqual(prepare_table_captions(page),set())
            self.assertNotIn('captions',page['exercise'])

    def test_table_allowance_never_relaxes_non_table_caption_budget(self):
        """Only verified references inside table cells get the larger allowance."""
        captions=[{'id':f'cell_{i}','text':str(i)} for i in range(20)]
        with self.assertRaises(ValueError):validate_caption_budget(captions)
        validate_caption_budget(captions,table_ids={c['id'] for c in captions})
        with self.assertRaises(ValueError):
            validate_caption_budget(captions+[{'id':f'context_{i}','text':'A contextual label'} for i in range(7)],
                                    table_ids={c['id'] for c in captions})
        with self.assertRaises(ValueError):
            validate_caption_budget(captions,table_ids={str(i) for i in range(37)})

    def test_table_size_cap_and_schema_match_the_mixed_profile(self):
        """A real table is limited to 36 cells, while the ordinary schema remains unchanged."""
        page=authored_page();page['html']='<table><tr>'+''.join(f'<td>Site {i}</td>' for i in range(37))+'</tr></table>'
        with self.assertRaisesRegex(ValueError,'36'):
            prepare_table_captions(page)
        brief={'render_mode':'authored','mechanic':'interpret_data'}
        config=load_grade_config()['5th-6th']
        self.assertEqual(exercise_schema(brief,config)['properties']['captions']['maxItems'],14)
        mixed=dict(config,table_caption_limit=36)
        self.assertEqual(exercise_schema(brief,mixed)['properties']['captions']['maxItems'],50)


if __name__=='__main__':
    unittest.main()
