"""Replay a real failed card layout and retain content auditing for its incorrect key."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.calculation_attachment import detach_conceptual_calculation,label_matching_text
from core.card_layout import source_card_layouts
from core.creative_generator import ask_json,layout_contract,validate_design
from core.exercise_quality import proofread_pack
from core.pipeline import load_grade_config
from core.response_schemas import design_schema


class PairedClaimCardTests(unittest.TestCase):
    """Check the uploaded failure with actual print geometry and bounded native generation."""

    def fixture(self,band):
        """Load the real generated worksheet without transport metadata or credentials."""
        raw=json.loads((Path(__file__).parent/'fixtures'/'paired_claim_cards.json').read_text())
        config=dict(load_grade_config()[band],purposeful_activity_layout=False,
            stimulus_limit=8,context_caption_limit=24,table_caption_limit=36,items_per_page=2)
        return raw['page'],config,raw['title']

    def test_uploaded_layout_fits_after_one_provider_response_both_grades(self):
        """Keep card columns, labels, both questions and all four writing heights intact."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page,config,title=self.fixture(band);original=deepcopy(page)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[
                    SimpleNamespace(message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                brief={'render_mode':'authored','mechanic':'matching'}
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                        lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                            expected_title=title,require_coherent=True,brief=brief),
                        'Activity design 6',response_schema=design_schema(brief,config))
                self.assertEqual(api.chat.completions.create.call_count,1)
                for field in ('stimuli','captions','directions','goal'):
                    self.assertEqual(result['exercise'][field],original['exercise'][field])
                for before,after in zip(original['exercise']['questions'],result['exercise']['questions']):
                    for field in ('id','prompt','answer','space_mm'):
                        self.assertEqual(after[field],before[field])
                self.assertNotIn('calculation',result['exercise']['questions'][0])
                self.assertEqual(result['calculations'],[])
                self.assertEqual(result['html'].count('height:25mm'),2)
                self.assertIn('height: 18mm',result['html']);self.assertIn('height: 22mm',result['html'])
                self.assertEqual(result['images'],original['images'])
                for card in original['exercise']['stimuli']:
                    self.assertIn(card['text'],result['html'])
                self.assertEqual(page,original)

    def test_recovery_never_discards_unbound_text_extra_tasks_or_oversized_workspace(self):
        """Unknown wording or impossible blank panels cannot be hidden by the new card solver."""
        for modification in ('<p>Write a new unkeyed report.</p>',
                             '<div style="height:280mm;border:1mm solid #167E80"></div>'):
            page,config,title=self.fixture('3rd-4th')
            page['html']+=modification;page['_recovery_config']=config;page['_recovery_title']=title
            candidates=list(source_card_layouts(page,12,8000))
            if modification.startswith('<p>'):
                self.assertEqual(candidates,[])
            else:
                self.assertTrue(candidates)
                for candidate in candidates:
                    self.assertIn('height:280mm',candidate['html'])
                    with self.assertRaisesRegex(ValueError,'Design overflow'):
                        validate_design(candidate,12,quality=config,expected_title=title,require_coherent=True)

    def test_label_ranges_are_not_arithmetic_but_real_matching_math_remains_checked(self):
        """Strip stray label-range calculations only from clearly label-only matching tasks."""
        page,_,_=self.fixture('3rd-4th');question=page['exercise']['questions'][0]
        detach_conceptual_calculation(question)
        self.assertNotIn('calculation',question)
        for prompt in ('Match each claim to source numbers (1-4), then calculate 8-3.',
                       'Match each measurement (1-4) to its result.',
                       'Match cards for numbers (1-4) and explain how many remain.',
                       'Match each claim to source numbers (1-4), then find the average.',
                       'Match each claim to source numbers (1-4), then compare the weights.',
                       'Calculate 4-3. Match the result to a source card.'):
            self.assertIsNone(label_matching_text(prompt))
            q=dict(prompt=prompt,answer='5',calculation={'expression':'8-3','answer':'5'})
            detach_conceptual_calculation(q);self.assertIn('calculation',q)

    def test_print_fit_does_not_bypass_semantic_matching_audit(self):
        """The known incorrect key must reach independent content review, then be repaired and rechecked."""
        page,config,title=self.fixture('3rd-4th');page['_recovery_config']=config;page['_recovery_title']=title
        result=validate_design(next(source_card_layouts(page,12,8000)),12,quality=config,
            expected_title=title,require_coherent=True)
        result['title']=title
        correct='Claim A matches Source 2; Claim B matches Source 1; Claim C matches Source 3; Claim D matches Source 4.'
        calls=[]

        def audit(prompt,validate,label,tokens):
            """Model the independent semantic verdict, not a Python inference of science meaning."""
            calls.append(prompt)
            self.assertIn('first independently pair the printed claims/cards',prompt)
            self.assertIn('Source 2',prompt);self.assertIn('Claim A',prompt)
            return validate({'pages':[{'page_number':1,'issues':
                ['Correct the matching key: A-2, B-1, C-3, D-4.'] if len(calls)==1 else []}]})

        def repair(number,previous,issues):
            """Change the disputed key only, keeping all printed tasks and retained dimensions."""
            replacement={'html':previous['source_layout'],'images':deepcopy(previous['images']),
                         'exercise':deepcopy(previous['exercise'])}
            replacement['exercise']['questions'][0]['answer']=correct
            repaired=validate_design(replacement,12,quality=config,expected_title=title,require_coherent=True)
            repaired['title']=title
            self.assertEqual(repaired['html'],previous['html'])
            return repaired

        pack={'grade_band':'3rd-4th','pages':[result]}
        proofread_pack(pack,audit,repair)
        self.assertEqual(len(calls),2)
        self.assertEqual(pack['pages'][0]['exercise']['questions'][0]['answer'],correct)
        self.assertEqual(pack['content_checks']['status'],'passed')
