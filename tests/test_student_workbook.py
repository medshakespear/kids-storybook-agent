"""Regressions from the reviewed fact/opinion PDFs and cramped writing panels."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from weasyprint import HTML
from core.creative_generator import ask_json,layout_contract,validate_design,validate_plan
from core.creative_layout import document_markup,fragment,data_only_fetcher,check_document
from core.pipeline import load_grade_config
from core.response_schemas import design_schema,plan_schema
from core.student_workbook import check_response_width,response_height
from core.varied_generator import generate_varied_pack
from core.workbook_review import review_varied_pack,validate_review
from tests.test_plan_mechanics import plan_for


def workbook_config(band):
    """Read the real opt-in profile rather than duplicating its configuration constants."""
    with patch('core.varied_generator.generate_creative_pack',return_value={'pages':[]}) as generate:
        generate_varied_pack('Fact and Opinion',band,load_grade_config())
    return generate.call_args.args[2][band]


def evidence_page(narrow=False):
    """Provide two labeled sources and two grade-appropriate tasks with undersized drafts."""
    page={'images':[{'id':'weather','prompt':'A school weather observation station with a rain gauge and clouds. Teal and gold illustration, no text.'}],
        'exercise':{'render_mode':'authored','mechanic':'compare_and_revise',
            'goal':'Distinguish checkable information from personal judgments using evidence.',
            'directions':'Read both fictional weather notes. Use their wording to support your answers.',
            'stimuli':[{'id':'note_a','label':'Card A','text':'A rain gauge collected 12 millimeters of rain on Monday.'},
                {'id':'note_b','label':'Card B','text':'Rainy days are the most enjoyable days for everyone.'}],
            'questions':[{'id':'1','prompt':'Classify Cards A and B as fact or opinion. Explain what makes each statement checkable or personal.',
                'answer':'A: fact; its rainfall can be measured. B: opinion; enjoyment is a personal preference.', 'space_mm':8},
                {'id':'2','prompt':'Rewrite Card B as a checkable weather observation. Use only information supplied in Card A.',
                'answer':'Accept an accurate neutral statement about the 12 millimeters of rainfall recorded on Monday.','space_mm':12}]}}
    header='<h1 data-content="title" style="color:#167E80;background-color:#EAF5F2;padding:2mm"></h1><p data-content="name"></p><p data-content="directions"></p>'
    sources='<p data-content="stimulus_note_a" style="background-color:#EDF7F4;padding:2mm"></p><p data-content="stimulus_note_b" style="background-color:#FFF3D9;padding:2mm"></p>'
    questions='<div data-content="question_1" style="margin:2mm 0"></div><div data-content="question_2" style="margin:2mm 0"></div>'
    art='<img data-asset="weather" style="width:92mm;height:92mm"/>'
    page['html']=header+'<table style="width:175mm;table-layout:fixed"><tr><td style="width:94mm;padding:0;vertical-align:top">'+art+'</td><td style="width:81mm;padding:0;vertical-align:top">'+sources+(questions if narrow else '')+'</td></tr></table>'+(questions if not narrow else '')
    return page


class StudentWorkbookTests(unittest.TestCase):
    """Use real rendering and native retry/reflow behavior for both active grade bands."""

    def validate(self,page,band):
        """Check actual canonical content, dimensions, images, fonts and pagination."""
        config=workbook_config(band)
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title='Weather Evidence Lab',require_coherent=True)

    def test_minimum_answer_heights_and_lines_are_applied_without_changing_tasks(self):
        """Short answers gain 35mm and rewrites 50mm; already larger requests stay larger."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page();original=deepcopy(raw);page=self.validate(raw,band)
            self.assertEqual([q['space_mm'] for q in page['exercise']['questions']],[35,50])
            for q,old in zip(page['exercise']['questions'],original['exercise']['questions']):
                for key in ('prompt','answer','id'): self.assertEqual(q[key],old[key])
            self.assertIn('height:35mm',page['html']);self.assertIn('height:50mm',page['html'])
            self.assertIn('solid #CCD7DF',page['html'])
            self.assertEqual(response_height({'prompt':'Rewrite the note.','space_mm':65},workbook_config(band)),65)
            self.assertEqual(raw,original)

    def test_narrow_answers_reflow_to_full_width_without_an_extra_provider_request(self):
        """The exact tall/narrow side-column failure is measured and repaired locally."""
        for band in ('3rd-4th','5th-6th'):
            raw=evidence_page(True);config=workbook_config(band)
            with self.assertRaisesRegex(ValueError,'answer box is only'):
                self.validate(raw,band)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            brief={'render_mode':'authored','mechanic':'compare_and_revise'}
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                 patch('core.creative_generator.time.sleep'):
                page=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                    lambda value:self.validate(value,band),'Activity design 1',response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            doc=HTML(string=document_markup([fragment(page,True)],config['student_font_pt']),url_fetcher=data_only_fetcher).render()
            check_document(doc,1);check_response_width(doc,page['quality_profile'])
            self.assertEqual(page['images'],raw['images'])

    def test_source_labels_are_printed_inside_their_own_bound_cards(self):
        """Card A and Card B cannot sit in empty adjacent table cells unrelated to their body."""
        page=self.validate(evidence_page(),'3rd-4th')
        self.assertIn('<strong>Card A</strong><br/>A rain gauge',page['html'])
        self.assertIn('<strong>Card B</strong><br/>Rainy days',page['html'])

    def test_drawing_workspace_is_larger_but_has_no_handwriting_lines(self):
        """An open sketch retains a genuinely blank 50mm working surface."""
        raw=evidence_page();raw['exercise']['questions']=raw['exercise']['questions'][:1]
        raw['exercise']['questions'][0].update(prompt='Draw a weather station. Label the rain gauge.',answer='Accept a labeled weather station including a rain gauge.')
        raw['html']=raw['html'].replace('<div data-content="question_2" style="margin:2mm 0"></div>','')
        page=self.validate(raw,'3rd-4th')
        self.assertIn('height:50mm',page['html']);self.assertNotIn('solid #CCD7DF',page['html'])

    def test_science_errors_and_filler_plans_are_rejected_without_relaxing_math(self):
        """Known PDF defects cannot pass because they fit a page or have a computed puzzle key."""
        for band in ('3rd-4th','5th-6th'):
            page=evidence_page();page['exercise']['stimuli'][0]['text']='Our barometer recorded a heavy rainfall of 45 millimeters.'
            with self.assertRaisesRegex(ValueError,'rain gauge measures rainfall'): self.validate(page,band)
            for mechanic in ('maze','matching','sort'):
                with self.assertRaisesRegex(ValueError,'contextual authored'):
                    validate_plan(plan_for([mechanic]),1,require_coherent=True,student_workbook=True)
            with self.assertRaisesRegex(ValueError,'contextual authored'):
                validate_plan(plan_for(['statement_path'],'authored'),1,require_coherent=True,student_workbook=True)
            page=evidence_page();page['exercise']['questions'][0].update(prompt='Calculate 35+12.',answer='48',calculation={'expression':'35+12','answer':'48'})
            with self.assertRaisesRegex(ValueError,'declared math answer is incorrect'): self.validate(page,band)
        self.assertEqual(len(plan_schema(10,authored_only=True)['properties']['pages']['items']['anyOf']),1)


class WorkbookReviewTests(unittest.TestCase):
    """Require real per-question verdicts and a bounded correction before publication."""

    def rows(self,pages):
        """Build complete provider-fixture verdicts with independent solutions."""
        return {'pages':[{'page_number':p['page_number'],'source_accuracy':True,'no_answer_leak':True,
            'reason':'The sources support the complete task.','issues':[],
            'question_checks':[{'id':q['id'],'source_support':True,'skill_match':True,
                'answer_correct':True,'solution':'A: measurable rainfall; B: preference. Rewrite using the Monday measurement.',
                'reason':'Measurement is checkable; enjoyment is personal.'} for q in p['exercise']['questions']]} for p in pages]}

    def test_negative_verdicts_cannot_be_hidden_by_an_empty_issues_list(self):
        """Science errors, answer leaks and a wrong skill each force a content repair."""
        pages=[dict(evidence_page(),page_number=1)]
        for flag in ('source_accuracy','no_answer_leak','source_support','skill_match','answer_correct'):
            rows=self.rows(pages)
            if flag in {'source_accuracy','no_answer_leak'}: rows['pages'][0][flag]=False
            else: rows['pages'][0]['question_checks'][0][flag]=False
            self.assertTrue(validate_review(rows,pages)[1])
        rows=self.rows(pages);rows['pages'][0]['question_checks'].pop()
        with self.assertRaisesRegex(ValueError,'every printed question'): validate_review(rows,pages)

    def test_bounded_batches_repair_and_recheck_only_the_affected_activity(self):
        """Small review batches retain global page IDs and do not repeat unaffected work."""
        pack={'grade_band':'3rd-4th','pages':[dict(evidence_page(),title='Weather Evidence') for _ in range(4)]}
        calls=[];fixed=False
        def ask(prompt,validate,label,tokens,**kwargs):
            """Flag the observed all-three/five defect once despite an empty issues array."""
            pages=json.loads(prompt.split('Activities:\n',1)[1]);calls.append([p['page_number'] for p in pages])
            verdict=self.rows(pages)
            for row in verdict['pages']:
                if row['page_number']==2 and not fixed:
                    row['question_checks'][0].update(answer_correct=False,
                        reason='The prompt asks for all three words, but five opinion indicators qualify.')
            return validate(verdict)
        def repair(number,page,issues):
            """Represent a corrected content page while keeping the original response heights."""
            nonlocal fixed
            self.assertEqual(number,2);self.assertIn('five opinion indicators',issues[0]);fixed=True
            return deepcopy(page)
        review_varied_pack(pack,ask,repair)
        self.assertEqual(calls,[[1,2,3],[4],[2]])
        self.assertEqual(pack['content_checks']['repair_rounds'],1)

    def test_repeated_semantic_failure_blocks_publication(self):
        """A repaired page still teaching the wrong skill cannot receive passed status."""
        pack={'grade_band':'5th-6th','pages':[dict(evidence_page(),title='Weather Evidence')]}
        def ask(prompt,validate,label,tokens,**kwargs):
            """Return the observed shape-match substitution as a persistent skill mismatch."""
            pages=json.loads(prompt.split('Activities:\n',1)[1]);rows=self.rows(pages)
            rows['pages'][0]['question_checks'][0].update(skill_match=False,
                reason='Shape matching does not match weather claims to supporting evidence.')
            return validate(rows)
        with self.assertRaisesRegex(ValueError,'still needs correction'):
            review_varied_pack(pack,ask,lambda n,page,issues:page)
        self.assertNotIn('content_checks',pack)
