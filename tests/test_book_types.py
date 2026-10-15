"""Opt-in mixed exercises, default QCM routing and model-owned print layouts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import webhook_server as web
from core.book_types import DEFAULT_BOOK_TYPE, require_book_type
from core.creative_generator import validate_plan
from core.pipeline import generate_book, load_grade_config
from core.varied_generator import generate_varied_pack
from tests.coherent_fixtures import authored_page
from tests.test_creative_design import attach_creative_test_art
from tests.test_plan_mechanics import plan_for


ACTIONS = ['compare_texts', 'sequence_process', 'interpret_data', 'vocabulary', 'applied_math',
           'design_shelter', 'explain_cause', 'persuasive_writing', 'classify_conditions', 'plan_investigation']
TASKS = [
    ('Compare two methods for watering a garden. Write one benefit of each.', 'Accept two distinct methods and an accurate benefit of each.'),
    ('Write three steps for planting a seed in a sensible order.', 'Place a seed in suitable soil, water it and provide suitable light.'),
    ('A seedling grew 2 cm in week one and 5 cm in week two. Which week showed more growth? Explain.', 'Week two; its 5 cm growth is greater than the 2 cm growth in week one.'),
    ('Write a sentence using observe to mean noticing and recording information.', 'Accept a sentence using observe to mean noticing and recording information.'),
    ('A class has 24 seeds and plants 8 seeds. How many seeds remain?', '16 seeds remain.'),
    ('Draw a plant shelter. Label how water and sunlight can reach the plant.', 'Accept a shelter design showing access for water and sunlight.'),
    ('Explain why a plant in a dark cupboard might grow differently from one near a window.', 'The cupboard provides less light, which can affect growth.'),
    ('Write two reasons your class should care for a school garden.', 'Accept two relevant reasons supported with explanations.'),
    ('Sort these needs into plant needs and classroom tools: water, sunlight, ruler, notebook.', 'Plant needs: water, sunlight. Classroom tools: ruler, notebook.'),
    ('Plan a fair test comparing light levels. Name two conditions to keep the same.', 'Compare light levels while keeping plant type and water amount the same.'),
]


def mixed_plan():
    """Return ten context-specific student actions for offline generation."""
    plan = plan_for(ACTIONS, mode='authored')
    plan.update(title='Garden Challenges', art_direction='Crisp teal, coral and gold garden illustrations.',
                character_description='Original plants and tools.', cover_brief='Large garden art, title and grade only.')
    for i, page in enumerate(plan['pages']):
        page.update(title=f'Garden Challenge {i+1}', learning_goal=TASKS[i][0],
                    activity_concept=TASKS[i][0], layout_brief=f'Composition {i+1}: meaningful garden scene and response panel.')
    return plan


def mixed_ask(prompt, validate, label, *args, **kwargs):
    """Supply model-like JSON through real content and print validators without API calls."""
    if label == 'Creative plan':
        return validate(mixed_plan())
    if label == 'Cover design':
        return validate({'html':'<h1 style="font-size:30pt;color:#167E80">Garden Science</h1>'
                                '<p style="font-size:16pt">Grades 3–6</p>'
                                '<img data-asset="scene" style="width:175mm;height:130mm"/>',
                         'images':[{'id':'scene','prompt':'An original flourishing school garden, teal and coral. No lettering.'}]})
    if label == 'Exercise proofreading':
        return validate({'pages':[{'page_number':n,'issues':[]} for n in range(1,11)]})
    if label == 'Workbook content review':
        import json
        pages=json.loads(prompt.split('Activities:\n',1)[1])
        return validate({'pages':[{'page_number':p['page_number'],'source_accuracy':True,
            'no_answer_leak':True,'reason':'The garden task has sufficient information and a relevant answer.',
            'issues':[],'question_checks':[{'id':q['id'],'source_support':True,'skill_match':True,
                'answer_correct':True,'solution':TASKS[p['page_number']-1][1],
                'reason':'The solution addresses the complete printed garden task.'}
                for q in p['exercise']['questions']]} for p in pages]})
    number=int(label.rsplit(' ',1)[1])
    page=authored_page(mechanic=ACTIONS[number-1])
    page['exercise']['goal']='Investigate a school garden.'
    page['exercise']['directions']='Use the information provided. Complete the garden challenge below.'
    page['exercise']['questions'][0].update(prompt=TASKS[number-1][0],answer=TASKS[number-1][1],space_mm=35)
    if number==5:
        page['exercise']['questions'][0]['calculation']={'expression':'24-8','answer':16}
    page['html']=page['html'].replace('#FFF7DE', ['#FFF7DE','#EAF3FC','#F2E8FA'][number%3])
    return validate(page)


class BookTypeTests(unittest.TestCase):
    """Keep the established QCM branch and expose a separate varied-activity branch."""

    def test_type_defaults_and_invalid_values(self):
        """Missing selection stays QCM; malformed selections are rejected explicitly."""
        self.assertEqual(require_book_type(),DEFAULT_BOOK_TYPE)
        for value in ('story', '', None, [], False, 3):
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_book_type(value)

    def test_pipeline_routes_defaults_and_selected_types_without_cross_calls(self):
        """Both branches share final delivery but only the selected generator runs."""
        for selected in (None, 'reading_qcm','varied_activities'):
            pack={'title':'Workbook','pages':[{'images':[]}]*10,'cover':{'images':[]},'theme':'Garden','grade_band':'3rd-4th'}
            def write_pdf(story, config, path):
                """Write a minimal staging fixture to verify atomic publication."""
                Path(path).write_bytes(b'%PDF-test')
            with tempfile.TemporaryDirectory() as folder,patch('core.pipeline.text_provider_names'), \
                 patch('core.pipeline.image_provider_name'),patch('core.pipeline.generate_activity_pack',return_value=deepcopy(pack)) as reading, \
                 patch('core.pipeline.generate_varied_pack',return_value=deepcopy(pack)) as varied, \
                 patch('core.pipeline.generate_activity_images'),patch('core.pipeline.build_activity_pdf',side_effect=write_pdf):
                options={} if selected is None else {'book_type':selected}
                result,path=generate_book(theme='Garden',grade_band='3rd-4th',output_dir=folder,book_title='Garden Science',**options)
                self.assertTrue(path.is_file())
                self.assertEqual(result['book_type'],selected or 'reading_qcm')
                expected, unused=(varied,reading) if selected=='varied_activities' else (reading,varied)
                expected.assert_called_once()
                unused.assert_not_called()
                self.assertEqual(expected.call_args.kwargs['book_title'],'Garden Science')

    def test_invalid_pipeline_type_never_calls_providers(self):
        """Direct Python callers have the same input boundary as the web app."""
        with patch('core.pipeline.text_provider_names') as providers:
            with self.assertRaises(ValueError):
                generate_book(theme='Garden',grade_band='3rd-4th',book_type='unknown')
            providers.assert_not_called()

    def test_variety_plan_rejects_relabelled_repeated_actions_and_generic_puzzles(self):
        """Mixed mode requires diversity, not ten renamed copies of one action."""
        self.assertEqual(len(validate_plan(mixed_plan(),10,require_coherent=True,require_variety=True)['pages']),10)
        for plan in (plan_for(['design']*10,mode='authored'),
                     plan_for(['design']*6+ACTIONS[:4],mode='authored'),
                     plan_for(['count','maze','pattern','matching','differences']*2,mode='exact')):
            with self.assertRaises(ValueError):
                validate_plan(plan,10,require_coherent=True,require_variety=True)

    def test_mixed_wrapper_copies_config_and_preserves_model_layouts(self):
        """Neither selected grade profile nor the QCM path is mutated by mixed mode."""
        config=load_grade_config(); original=deepcopy(config)
        with patch('core.varied_generator.generate_creative_pack',return_value={'pages':[]}) as generate:
            pack=generate_varied_pack('Garden','5th-6th',config,book_title='Garden Science')
        self.assertEqual(config,original)
        self.assertFalse(generate.call_args.args[2]['5th-6th']['purposeful_activity_layout'])
        self.assertTrue(generate.call_args.kwargs['require_variety'])
        self.assertIn('fictional',generate.call_args.kwargs['source_context'])
        self.assertEqual(pack['content_format'],'varied_activities')

    def test_complete_mixed_book_in_both_grades_has_verified_math_and_gemini_compositions(self):
        """Run actual schema/content, A4 rendering, logo, key and PDF publication offline."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band),tempfile.TemporaryDirectory() as folder, \
                 patch('core.creative_generator.ask_json',side_effect=mixed_ask), \
                 patch('core.creative_generator.text_worker_limit',return_value=1), \
                 patch('core.pipeline.text_provider_names'),patch('core.pipeline.image_provider_name'), \
                 patch('core.pipeline.generate_activity_images',side_effect=attach_creative_test_art):
                pack,path=generate_book(theme='School gardens',grade_band=band,book_type='varied_activities',
                                        output_dir=folder,book_title='Garden Science')
                self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
                self.assertEqual(pack['page_count'],12)
                self.assertEqual(pack['title'],'Garden Science')
                self.assertEqual(pack['book_type'],'varied_activities')
                self.assertEqual(pack['content_checks']['status'],'passed')
                self.assertEqual(len({p['exercise']['mechanic'] for p in pack['pages']}),10)
                self.assertIn('width:175mm;height:75mm',pack['pages'][0]['html'])
                self.assertNotIn('_canonical_presentation',pack['pages'][0])
                self.assertEqual(pack['pages'][4]['calculations'][0]['expression'],'24-8')
                self.assertNotIn('path',pack['pages'][0]['images'][0])


class WebBookTypeTests(unittest.TestCase):
    """The dropdown and all existing input modes forward the book type consistently."""

    def test_form_and_all_input_modes_accept_both_types(self):
        client=web.app.test_client()
        with patch.object(web,'list_books',return_value=[]):
            html=client.get('/').data
        self.assertIn(b'id="book-type"',html)
        self.assertIn(b'value="reading_qcm"',html)
        self.assertIn(b'value="varied_activities"',html)
        for source in ({'description':'Garden skills'},{'link':'https://example.com/'},
                       {'event':'Halloween'},{'event':'Media Literacy'}):
            for kind in ('reading_qcm','varied_activities'):
                brief=web.generation_input(dict(source,grade_band='5th-6th',book_type=kind))
                self.assertEqual(brief['book_type'],kind)
        self.assertEqual(web.generation_input({'description':'Gardens'})['book_type'],'reading_qcm')

    def test_endpoint_passes_type_and_registers_it_for_all_input_modes(self):
        client=web.app.test_client()
        with patch.object(web,'_authorized',return_value=True), \
             patch.object(web,'read_reference',return_value={'url':'https://example.com/','title':'Garden','description':'','text':'Original garden information.'}), \
             patch.object(web,'generate_book',return_value=({'title':'Workbook'},Path('book.pdf'))) as generate, \
             patch.object(web,'register_book') as register:
            for source in ({'description':'Garden skills'},{'link':'https://example.com/'},{'event':'Halloween'},{'event':'Media Literacy'}):
                for kind in ('reading_qcm','varied_activities'):
                    response=client.post('/generate',json=dict(source,grade_band='3rd-4th',book_type=kind))
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(generate.call_args.kwargs['book_type'],kind)
                    self.assertEqual(response.json['book_type'],kind)
                    self.assertEqual(register.call_args.args[0]['book_type'],kind)

    def test_type_is_durable_and_visible_after_catalog_reload(self):
        """A completed mixed book keeps its format in the single state file and library card."""
        from core import book_library, state_manager
        with tempfile.TemporaryDirectory() as folder:
            state_path=Path(folder)/'state.json'
            def read_state():
                """Load the isolated catalog as a restarted process would."""
                return state_manager.load_state(state_path)
            def save_state(state):
                """Persist via the production atomic state writer."""
                return state_manager.save_state(state,state_path)
            with patch.object(book_library,'OUTPUT_DIR',Path(folder)), \
                 patch.object(book_library,'load_state',side_effect=read_state), \
                 patch.object(book_library,'save_state',side_effect=save_state):
                book_library.register_book({'title':'Garden Challenges','theme':'Garden','grade_band':'3rd-4th',
                                            'book_type':'varied_activities'},'garden.pdf','On demand')
                records=book_library.list_books()
                self.assertEqual(records[0]['book_type'],'varied_activities')
                self.assertEqual(read_state()['generated'][0]['book_type'],'varied_activities')
                with patch.object(web,'list_books',return_value=records):
                    self.assertIn(b'Mixed exercises',web.app.test_client().get('/').data)

    def test_background_jobs_retain_type_and_reject_unknown_types(self):
        client=web.app.test_client()
        with web._jobs_lock: web._jobs.clear()
        with patch.object(web,'_authorized',return_value=True),patch.object(web._job_worker,'submit') as submit:
            response=client.post('/generation-jobs',json={'description':'Gardens','book_type':'varied_activities'})
            self.assertEqual(response.status_code,202)
            self.assertEqual(submit.call_args.args[2]['book_type'],'varied_activities')
            submit.reset_mock()
            for kind in ('unknown',None,False,[]):
                response=client.post('/generation-jobs',json={'description':'Gardens','book_type':kind})
                self.assertEqual(response.status_code,400)
            submit.assert_not_called()
        with web._jobs_lock: web._jobs.clear()


if __name__=='__main__':
    unittest.main()
