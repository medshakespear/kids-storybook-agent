"""Review small groups of activities with an independent solution for every task."""
import json
from copy import deepcopy

from core.task_visuals import answer_text
from core.workbook_checks import classification_leaks,printed_words,unsupported_fact_claims
from core.contextual_tasks import contextual_task_issues
from core.workbook_tasks import task_coverage_issues


def semantic_review_guidance() -> str:
    """Share meaning checks between blind solving and comparison with authored keys."""
    return ('Track the meaning and location of each quantity: handed-out minus returned means '
        'items still with recipients, not items in storage. Usable returns added back to stock '
        'increase stock; require starting inventory and an explicit return/restocking condition. '
        'For sentence ordering, require printed time/dependency cues establishing ONE order; '
        'otherwise accept all defensible orders or re-author the source, not just the key. '
        'In bullying scenarios, seek trusted adult help promptly. Checking in, speaking up, '
        'collecting evidence or finding witnesses must never be prerequisites for reporting; '
        'optional peer support is only when safe. Do not treat bullying as an equal-power '
        'disagreement requiring reconciliation. Raw class totals cannot prove per-student '
        'participation, age effects or causation without denominators/comparable conditions. '
        'State only the observed count comparison. Avoid redundant inclusion reflections and '
        'unrelated math tacked onto matching questions; keep each task focused. '
        'For classification, distinguish supplied source statements from student answer cells. '
        'Unselected Fact/Opinion choices, empty checkboxes and category column headings are '
        'legitimate scaffolds, not leaked answers. A selected category or prefilled explanation '
        'in a student response cell is a leak. Repair only the identified response cell, preserving '
        'its writing area, source evidence, question and verified final-key solution. '
        'Audit ALL student actions in directions, tables and matching lists, not only numbered questions. '
        'If directions require four classifications, independently solve all four and ensure the final '
        'key includes every row, even if only two follow-up questions are registered. One question '
        'can own the full table task with concise row-by-row answers. Never silently omit rows. '
        'Every numbered matching term needs its printed label and a separate readable entry. '
        'Distinguish a count of items from points earned: the question, operation, unit and key '
        'must ask/answer the same quantity. Catch repeated-word item labels and keep corrections '
        'consistent across sources, table cells, prompts and key without changing quantities. '
        'Vague invented historical/cultural scenes must be labeled fictional; do not present '
        'invented village celebrations as established history. Use a real supported context instead '
        'if historical facts are the learning goal. ')


def blind_pages(pages: list[dict]) -> list[dict]:
    """Remove all authored answers/calculations before asking an independent solver."""
    result=[]
    for page in pages:
        exercise={k:deepcopy(v) for k,v in page['exercise'].items()
                  if k in {'render_mode','mechanic','directions','passage','captions','stimuli'}}
        exercise['questions']=[{'id':q['id'],'prompt':q['prompt']} for q in page['exercise']['questions']]
        result.append({'page_number':page['page_number'],'title':page['title'],
                       'exercise':exercise,'student_content':page['student_content']})
    return result


def independent_schema(pages: list[dict]) -> dict:
    """Ask for solvability and an independent answer without a key-correctness guess."""
    from core.response_schemas import obj,array,text,integer
    check=obj({'id':text(3),'source_support':{'type':'boolean'},'skill_match':{'type':'boolean'},
        'grade_match':{'type':'boolean'},'solution':text(650),'reason':text(650)})
    row=obj({'page_number':integer(1,100),'source_accuracy':{'type':'boolean'},
        'no_answer_leak':{'type':'boolean'},'reason':text(650),
        'question_checks':array(check,1,2),'issues':array(text(650),0,6)})
    return obj({'pages':array(row,len(pages),len(pages))})


def validate_independent(raw: dict, pages: list[dict]) -> dict:
    """Retain blind solutions and make unsupported/weak tasks mandatory correction issues."""
    adapted=deepcopy(raw)
    if not isinstance(adapted,dict) or not isinstance(adapted.get('pages'),list):
        raise ValueError('Independent review must return pages')
    for row in adapted['pages']:
        if not isinstance(row,dict):raise ValueError('Independent review needs page records')
        checks=row.get('question_checks')
        if not isinstance(checks,list):raise ValueError('Independent review needs every question check')
        for check in checks:
            if not isinstance(check,dict) or type(check.get('grade_match')) is not bool:
                raise ValueError('Independent review needs an explicit grade_match verdict')
            check['answer_correct']=True  # No authored key is present in this phase.
    issues=validate_review(adapted,pages)
    for row in adapted['pages']:
        for check in row['question_checks']:
            if not check['grade_match']:issues[row['page_number']].append(f'Question {check["id"]}: grade mismatch: {check["reason"]}')
            check.pop('answer_correct',None)
    return {'pages':adapted['pages'],'required_issues':issues}


def review_schema(pages: list[dict]) -> dict:
    """Require explicit question checks instead of an unexplained empty issue list."""
    from core.response_schemas import obj,array,text,integer
    check=obj({'id':text(3),'source_support':{'type':'boolean'},'skill_match':{'type':'boolean'},
        'answer_correct':{'type':'boolean'},'solution':text(650),'reason':text(650)})
    row=obj({'page_number':integer(1,100),'source_accuracy':{'type':'boolean'},
        'no_answer_leak':{'type':'boolean'},'reason':text(650),
        'question_checks':array(check,1,2),'issues':array(text(650),0,6)})
    return obj({'pages':array(row,len(pages),len(pages))})


def validate_review(raw: dict, pages: list[dict]) -> dict:
    """Require every page/question and turn any negative verdict into a repair issue."""
    rows=raw.get('pages') if isinstance(raw,dict) else None
    if not isinstance(rows,list) or len(rows)!=len(pages):
        raise ValueError('Content review must check every supplied activity exactly once')
    expected={p['page_number']:p for p in pages};result={}
    for row in rows:
        if not isinstance(row,dict) or type(row.get('page_number')) is not int:
            raise ValueError('Content review needs explicit activity numbers')
        number=row['page_number']
        if number not in expected or number in result: raise ValueError('Unexpected or repeated activity review')
        reason=row.get('reason');issues=row.get('issues')
        if not isinstance(reason,str) or not reason.strip() or not isinstance(issues,list) or any(not isinstance(i,str) or not i.strip() for i in issues):
            raise ValueError('Content review needs a concrete reason and an issues list')
        issues=list(issues)
        for field in ('source_accuracy','no_answer_leak'):
            if type(row.get(field)) is not bool: raise ValueError('Content review verdicts must be true or false')
            if not row[field]: issues.append(field+': '+reason)
        checks=row.get('question_checks');questions={q['id'] for q in expected[number]['exercise']['questions']}
        if not isinstance(checks,list) or len(checks)!=len(questions):
            raise ValueError('Independently solve every printed question exactly once')
        seen=set()
        for check in checks:
            if not isinstance(check,dict) or check.get('id') not in questions or check['id'] in seen:
                raise ValueError('Review question IDs must match the printed tasks')
            seen.add(check['id'])
            if any(not isinstance(check.get(k),str) or not check[k].strip() for k in ('solution','reason')):
                raise ValueError('Each question review needs its independent solution and reasoning')
            for flag in ('source_support','skill_match','answer_correct'):
                if type(check.get(flag)) is not bool: raise ValueError('Question verdicts must be true or false')
                if not check[flag]: issues.append(f'Question {check["id"]}: {flag}: {check["reason"]}')
        result[number]=list(dict.fromkeys(issues))
    return result


def review_varied_pack(pack: dict, ask, repair, batch_size: int = 3) -> None:
    """Solve contextual activities in bounded batches; repair affected pages once."""
    pack.pop('content_checks',None)
    pending=list(range(1,len(pack['pages'])+1))
    for attempt in range(2):
        failed={}
        for offset in range(0,len(pending),batch_size):
            pages=[]
            for n in pending[offset:offset+batch_size]:
                page=pack['pages'][n-1]
                pages.append({'page_number':n,'title':page['title'],'planned_intent':page.get('planned_intent'),
                    'exercise':page['exercise'],'student_content':printed_words(page['html']),'answer_key':answer_text(page)})
            public=blind_pages(pages)
            from core.simple_exercises import exercise_guidance
            independent_prompt=('Solve these student activities WITHOUT an authored answer key. '
                'Use ONLY their printed sources and questions. Never fill gaps from artwork or prior knowledge. '
                'If two sources do not support two shared details, flag source_support=false instead of inventing them. '
                'Vocabulary questions must refer to the actual objects and words in the passage. '
                'An exact quotation must support the ENTIRE statement, including each named location '
                'and date. A passage saying Tanzania does not prove a particular named park. '
                'Do not supply missing details from your own historical knowledge. '
                'Check that two questions require different details or reasoning, rather than asking '
                'the same purpose/contribution twice. Headings must not pre-answer the task. '
                'Historical sequencing needs printed dates or clear time relationships establishing '
                'the intended order, not an unstated guessed timeline. '
                'Solve all mathematics independently, checking operation, units and explicit rounding. '
                'Use the same printed card letters for sequences. For open questions give a concrete criterion. '
                'Check grade_match against this guidance: '+exercise_guidance(pack['grade_band'])+' '
                'Check source_accuracy and whether the source/text table gives away student answers. '
                'Flag unsupported safety guarantees, false science, unattributed fictional quotes, '
                'or cultural generalizations. Sources labeled fictional still need internally consistent information. '
                'Invented arithmetic scenarios about a real historical person must be labeled fictional '
                'or replaced with clearly fictional participants; never present practice kit/book counts '
                'as established biographical facts without supplied attribution. '
                'Do not inspect image pixels. Return page_number, source_accuracy, no_answer_leak, reason, '
                'issues and question_checks with id, source_support, skill_match, grade_match, solution, reason. '
                +semantic_review_guidance()+'Activities:\n'+json.dumps(public))
            independent=ask(independent_prompt,lambda raw:validate_independent(raw,public),
                'Workbook independent solutions',5000,response_schema=independent_schema(public))
            prompt=('Compare the existing answer keys with these independently obtained solutions and '
                'the actual printed sources. Do not assume the authored key is correct. Check EVERY clause '
                'of every answer, not just its numeric value. An answer must not invent shared traditions, '
                'objects, locations, events or explanations absent from the source. '
                'Check exact meanings: developing uses FOR crops does not mean creating those crops. If the source is insufficient, '
                'repair the question/source together; do not invent a plausible answer. A numeric calculation '
                'must solve the printed word problem. Use printed card letters in sequence keys. '
                'A fact/opinion reasoning column must not reveal the requested classification. '
                'Flag missing evidence and mismatched tasks. Do not require one wording for valid open answers. '
                'This is text review; do not inspect AI image pixels. Return one page/question verdict each '
                'with source_accuracy, no_answer_leak, source_support, skill_match and answer_correct. '
                'Include a concrete independent solution and reason. Preserve response space. '
                +semantic_review_guidance()+'Independent solutions:\n'+json.dumps(independent['pages'])+'\nActivities:\n'+json.dumps(pages))
            verdict=ask(prompt,lambda raw:validate_review(raw,pages),'Workbook content review',
                5000,response_schema=review_schema(pages))
            for page in pages:
                n=page['page_number']
                issues=(verdict[n]+independent['required_issues'][n]+classification_leaks(pack['pages'][n-1])
                        +unsupported_fact_claims(pack['pages'][n-1])+contextual_task_issues(pack['pages'][n-1])
                        +task_coverage_issues(pack['pages'][n-1]))
                if issues:failed[n]=list(dict.fromkeys(issues))
        if not failed:
            pack['content_checks']={'status':'passed','pages':len(pack['pages']),'repair_rounds':attempt,
                'method':'blind_solutions_then_source_and_answer_comparison'}
            return
        if attempt:
            raise ValueError('Workbook content still needs correction: '+'; '.join(
                f'Activity {n}: '+ '; '.join(issues) for n,issues in failed.items()))
        for number,issues in failed.items():
            pack['pages'][number-1]=repair(number,pack['pages'][number-1],issues)
        pending=sorted(failed)
