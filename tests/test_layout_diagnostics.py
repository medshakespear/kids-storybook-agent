"""Expose reproducible failed layouts without headers, credentials or public status payloads."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import webhook_server as web
from core.activity_generator import ActivityGenerationError
from core.creative_generator import ask_json,layout_contract,validate_design
from core.layout_diagnostics import build_layout_diagnostic
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class LayoutDiagnosticTests(unittest.TestCase):
    """Test replay payloads, actual exhaustion and authenticated diagnostic downloads."""

    def test_allowlisted_report_omits_credentials_paths_and_prompt_metadata(self):
        """Only generated worksheet content and necessary print settings may be exported."""
        page=authored_page();page['_recovery_config']={'minimum_text_pt':12,'api_key':'private-value','headers':{'Authorization':'private-value'}}
        page['images'][0].update(path='/private/path',api_key='private-value')
        page['prompt']='Private transport metadata'
        report=build_layout_diagnostic(page,'Activity design 1',12,8000,[{'error':'Too small'}])
        value=json.dumps(report)
        for secret in ('private-value','/private/path','Private transport metadata','Authorization'):
            self.assertNotIn(secret,value)
        self.assertEqual(report['page']['html'],page['html'])
        self.assertEqual(report['page']['exercise'],page['exercise'])
        self.assertEqual(report['config'],{'minimum_text_pt':12})

    def test_exhausted_print_fit_retains_original_page_and_candidate_errors(self):
        """A genuinely impossible page yields replay data instead of hiding its failure."""
        config=dict(load_grade_config()['3rd-4th'],purposeful_activity_layout=False,
            stimulus_limit=8,context_caption_limit=24,items_per_page=2)
        page=authored_page();page['html']+='<div style="height:280mm;border:0.4mm solid #167E80"></div>'
        original=deepcopy(page);api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        brief={'render_mode':'authored','mechanic':page['exercise']['mechanic']}
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'), \
             patch.dict('os.environ',{'DESIGN_VALIDATION_ATTEMPTS':'3'}):
            with self.assertRaises(ActivityGenerationError) as caught:
                ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                    lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                        expected_title='Impossible Layout',require_coherent=True),
                    'Activity design 1',response_schema=design_schema(brief,config))
        report=caught.exception.layout_diagnostic
        self.assertEqual(report['title'],'Impossible Layout')
        for key,value in original['exercise'].items():
            self.assertEqual(report['page']['exercise'][key],value)
        self.assertEqual(report['page']['exercise'].get('captions',[]),[])
        self.assertEqual(report['page']['exercise'].get('stimuli',[]),[])
        self.assertIn('height:280mm',report['page']['html'])
        self.assertTrue(report['recovery_attempts'])
        self.assertEqual(report['config']['visual_area_mm2'],8000)
        self.assertEqual(page,original)

    def test_failed_job_diagnostic_is_downloadable_with_auth_and_excluded_from_polling(self):
        """The web form gets a link, while the full replay is available only through its route."""
        client=web.app.test_client();job_id='a'*32
        report=build_layout_diagnostic(authored_page(),'Activity design 1',12,8000,[])
        error=ActivityGenerationError('Cannot fit');error.layout_diagnostic=report
        with patch.dict(web._jobs,{job_id:{'status':'queued','updated':0}},clear=True), \
             patch.dict('os.environ',{'WEBHOOK_API_KEY':'fixture-key'}), \
             patch.object(web,'run_generation',side_effect=error):
            web.perform_job(job_id,{'link':'','description':'space'})
            self.assertEqual(client.get('/generation-jobs/'+job_id+'/diagnostics').status_code,401)
            headers={'X-API-Key':'fixture-key'}
            status=client.get('/generation-jobs/'+job_id,headers=headers)
            self.assertEqual(status.json['status'],'failed')
            self.assertNotIn('_layout_diagnostic',status.json)
            response=client.get(status.json['diagnostic_url'],headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json,report)
            self.assertIn('attachment',response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(client.get('/generation-jobs/missing/diagnostics',headers=headers).status_code,404)
        with patch.object(web,'list_books',return_value=[]):
            self.assertIn('Download layout diagnostic',client.get('/books').get_data(as_text=True))
