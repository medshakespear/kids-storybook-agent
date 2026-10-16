"""Prevent the skull half-completion and tiny banner failures reviewed in the generated PDF."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from PIL import Image
from weasyprint import HTML
from core.blank_templates import template_png
from core.work_templates import required_template,prepare_work_template,check_template_geometry
from core.creative_generator import ask_json,layout_contract,validate_design,generate_creative_images
from core.creative_layout import fragment,document_markup,data_only_fetcher,check_document
from core.response_schemas import design_schema
from tests.test_student_workbook import workbook_config
from tests.test_reading_bindings import plain_text


def work_page(kind):
    """Reproduce the actual student instructions using representative provider HTML and art briefs."""
    if kind=='skull':
        directions='Decorate the skull outline with symmetrical patterns, then write about your artistic choices below.'
        prompts=['Complete the uncolored half of the skull by drawing matching decorative patterns, swirls, and flowers so that both sides are perfectly symmetrical.',
                 'Write two to three sentences explaining the traditional symbols or shapes you chose to include in your sugar skull design and what they represent.']
        answers=['Accept original symmetrical patterns matching both sides of the skull.',
                 'Accept thoughtful student explanations connecting design choices to cultural remembrance themes.']
        art='A fully decorated colorful sugar skull with symmetric floral designs on an orange background.'
        captions=[]
    else:
        directions='Design a traditional decorative paper banner motif by planning your symmetrical cutouts and geometric shapes.'
        prompts=['In the space below, draw your completed repeating cutout motif for the banner. Include fold lines and shaded areas showing where snips will be made.',
                 'Identify and name two distinct geometric shapes (e.g., triangle, diamond) that form the repeating units of your architectural banner design.']
        answers=['Accept original symmetrical cutout motifs with clear snip markings and fold lines.',
                 "Accept valid geometric shapes used in the student's design, such as triangles, diamonds, squares, or semicircles."]
        art='A tiny white paper template with an arch cutout, on a violet background. Papel picado.'
        captions=[{'id':'workspace_label','text':'Banner Template Workspace'},
                  {'id':'workspace_note','text':'Sketch your symmetrical repeating cutout pattern inside the template box above.'}]
    html='<h1 data-content="title" style="font-size:16pt;color:#B35716;margin:0 0 1mm"></h1><p data-content="directions"></p>'
    html+='<div style="width:85mm;padding:3mm"><img data-asset="work_art" style="width:80mm;height:85mm"/></div>'
    html+=''.join('<p data-content="caption_'+c['id']+'"></p>' for c in captions)
    html+='<div data-content="question_1"></div><div data-content="question_2"></div>'
    return {'html':html,'images':[{'id':'work_art','prompt':art}], 'exercise':{
        'render_mode':'authored','mechanic':'symmetrical design' if kind=='skull' else 'banner design',
        'goal':'Plan and explain an original symmetrical design.','directions':directions,'captions':captions,
        'questions':[dict(id=str(i+1),prompt=p,answer=a,space_mm=50 if i==0 else 35) for i,(p,a) in enumerate(zip(prompts,answers))]}}


class WorkTemplateTests(unittest.TestCase):
    """Use actual PNGs and measured A4 layout, without any live AI or image checker."""

    def ask(self,raw,band):
        """Use the native retry flow; a trustworthy local template must need only one response."""
        api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
        config=workbook_config(band)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
             patch('core.creative_generator.time.sleep'):
            page=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                lambda value:validate_design(value,config['student_font_pt'],quality=config,
                    expected_title='Sugar Skull Artistry' if 'skull' in raw['images'][0]['prompt'] else 'Papel Picado Design',require_coherent=True),
                'Activity design 5',response_schema=design_schema({'render_mode':'authored','mechanic':raw['exercise']['mechanic']},config))
        return page,api

    def test_skull_and_banner_failures_finish_from_one_response_in_both_bands(self):
        """The decorative image is replaced only for the actual work asset; every answer area survives."""
        for kind in ('skull','banner'):
            for band in ('3rd-4th','5th-6th'):
                with self.subTest(kind=kind,band=band):
                    raw=work_page(kind);before=deepcopy(raw);page,api=self.ask(raw,band)
                    self.assertEqual(api.chat.completions.create.call_count,1)
                    self.assertEqual(raw,before)
                    template='skull_symmetry' if kind=='skull' else 'banner_plan'
                    self.assertEqual(page['images'][0]['local_template'],template)
                    self.assertEqual(page['images'][0]['prompt'],before['images'][0]['prompt'])
                    self.assertEqual([q['answer'] for q in page['exercise']['questions']],
                                     [q['answer'] for q in before['exercise']['questions']])
                    self.assertEqual(page['html'].count('height:50mm'),2)
                    text=plain_text(page['html'])
                    if kind=='skull':self.assertIn('blank right half',text);self.assertIn('Draw directly on the template.',text)
                    else:self.assertNotIn('box above',text);self.assertIn('large blank banner template',text)
                    d=HTML(string=document_markup([fragment(page,True)],workbook_config(band)['student_font_pt']),url_fetcher=data_only_fetcher).render()
                    check_document(d,1);check_template_geometry(d)
                    self.assertIn('data-work-template="'+template+'"',fragment(page,True))

    def test_right_half_has_no_reference_patterns_and_banner_has_real_blank_space(self):
        """Reference motifs remain entirely on the left; banner interior is white except its fold guide."""
        skull=Image.open(io.BytesIO(template_png('skull_symmetry'))).convert('RGB')
        # The forehead flower appears on the left, never on the matching right area.
        left=skull.crop((550,170,750,370));right=skull.crop((1050,170,1250,370))
        dark=sum(left.convert('L').histogram()[:150])
        self.assertLess(dark,20000)
        self.assertGreater(dark,100)
        self.assertEqual(right.getextrema(),((255,255),)*3)
        banner=Image.open(io.BytesIO(template_png('banner_plan')))
        self.assertEqual(banner.crop((150,150,850,860)).getextrema(),((255,255),)*3)
        self.assertEqual(banner.crop((950,150,1650,860)).getextrema(),((255,255),)*3)
        for subject in ('butterfly','leaf','heart','pumpkin'):
            image=Image.open(io.BytesIO(template_png(subject+'_symmetry')))
            self.assertEqual(image.size,(1800,1320))
        with self.assertRaises(ValueError):template_png('unsupported')

    def test_template_selection_is_specific_and_keeps_decorative_art(self):
        """Observation and open art tasks do not gain a half-finished drawing or lose meaningful scenes."""
        self.assertIsNone(required_template({'directions':'Observe the symmetry of the decorated skull.','questions':[]}))
        self.assertIsNone(required_template({'directions':'Draw your own symmetrical skull design.','questions':[]}))
        self.assertIsNone(required_template({'directions':'Design a campaign banner slogan. Explain your word choices.','questions':[]}))
        p=work_page('skull');p['images'].append({'id':'festival','prompt':'Families remembering loved ones in a decorated room.'})
        config=workbook_config('3rd-4th');prepare_work_template(p,config)
        self.assertNotIn('local_template',p['images'][1]);self.assertEqual(p['images'][0]['local_template'],'skull_symmetry')
        snapshot=deepcopy(p);prepare_work_template(p,config);self.assertEqual(p,snapshot)
        p=work_page('skull');p['images']=[{'id':'festival','prompt':'Families sharing memories.'}]
        prepare_work_template(p,config)
        self.assertEqual(len(p['images']),2);self.assertNotIn('local_template',p['images'][0])
        self.assertIn('local_template',p['images'][1])
        p=work_page('banner');before=deepcopy(p);prepare_work_template(p,{})
        self.assertEqual(p,before)

    def test_templates_bypass_cloudflare_and_use_identical_preview_and_final_graphics(self):
        """Only the decorative cover is requested from AI; student templates are local valid PNGs."""
        from core.creative_generator import strip_creative_art
        page,_=self.ask(work_page('skull'),'3rd-4th')
        cover={'images':[{'id':'cover','prompt':'A festive room.'}]}
        pack={'cover':cover,'pages':[page],'art_direction':'Orange and teal','resource_type':'activity_pack','character_description':''}
        with tempfile.TemporaryDirectory() as folder:
            cover_path=Path(folder)/'cover.png';Image.new('RGB',(512,512),'orange').save(cover_path)
            with patch('core.creative_generator.generate_images',return_value=[cover_path]) as provider:
                generate_creative_images(pack,{},folder)
            self.assertEqual(len(provider.call_args.args[0]['pages']),1)
            local=page['images'][0]
            self.assertEqual(Path(local['path']).read_bytes(),template_png('skull_symmetry'))
            self.assertEqual(fragment(page,True),fragment(page,False))
            self.assertEqual(pack['image_review']['status'],'disabled')
            strip_creative_art(pack);self.assertNotIn('path',local)

    def test_a_small_parent_cannot_publish_a_tiny_template(self):
        """Measured size is enforced even when the image advertises a large CSS width."""
        page,_=self.ask(work_page('banner'),'3rd-4th')
        page['html']='<div style="width:45mm">'+page['html']+'</div>'
        d=HTML(string=document_markup([fragment(page,True)],12),url_fetcher=data_only_fetcher).render()
        with self.assertRaisesRegex(ValueError,'template is too small'):check_template_geometry(d)
