"""Scope and grade checks for the simple written-exercise workbook option."""
import ast
import re


def exercise_guidance(grade_band: str) -> str:
    """Give the planner, author and content repair the same non-craft requirements."""
    math=('Use two/three-digit addition and subtraction, multiplication facts or two-digit by '
          'one-digit multiplication, exact division and short one/two-step word problems. '
          'Avoid single-digit addition/subtraction as a standalone exercise.' if grade_band=='3rd-4th' else
          'Use multi-step whole-number problems, multi-digit multiplication/division, simple '
          'fractions, decimals, percentages or meaningful elapsed-time/data problems. State '
          'rounding explicitly when needed. Avoid standalone addition/subtraction of small '
          'numbers and basic multiplication-fact drills.')
    return ('SIMPLE WRITTEN EXERCISES ONLY. Create a useful, easy-to-follow student workbook. '
        'Vary short reading questions, vocabulary with context, text matching, true/false with '
        'a correction, ordering supplied sentences, fact/opinion with evidence, reading a small '
        'table and age-appropriate word problems. Use at least five different student actions. '
        'Ask one clear action per question, normally one/two sentences to answer. All needed '
        'information must be printed, with one unambiguous answer or a concrete open-answer criterion. '
        'No drawing, templates, tracing, coloring, crafting, cutting, folding, mirroring, design '
        'projects, construction or hands-on activities. No geometric puzzles or image-dependent '
        'answers. Illustrations are context only; never ask students to count, copy or measure '
        'their contents. The title/theme may mention a craft, but the student work must remain '
        'reading, writing or mathematics. Keep language accessible for the selected grade; '
        'simple directions do not mean below-grade mathematics. '+math+' '
        'For every numeric problem include one calculation matching the printed problem and '
        'its exact answer. Independently solve the problem before writing the answer key. '
        'Comparison questions must have supporting details in EACH named source; do not invent '
        'shared traditions, objects or actions. A key must not add facts absent from the sources. '
        'Sequence answers must use the same printed card letters. Classification response cells '
        'and reasoning cells must be blank; do not reveal the answers in captions or tables. '
        'Prefer clear short titles, calm colorful headings, one contextual picture and full-width '
        'answer space. No technical instructions such as 50mm writing space in student wording. '
        'Keep cultural events distinct and describe beliefs as traditions, not universal facts. '
        'No invented safety ratings, guarantees or quotations presented as authentic. ')


def check_simple_activity(exercise: dict, *, planning: bool = False) -> None:
    """Reject disallowed student actions while allowing reading about art and ordinary idioms."""
    if not isinstance(exercise,dict):return
    if exercise.get('render_mode')!='authored':
        raise ValueError('Simple workbook activities must be authored reading, writing or math exercises')
    mechanic=str(exercise.get('mechanic','')).replace('_',' ')
    if re.search(r'\b(?:draw\w*|craft\w*|sketch\w*|trac(?:e|ing)|colou?ring|origami|symmetr\w*|design|maze|cutouts?)\b',mechanic,re.I):
        raise ValueError('Simple workbook: replace the drawing/craft/design mechanic with a written exercise')
    questions=exercise.get('questions',[])
    texts=([exercise.get('learning_goal',''),exercise.get('activity_concept','')] if planning else
           [exercise.get('directions','')]+[q.get('prompt','') for q in (questions if isinstance(questions,list) else []) if isinstance(q,dict)])
    verbs=r'(?:draw(?!\s+(?:a|the)\s+conclusion)|sketch|trace|colou?r|paint|cut|fold|glue|assemble|decorate|craft|build|construct|carve|mirror|design)'
    for text in texts:
        text=str(text)
        action=re.search(r'(?:^|[.!?:;]\s*|\b(?:then|and)\s+)(?:(?:please|carefully|neatly|accurately|directly|now)\s+)*'+verbs+r'\b',text,re.I)
        if planning:
            action=action or re.search(r'\b(?:students?|children|learners?)\s+(?:will\s+)?'+verbs+r'\b',text,re.I)
        indirect=re.search(r'\b(?:by|to)\s+(?:drawing|sketching|tracing|coloring|colouring|cutting|folding|crafting|mirroring)\b',text,re.I)
        if action or indirect or re.search(r'\b(?:templates?|blank (?:right|left) half|mirror image|drawing (?:box|area))\b',text,re.I):
            raise ValueError('Simple workbook: replace drawing, crafting or template instructions with a clear reading, writing or math question')
        if re.search(r'\b\d+(?:\.\d+)?\s*mm\s+(?:writing|response|answer)\s+space\b',text,re.I):
            raise ValueError('Keep response-space measurements in space_mm, not in the student question')


def check_grade_math(question: dict, exercise: dict, grade_band: str) -> None:
    """Reject clearly below-band arithmetic without inferring operations from source prose."""
    calculation=question.get('calculation')
    if not isinstance(calculation,dict) or not isinstance(calculation.get('expression'),str):return
    from core.exercise_quality import normalize_calculation
    expression=normalize_calculation(calculation['expression']);root=ast.parse(expression,mode='eval')
    operations=[n for n in ast.walk(root) if isinstance(n,ast.BinOp)]
    values=[n.value for n in ast.walk(root) if isinstance(n,ast.Constant) and type(n.value) in {int,float}]
    if not operations or not values:return
    clocks=' '.join(str(s.get('text','')) for s in exercise.get('stimuli',[]) if isinstance(s,dict))
    timetable=bool(re.search(r'\b\d{1,2}:\d{2}\b',clocks) and
                   re.search(r'\b(?:time|hours?|minutes?|start|end)\b',question.get('prompt',''),re.I))
    if grade_band=='3rd-4th':
        weak=(all(isinstance(op.op,(ast.Add,ast.Sub)) for op in operations) and max(abs(v) for v in values)<20 and not timetable)
    elif grade_band=='5th-6th':
        fractional=any(type(v) is float and v!=int(v) for v in values)
        if len(operations)==1:
            operation=operations[0]
            if isinstance(operation.op,ast.Div) and len(values)==2 and 0<abs(values[0])<abs(values[1]):fractional=True
            if isinstance(operation.op,(ast.Add,ast.Sub)):weak=not fractional and max(abs(v) for v in values)<1000
            else:weak=not fractional and max(abs(v) for v in values)<=100 and min(abs(v) for v in values)<=10
        else:weak=(all(isinstance(op.op,(ast.Add,ast.Sub)) for op in operations) and max(abs(v) for v in values)<20 and not fractional)
    else:return
    if weak:
        raise ValueError(f'Question {question.get("id")}: arithmetic is below {grade_band} level; replace this problem and its calculation/key together. Use grade-appropriate multi-digit or multi-step work; upper grades may use fractions or decimals.')
