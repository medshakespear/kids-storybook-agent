"""Blind text-only answer verification, with bounded repairs of faulty questions."""
from copy import deepcopy
import json

from core.activity_generator import ActivityGenerationError
from core.response_schemas import array, enum, integer, obj, text


def verify_question_answers(unit, config, label, *, ask):
    """Solve without the supplied key, repair mismatches, and verify again.

    This is independent model-based semantic review, not external fact checking.
    No images are sent. Repairs cannot change the passage or unaffected questions.
    """
    from core.reading_generator import bounded, validate_unit, unit_schema
    current = deepcopy(unit)
    solution_schema = obj({'solutions': array(obj({
        'number': integer(1, 5), 'answer': enum(['A','B','C','D','NONE','AMBIGUOUS']),
        'reason': text(110, 'Brief passage-based explanation of the selected option or defect.')
    }), 5, 5)})

    def validate_solutions(raw):
        """Require one explicitly numbered independent solution for every question."""
        solutions = raw.get('solutions') if isinstance(raw, dict) else None
        if not isinstance(solutions, list) or len(solutions) != 5:
            raise ValueError('Return five numbered solutions')
        found = {}
        for solution in solutions:
            if not isinstance(solution, dict):
                raise ValueError('Each solution must be an object')
            number = solution.get('number')
            if type(number) is not int or number not in range(1,6) or number in found:
                raise ValueError('Solution numbers must be exactly 1-5, each once')
            if solution.get('answer') not in ('A','B','C','D','NONE','AMBIGUOUS'):
                raise ValueError('Select A-D, NONE or AMBIGUOUS')
            found[number] = dict(answer=solution['answer'], reason=bounded(solution.get('reason'),'Review reason',110))
        return found

    for attempt in range(3):
        # The proposed key, explanations and supporting quotations are deliberately
        # absent. Otherwise a reviewer can rationalize an unrelated selected choice.
        blind = {'paragraphs': current['paragraphs'], 'questions': [
            {'number': n, 'prompt': q['prompt'], 'options': q['options']}
            for n,q in enumerate(current['questions'],1)]}
        prompt = ('Solve these five reading questions using ONLY the passage and printed options. '
                  'No answer key is supplied. Select NONE when no option answers the question, and '
                  'AMBIGUOUS when two or more options are defensible. Never select a merely related '
                  'option or borrow the answer from another question. Return solutions with number, '
                  'answer and a brief reason of at most 110 characters (aim for 60-90). Do not invent missing options.\n'+json.dumps(blind))
        solutions = ask(prompt, validate_solutions, label+' blind answer verification', 2200,
                        response_schema=solution_schema)
        faults = {n: result for n,result in solutions.items()
                  if result['answer'] != current['questions'][n-1]['answer']}
        if not faults:
            for number, result in solutions.items():
                current['questions'][number-1]['explanation'] = result['reason']
            return validate_unit(current,config)
        if attempt == 2:
            numbers = ', '.join(str(n) for n in sorted(faults))
            raise ActivityGenerationError(f'{label}: answer verification still fails for questions {numbers}; PDF not published')
        retained = deepcopy(current)

        def validate_repairs(raw):
            """Freeze passage and unaffected questions while validating complete repairs."""
            repairs = raw.get('repairs') if isinstance(raw,dict) else None
            if not isinstance(repairs,list) or len(repairs) != len(faults):
                raise ValueError('Repair exactly the flagged question numbers')
            candidate, seen = deepcopy(retained), set()
            for repair in repairs:
                number = repair.get('number') if isinstance(repair,dict) else None
                if type(number) is not int or number not in faults or number in seen:
                    raise ValueError('Unknown or duplicate repaired question number')
                seen.add(number)
                candidate['questions'][number-1] = deepcopy(repair.get('question'))
            return validate_unit(candidate,config,retained=retained)

        repair_schema = obj({'repairs':array(obj({'number':integer(1,5),
                             'question':unit_schema()['properties']['questions']['items']}),len(faults),len(faults))})
        prompt = ('Repair ONLY these faulty comprehension questions: '+json.dumps(faults)+'. '
                  'Return repairs [{number,question}] containing complete question objects. Keep the '
                  'passage, title, illustration and every unaffected question unchanged. A selected '
                  'option must actually answer its own prompt and agree with its explanation. When '
                  'no correct choice exists, replace the faulty choice, not just the answer letter. '
                  'Retain plausible distractors and the grade skill mix. Copy real passage evidence. '
                  'Do not insert claims into the passage to justify a bad option.\n'+json.dumps(retained))
        current = ask(prompt,validate_repairs,label+' answer repair',3500,response_schema=repair_schema)
    raise AssertionError('Unreachable answer-review state')
