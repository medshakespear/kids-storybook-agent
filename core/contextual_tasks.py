"""Conservative local guards for inventory meaning and procedural safety sequences."""
import re
from fractions import Fraction


def source_text(exercise: dict) -> str:
    """Read retained sources without treating an answer key as evidence."""
    return ' '.join([str(exercise.get('passage',''))]+
        [str(s.get('text','')) for s in exercise.get('stimuli',[]) if isinstance(s,dict)])


def inventory_return_issues(exercise: dict) -> list[str]:
    """Distinguish net distributed items from stock in explicit two-delivery records.

    Complex stories remain the responsibility of blind text review. This guard
    never guesses a missing starting quantity or rewrites an authored answer.
    """
    source=source_text(exercise)
    deliveries=[];returns=[];distribution_numbers=[];item=None;returned_item=None
    for sentence in re.split(r'(?<=[.!?])\s+',source):
        numbers=re.findall(r'(?<![\w.,])\d+(?![\w.,])',sentence)
        if re.search(r'\b(?:handed out|distributed)\b',sentence,re.I) and len(numbers)==2:
            first=re.search(r'\b(?:handed out|distributed)\s+\d+\s+([A-Za-z -]+?)(?=\s+(?:on|at|to|and)\b|[.!?]|$)',sentence,re.I)
            second=re.search(r'\band\s+\d+\s+([A-Za-z -]+?)(?=\s+(?:on|at|to)\b|[.!?]|$)',sentence,re.I)
            item=first[1].split()[-1].lower() if first else None
            if second and not re.match(r'(?:on|at|to)\b',second[1],re.I) and second[1].split()[-1].lower()!=item:return []
            deliveries.append(sum(map(int,numbers)))
            distribution_numbers.extend(map(int,numbers))
        if re.search(r'\breturned\b',sentence,re.I) and len(numbers)==1:
            if re.search(r'\b(?:damaged|unusable|discarded|disposed|destroyed|not restocked)\b',sentence,re.I):return []
            resource=re.search(r'\breturned\s+\d+\s+([A-Za-z -]+?)(?=\s+(?:to|on|at)\b|[.!?]|$)',sentence,re.I)
            returned_item=resource[1].split()[-1].lower() if resource else None
            returns.append(int(numbers[0]))
    if len(deliveries)!=1 or len(returns)!=1 or not item or item!=returned_item:return []
    distributed,returned=deliveries[0],returns[0]
    if returned>distributed:return []
    issues=[]
    for q in exercise.get('questions',[]):
        prompt=str(q.get('prompt',''))
        stock=bool(re.search(r'\b(?:remain\w*\s+(?:at|in)\s+(?:the\s+)?(?:school|office|storage)|'
            r'left\s+in\s+(?:the\s+)?(?:storage|box|office)|stock|inventory)\b',prompt,re.I))
        if not stock:continue
        initial=re.search(r'\b(?:ordered|started with|initially had)\s+(?:a total of\s+)?(\d+)\b',source+' '+prompt,re.I)
        if not initial:
            # Another printed number may be starting stock expressed in a way
            # this narrow parser does not understand. Defer that case to review.
            known=set(distribution_numbers+returns)
            if any(int(n) not in known for n in re.findall(r'\b\d+\b',source+' '+prompt)):continue
            issues.append(f'Question {q.get("id")}: stock remaining is underdetermined: '
                f'{distributed} handed out minus {returned} returned gives {distributed-returned} '
                'still distributed, not stock at school. Supply starting stock and say returns '
                'are restocked, or ask how many remain with recipients. Align calculation and key.')
            continue
        calculation=q.get('calculation')
        if not isinstance(calculation,dict):continue
        try:actual=Fraction(str(calculation.get('answer')))
        except (ValueError,TypeError,ZeroDivisionError):continue
        expected=int(initial[1])-distributed+returned
        if actual!=expected:
            issues.append(f'Question {q.get("id")}: returned usable items INCREASE available stock. '
                f'If returns are restocked, storage is {initial[1]} - {distributed} + {returned} = '
                f'{expected}, not {actual}. Clarify the return condition/location in the source '
                'and repair the question, calculation and prose answer together.')
    return issues


def upstander_sequence_issues(exercise: dict) -> list[str]:
    """Prevent procedural keys from requiring peer actions before seeking adult help."""
    task=' '.join([str(exercise.get('directions',''))]+
        [str(q.get('prompt','')) for q in exercise.get('questions',[])])
    if not (re.search(r'\bupstander\b',task,re.I) and
            re.search(r'\b(?:order|sequence|chronological)\b',task,re.I)):return []
    source=source_text(exercise)
    markers=list(re.finditer(r'(?<!\w)(?:Card\s+)?([A-H])[:.)]\s+',source))
    reports=set();support=set()
    for i,m in enumerate(markers):
        body=source[m.end():markers[i+1].start() if i+1<len(markers) else len(source)]
        if re.search(r'\b(?:tell|report|seek|ask)\b.{0,65}\b(?:adult|teacher)\b',body,re.I):reports.add(m[1])
        if re.search(r'\b(?:check in|invite|speak up|stay nearby)\b',body,re.I):support.add(m[1])
    for q in exercise.get('questions',[]):
        route=re.match(r'^\s*([A-H](?:\s*(?:,|→|->|–|-)\s*[A-H]){1,7})\b',str(q.get('answer','')))
        if not route:continue
        labels=re.findall(r'[A-H]',route[1])
        if any(labels.index(r)>labels.index(s) for r in reports for s in support if r in labels and s in labels):
            return [f'Question {q.get("id")}: the procedural upstander key requires peer actions '
                'before telling an adult. Seek trusted adult help promptly; optional peer support '
                'is only when safe and is never a prerequisite for reporting. Rewrite the cards '
                'with explicit chronological cues for one defensible sequence, or accept multiple '
                'safe orders with a clear criterion. Do not merely change the answer letters.']
    return []


def contextual_task_issues(page: dict) -> list[str]:
    """Keep observed semantic failures mandatory even when a model approves the key."""
    exercise=page.get('exercise',{})
    if exercise.get('render_mode')!='authored':return []
    return inventory_return_issues(exercise)+upstander_sequence_issues(exercise)
