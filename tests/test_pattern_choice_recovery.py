"""Derive valid pattern options while preserving the original sequence and computed key."""
from copy import deepcopy
import unittest

from core.creative_generator import validate_design
from core.pattern_recovery import recover_pattern_choices
from core.pipeline import load_grade_config
from core.task_visuals import build_visual,answer_text,symbol
from tests.coherent_fixtures import exact_page,visual_examples


class PatternChoiceRecoveryTests(unittest.TestCase):
    """Check exact puzzle correction with real SVG generation and page measurement."""

    def validate(self,spec):
        """Compile and preflight a first/second-grade computed pattern page."""
        return validate_design(exact_page(spec),14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_duplicate_correct_or_wrong_choices_are_repaired(self):
        """Always produce exactly one next-symbol answer and at least one distinct distractor."""
        base=visual_examples()[0]
        correct=base['motif'][-1];wrong=base['motif'][0]
        for choices in [[correct,correct],[wrong,wrong],[correct,wrong,wrong],[wrong,correct,correct]]:
            spec=deepcopy(base);spec['choices']=deepcopy(choices);original=deepcopy(spec)
            result=self.validate(spec);repaired=result['exercise']['visual']
            options=[symbol(v) for v in repaired['choices']]
            self.assertEqual(options.count(symbol(correct)),1)
            self.assertEqual(len({tuple(sorted(v.items())) for v in options}),len(options))
            self.assertTrue(2<=len(options)<=4)
            self.assertEqual(repaired['motif'],original['motif'])
            _,key=build_visual(repaired)
            self.assertEqual(answer_text(result),key)
            self.assertEqual(spec,original)

    def test_four_wrong_choices_get_correct_option_without_expanding_page(self):
        """Replace one distractor while retaining four distinct lettered choices."""
        spec=deepcopy(visual_examples()[0])
        spec['choices']=[{'shape':shape,'color':'teal','size':'large'} for shape in ['circle','square','triangle','star']]
        repaired=recover_pattern_choices(spec)
        self.assertEqual(len(repaired['choices']),4)
        self.assertEqual(repaired['choices'][:3],spec['choices'][:3])
        self.assertEqual(repaired['choices'][-1],symbol(spec['motif'][-1]))
        self.validate(repaired)

    def test_valid_options_preserve_order_and_key(self):
        """Do not reshuffle authored choices or move a correct answer when they are valid."""
        spec=visual_examples()[0]
        self.assertEqual(recover_pattern_choices(spec),spec)
        self.assertEqual(build_visual(spec),build_visual(recover_pattern_choices(spec)))

    def test_invalid_motif_symbols_or_option_count_are_not_invented(self):
        """Recovery cannot turn an unsupported puzzle into unrelated stock shapes."""
        base=visual_examples()[0]
        cases=[]
        bad=deepcopy(base);bad['motif']=[bad['motif'][0]]*2;cases.append(bad)
        bad=deepcopy(base);bad['choices'][0]['shape']='corn';cases.append(bad)
        bad=deepcopy(base);bad['choices']*=2;cases.append(bad)
        for spec in cases:
            with self.subTest(spec=spec):
                self.assertEqual(recover_pattern_choices(spec),spec)
                with self.assertRaises(ValueError):
                    self.validate(spec)


if __name__=='__main__':
    unittest.main()
