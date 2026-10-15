"""Review small groups of activities with an independent solution for every task."""
import json

from core.exercise_quality import student_text
from core.task_visuals import answer_text


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
    pending=list(range(1,len(pack['pages'])+1))
    for attempt in range(2):
        failed={}
        for offset in range(0,len(pending),batch_size):
            pages=[]
            for n in pending[offset:offset+batch_size]:
                page=pack['pages'][n-1]
                pages.append({'page_number':n,'title':page['title'],'planned_intent':page.get('planned_intent'),
                    'exercise':page['exercise'],'student_content':student_text(page),'answer_key':answer_text(page)})
            prompt=('Review student workbook activities for '+pack['grade_band']+'. This is TEXT curriculum review, not image review. '
                'Independently SOLVE EVERY question from the printed sources before comparing its answer key. '
                'Return one page review and one question_checks record per question. Include a concrete solution '
                'and reason, plus source_support, skill_match and answer_correct booleans. '
                'Check the complete learning action: a working shape sort or picture matcher does not teach '
                'fact/opinion classification or matching claims to evidence. Flag unrelated fillers. '
                'Check source science, instrument/unit consistency (rain gauge: rainfall; barometer: air pressure), '
                'factual accuracy, mixed fact/opinion statements, ambiguous task counts such as all three when '
                'five words qualify, and whether evidence is actually printed. Labels must identify '
                'their own source text. Do not infer source identities from internal IDs or array order. '
                'Set no_answer_leak=false if sources already print classifications, correct matching pairs or '
                'word-hunt solutions students must discover, unless a separate worked example. '
                'Do not assess AI image pixels or assume exact teeth/counts/measurements from generated art. '
                'Quantitative data must be printed. Check every part of multipart questions and allow '
                'reasonable open-answer criteria. Issues [] requires positive verdicts AND independent '
                'solutions; do not approve on appearance or mathematical metadata alone. '
                'Give precise correction issues, not stylistic preferences. Do not shrink writing space. '
                'Return JSON pages with page_number, source_accuracy, no_answer_leak, reason, '
                'question_checks and issues. Activities:\n'+json.dumps(pages))
            verdict=ask(prompt,lambda raw:validate_review(raw,pages),'Workbook content review',
                5000,response_schema=review_schema(pages))
            failed.update({n:issues for n,issues in verdict.items() if issues})
        if not failed:
            pack['content_checks']={'status':'passed','pages':len(pack['pages']),'repair_rounds':attempt,
                'method':'independent_question_solutions_and_source_skill_key_review'}
            return
        if attempt:
            raise ValueError('Workbook content still needs correction: '+'; '.join(
                f'Activity {n}: '+ '; '.join(issues) for n,issues in failed.items()))
        for number,issues in failed.items():
            pack['pages'][number-1]=repair(number,pack['pages'][number-1],issues)
        pending=sorted(failed)
