"""Exercise production reading/QCM contracts and actual A4 composition without APIs."""
from copy import deepcopy
import html
import unittest
import tempfile
from unittest.mock import patch

from weasyprint import HTML
from core.reading_generator import validate_unit, render_unit, generate_reading_pack
from core.creative_layout import answer_key_markup, pack_markup, data_only_fetcher, check_document
from core.pipeline import load_grade_config


PARAGRAPHS = [
    "A school garden can be a small place with a big job. Plants need sunlight, water, air, and room for their roots. Before planting, students observe the site at different times of day. A corner that looks sunny in the morning might be shaded in the afternoon. Recording these changes helps the class choose plants that can grow there. Good planning begins with watching carefully rather than guessing.",
    "Soil is more than loose dirt. It contains pieces of rock, decaying leaves, tiny living things, and spaces that hold air and water. Compost is material made from broken-down plant scraps. Adding compost can improve soil and help it hold moisture. Students should follow an adult's instructions when handling garden materials. They can compare soil samples by looking closely and describing what they notice, without tasting anything.",
    "Water also needs careful attention. If a plant receives too little water, its leaves may wilt. Too much water can fill the spaces around its roots and leave less air. Gardeners check the soil before watering instead of always using the same amount. A class can keep a notebook with dates, observations, and changes. Over time, these records show how conditions affect growth. The garden becomes an outdoor laboratory where students ask questions, collect evidence, and revise their plans. A plant that grows slowly is a reason to investigate, not proof that the garden has failed."
]
EXTENSIONS = [
    "Scientists call a test fair when the conditions being compared differ in a planned way. For example, students might give two similar plants different amounts of light while keeping their soil and watering alike. Otherwise, several changes could explain the results. A clear record makes it easier to notice patterns and discuss alternative explanations.",
    "One observation does not settle every question. A leaf might droop because the soil is dry, but heat or damage can also affect it. Students compare several observations before drawing a conclusion. They explain how their evidence supports a claim and acknowledge what they still do not know. This cautious reasoning is part of learning."
]


def reading_fixture(band='3rd-4th'):
    """Return original informational content with five evidence-supported questions."""
    paragraphs = list(PARAGRAPHS)
    if band == '5th-6th':
        paragraphs[1] += ' '+EXTENSIONS[0]
        paragraphs[2] += ' '+EXTENSIONS[1]
    questions = [
        dict(prompt='What is the main idea of the passage?',skill='main_idea',options=dict(A='Gardens only need sunlight.',B='Careful observations help people grow a garden.',C='All plants grow at the same speed.',D='Watering follows one fixed rule.'),answer='B',evidence='Good planning begins with watching carefully rather than guessing.',explanation='Observations guide planning and later decisions.'),
        dict(prompt='Why should students observe the site at different times?',skill='detail',options=dict(A='To find changes in shade and sunlight.',B='To make plants grow instantly.',C='To avoid keeping any records.',D='To replace soil with air.'),answer='A',evidence='A corner that looks sunny in the morning might be shaded in the afternoon.',explanation='Light at a site can change during the day.'),
        dict(prompt='What does revise mean in the final paragraph?',skill='vocabulary',options=dict(A='Forget completely',B='Copy without thinking',C='Change using new information',D='Finish without checking'),answer='C',evidence='students ask questions, collect evidence, and revise their plans.',explanation='Students use their evidence to improve a plan.'),
        dict(prompt='What can you infer about a slowly growing plant?',skill='inference',options=dict(A='It proves that all gardening has failed.',B='It never needs water.',C='Its leaves must be tasted.',D='Its conditions should be investigated.'),answer='D',evidence='A plant that grows slowly is a reason to investigate',explanation='Slow growth calls for evidence and investigation.'),
        dict(prompt='Why can too much water harm roots?',skill='cause_effect',options=dict(A='It makes sunlight disappear.',B='It leaves less air around the roots.',C='It removes every rock from soil.',D='It stops students from keeping notes.'),answer='B',evidence='Too much water can fill the spaces around its roots and leave less air.',explanation='Water can fill spaces that would otherwise contain air.')]
    if band == '5th-6th':
        questions[0].update(prompt="Why does the author describe students' observations and tests?",skill='author_purpose')
        questions[0]['options']['B']='To explain how evidence guides gardening decisions.'
    return dict(title='The Garden as a Laboratory',paragraphs=paragraphs,image_prompt='An original school garden scene with plants, soil and a notebook. No text.',questions=questions)


class ReadingGeneratorTests(unittest.TestCase):
    """Verify content validation, shared answers and both production grade layouts."""

    def setUp(self):
        """Load the production grade contract."""
        self.config = load_grade_config()

    def test_valid_grade_specific_readings(self):
        """Both grade ranges accept the original informational fixtures."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                self.assertEqual(validate_unit(reading_fixture(band),self.config[band]),reading_fixture(band))

    def test_invalid_content_is_rejected(self):
        """Missing choices, weak evidence, repeated tasks and short passages fail locally."""
        mutations = [
            lambda u:u['questions'][0]['options'].pop('D'),
            lambda u:u['questions'][0].update(evidence='This is not in the passage.'),
            lambda u:u['questions'][0]['options'].update(D=u['questions'][0]['options']['A']),
            lambda u:u['questions'][0].update(prompt='Count the plants.'),
            lambda u:u.update(paragraphs=['Too short.']*3),
            lambda u:u['questions'][1].update(prompt=u['questions'][0]['prompt']),
            lambda u:u['questions'][3].update(skill='detail'),
        ]
        for mutate in mutations:
            unit = reading_fixture(); mutate(unit)
            with self.assertRaises(ValueError):
                validate_unit(unit,self.config['3rd-4th'])

    def test_review_can_correct_passage_but_preserves_art_identity(self):
        """Review repairs content facts without changing the title or illustration contract."""
        original = reading_fixture(); reviewed=deepcopy(original)
        reviewed['paragraphs'][0] += ' Evidence helps.'
        validate_unit(reviewed,self.config['3rd-4th'],retained=original)
        reviewed['title']='A different topic'
        with self.assertRaises(ValueError):
            validate_unit(reviewed,self.config['3rd-4th'],retained=original)

    def test_pack_renders_twelve_pages_and_shared_key_for_both_bands(self):
        """Mock content calls while running real preflight, logo and final-sheet composition."""
        for band in ('3rd-4th','5th-6th'):
            def ask(prompt,validate,label,*args,**kwargs):
                """Return validated original content for planning, generation and review."""
                if label == 'Reading plan':
                    return validate(dict(title='Garden Investigations',overview='Read about how observations help a school garden grow.',topics=[f'Garden investigation {n}' for n in range(5)]))
                if 'blind answer verification' in label:
                    return validate({'solutions':[{'number':i,'answer':q['answer'],'reason':'Supported by the passage.','quality_issues':[]} for i,q in enumerate(reading_fixture(band)['questions'],1)]})
                return validate(reading_fixture(band))
            with self.subTest(band=band),patch('core.reading_generator.ask_json',side_effect=ask),patch('core.reading_generator.text_worker_limit',return_value=1):
                pack=generate_reading_pack('School gardens',band,self.config,book_title='Garden Science')
                self.assertEqual(pack['title'],'Garden Science')
                self.assertEqual(pack['cover']['title'],'Garden Science')
                self.assertEqual(len(pack['pages']),10)
                self.assertEqual(sum(len(p['images']) for p in [pack['cover']]+pack['pages']),6)
                self.assertEqual(len(pack['reading_units']),5)
                key=answer_key_markup(pack,pack['answer_key_layout'])
                for page in (3,5,7,9,11):
                    self.assertIn(f'PDF page {page}.',key)
                self.assertNotIn('Creative answers may vary',key)
                self.assertEqual(key.count('<strong>1.'),5)
                self.assertEqual(key.count('<strong>'),25)
                for page in pack['pages']:
                    self.assertNotIn('Observations guide planning',page['html'])
                doc=HTML(string=pack_markup(pack,self.config[band],preview=True),url_fetcher=data_only_fetcher).render()
                check_document(doc,12)

    def test_longest_question_contract_fits_both_bands(self):
        """Maximum permitted wording still fits without shrinking the student font."""
        for band in ('3rd-4th','5th-6th'):
            unit=reading_fixture(band)
            for i,q in enumerate(unit['questions']):
                q['prompt']=(f'Question {i+1}: '+'Which evidence best supports the explanation in this passage? '*3)[:120]
                q['options']={letter:(f'{letter} '+'Evidence explains a connection between observations and the result. '*2)[:55] for letter in 'ABCD'}
            with self.subTest(band=band):
                render_unit(unit,1,self.config[band])

    def test_maximum_passage_and_title_fit(self):
        """Longest allowed passages and headings retain the configured font and art."""
        for band in ('3rd-4th','5th-6th'):
            unit=reading_fixture(band)
            words=sum(len(p.split()) for p in unit['paragraphs'])
            extra=self.config[band]['reading_words']['max']-words
            if extra>0:
                unit['paragraphs'][-1]+=' '+' '.join(('Careful observation supports clear explanations. '*100).split()[:extra])
            unit['title']=('Investigating the relationships between evidence and school garden conditions ' *2)[:80]
            with self.subTest(band=band):
                render_unit(unit,1,self.config[band])

    def test_word_limit_with_longer_vocabulary_keeps_art_and_all_text(self):
        """Accepted passages with longer words fit both grades without content cuts."""
        from core.creative_layout import document_markup, fragment
        from core.reading_generator import passage_word_count
        sentence = ('Observations reveal environmental conditions affecting vegetation development, '
                    'including temperature, illumination, precipitation, and surrounding infrastructure.')
        for band, size in (('3rd-4th',86),('5th-6th',76)):
            unit = reading_fixture(band)
            words = ' '.join(unit['paragraphs']).split()
            extra = self.config[band]['reading_words']['max']-len(words)
            words += (sentence.split()*100)[:extra]
            unit['paragraphs'] = [' '.join(words[i*len(words)//4:(i+1)*len(words)//4]) for i in range(4)]
            retained = deepcopy(unit)
            with self.subTest(band=band):
                validate_unit(unit,self.config[band])
                self.assertEqual(passage_word_count(unit['paragraphs']),self.config[band]['reading_words']['max'])
                reading,quiz = render_unit(unit,4,self.config[band])
                self.assertEqual(unit,retained)
                self.assertIn(f'width:{size}mm;height:{size}mm',reading['html'])
                for paragraph in unit['paragraphs']:
                    self.assertIn(paragraph,html.unescape(reading['html']))
                for page in (reading,quiz):
                    doc = HTML(string=document_markup([fragment(page,True)],self.config[band]['student_font_pt']),url_fetcher=data_only_fetcher).render()
                    check_document(doc,1)
                    text_boxes = [b for b in doc.pages[0]._page_box.descendants() if getattr(b,'text','').strip()]
                    self.assertTrue(text_boxes)
                    self.assertTrue(all(b.style['font_size'] >= self.config[band]['student_font_pt']*96/72-.01 for b in text_boxes))

    def test_qcm_recomposition_retains_questions_options_and_key(self):
        """Measured fallback preserves the complete QCM and its canonical answer model."""
        from core.creative_layout import check_page as real_check_page
        for band in ('3rd-4th','5th-6th'):
            unit = reading_fixture(band)
            calls = []
            def check(page,font):
                """Exercise recovery after a default QCM overflow, then measure its result."""
                calls.append(page['page_type'])
                if page['page_type']=='qcm' and calls.count('qcm')==1:
                    raise ValueError('Design overflow: expected 1 pages, got 2')
                return real_check_page(page,font)
            with self.subTest(band=band),patch('core.reading_generator.check_page',side_effect=check):
                reading,quiz = render_unit(unit,4,self.config[band])
                self.assertEqual(calls,['reading','qcm','qcm'])
                for number,question in enumerate(unit['questions'],1):
                    self.assertIn(question['prompt'],html.unescape(quiz['html']))
                    for choice in question['options'].values():
                        self.assertIn(choice,html.unescape(quiz['html']))
                    self.assertEqual(quiz['answer_items'][number-1]['answer'],question['answer'])

    def test_production_pipeline_embeds_art_and_publishes_complete_pdf(self):
        """Use the real new production route with mocked text and local artwork."""
        from core.pipeline import generate_book
        from tests.test_creative_design import attach_creative_test_art
        def ask(prompt,validate,label,*args,**kwargs):
            """Supply validated content while preserving production rendering stages."""
            if label == 'Reading plan':
                return validate(dict(title='Garden Investigations',overview='Read about garden evidence.',topics=[f'Garden {n}' for n in range(5)]))
            if 'blind answer verification' in label:
                return validate({'solutions':[{'number':i,'answer':q['answer'],'reason':'Supported by the passage.','quality_issues':[]} for i,q in enumerate(reading_fixture('5th-6th')['questions'],1)]})
            return validate(reading_fixture('5th-6th'))
        with tempfile.TemporaryDirectory() as folder, \
             patch('core.reading_generator.ask_json',side_effect=ask), \
             patch('core.reading_generator.text_worker_limit',return_value=1), \
             patch('core.pipeline.text_provider_names'),patch('core.pipeline.image_provider_name'), \
             patch('core.pipeline.generate_activity_images',side_effect=attach_creative_test_art):
            pack,path=generate_book(theme='School gardens',grade_band='5th-6th',output_dir=folder,book_title='Garden Science')
            self.assertEqual(pack['title'],'Garden Science')
            self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
            self.assertEqual(pack['content_format'],'reading_qcm')
            self.assertEqual(pack['page_count'],12)
            self.assertEqual(pack['content_checks']['questions'],25)
            self.assertNotIn('path',pack['pages'][0]['images'][0])

    def test_disabled_grades_never_call_ai(self):
        """Only grades 3–6 are available in the production engine."""
        with patch('core.reading_generator.ask_json') as ask:
            with self.assertRaises(ValueError):
                generate_reading_pack('Garden','1st-2nd',self.config)
            ask.assert_not_called()

