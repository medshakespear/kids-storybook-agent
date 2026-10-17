"""Checks for sequence endpoints and answer-revealing matching rows."""
import re
from core.workbook_tasks import page_tree,node_words,tables_in,own_rows,row_cells


def matching_pairs(exercise: dict) -> dict[str,str]:
    """Read one explicit numbered-to-lettered key from a matching question."""
    candidates=[]
    for q in exercise.get('questions',[]):
        if not re.search(r'\b(?:match|pair)\b',str(q.get('prompt','')),re.I):continue
        pairs=re.findall(r'(?<!\w)([1-8])\s*[:=–-]\s*([A-H])(?!\w)',str(q.get('answer','')))
        if len(pairs)>=3 and len({n for n,_ in pairs})==len(pairs) and len({a for _,a in pairs})==len(pairs):candidates.append(dict(pairs))
    return candidates[0] if len(candidates)==1 else {}


def revealed_matching_tables(roots: list, exercise: dict) -> list[list]:
    """Find complete two-column lists with every correct partner in the same row."""
    key=matching_pairs(exercise);result=[]
    if not key:return result
    for table in tables_in(roots):
        rows=own_rows(table)
        if rows and any(c['tag']=='th' for c in row_cells(rows[0])):rows=rows[1:]
        if not 3<=len(rows)<=8 or len(rows)!=len(key):continue
        cells=[row_cells(r) for r in rows]
        if any(len(c)!=2 or any(k in {'rowspan','colspan'} for cell in c for k,_ in cell['attrs']) for c in cells):continue
        pairs=[]
        for left,right in cells:
            n=re.match(r'^\s*([1-8])[.)]\s+',node_words(left,exercise))
            a=re.match(r'^\s*([A-H])[.)]\s+',node_words(right,exercise))
            if not n or not a:break
            pairs.append((n[1],a[1]))
        if len(pairs)==len(rows) and len(dict(pairs))==len(rows) and dict(pairs)==key:result.append(rows)
    return result


def shuffle_matching_rows(page: dict, exercise: dict, config: dict) -> None:
    """Rotate complete labeled choices without changing their wording, letters or key."""
    if not config.get('simple_exercises_only') or exercise.get('render_mode')!='authored':return
    roots=page_tree({'html':page['html']});revealed=revealed_matching_tables(roots,exercise)
    if not revealed:return
    for rows in revealed:
        choices=[row_cells(row)[1] for row in rows]
        for i,row in enumerate(rows):
            old=row_cells(row)[1];index=next(j for j,c in enumerate(row['children']) if c is old)
            row['children'][index]=choices[(i+1)%len(choices)]
    from core.print_grid import literal_html
    page['html']=''.join(literal_html(n) for n in roots)


def sequence_matching_issues(page: dict) -> list[str]:
    """Flag contradicted explicit endpoints and unsupported matching follow-ups."""
    exercise=page.get('exercise',{})
    if exercise.get('render_mode')!='authored':return []
    roots=page_tree(page);source=' '.join(node_words(n,exercise,sources_only=True) for n in roots)
    markers=list(re.finditer(r'(?<!\w)(?:Card\s+)?([A-H])[:.)]\s+',source));cards={}
    for i,m in enumerate(markers):cards.setdefault(m[1],[]).append(source[m.end():markers[i+1].start() if i+1<len(markers) else len(source)].strip())
    if not cards:
        for s in exercise.get('stimuli',[]):
            label=re.fullmatch(r'(?:Card\s+)?([A-H])[:.)]?',str(s.get('label','')).strip())
            if label:cards.setdefault(label[1],[]).append(str(s.get('text','')))
    unique={k:v[0] for k,v in cards.items() if len(v)==1}
    starts=[k for k,v in unique.items() if re.match(r'^(?:First\b|To begin\b|At the start\b)',v,re.I)]
    ends=[k for k,v in unique.items() if re.match(r'^(?:Finally\b|Lastly\b|Last\b|In the end\b)',v,re.I)]
    issues=[]
    for q in exercise.get('questions',[]):
        prompt=str(q.get('prompt',''));answer=str(q.get('answer',''))
        if re.search(r'\b(?:sequence|chronological|order)\b',prompt,re.I):
            route=re.search(r'(?<!\w)([A-H](?:\s*(?:,|→|->|–|-)\s*[A-H]){1,7})\b',answer)
            if route and 3<=len(unique)<=8:
                labels=re.findall(r'[A-H]',route[1])
                if (len(starts)==1 and labels[0]!=starts[0] or len(ends)==1 and labels[-1]!=ends[0]):
                    issues.append(f'Question {q.get("id")}: sequence key contradicts explicit printed time cues. FIRST: {starts}; FINAL: {ends}; key: {labels}. '
                        'Solve the entire order from the retained cards and dependencies and correct only the key/criterion. Keep all sources, letters, prompts and response areas. '
                        'Finally must be last; do not assume Then and Next alone determine the order of interchangeable middle steps.')
        changed=(re.search(r'\bwhy\b',prompt,re.I) and re.search(r'\b(?:traditions?|customs?|festivals?|celebrations?)\b',prompt,re.I) and re.search(r'\b(?:chang\w*|evolv\w*)\b',prompt,re.I))
        causes=re.search(r'\b(?:because|due to|led to|resulted|reason|safer|safety|available|introduced|adopt\w*|migrat\w*|immigra\w*|in order to)\b',source,re.I)
        if changed and matching_pairs(exercise) and not causes:
            issues.append(f'Question {q.get("id")}: matching sources list customs/descriptions but supply no reasons for historical change. '
                'Replace this unsupported why-change follow-up with a short comparison supported by the printed descriptions. Keep the matching sources/task; update only this follow-up and its key together. '
                'Do not invent causes, safety standards, crop availability or historical facts to justify the old answer.')
    if revealed_matching_tables(roots,exercise):issues.append('Matching descriptions reveal every correct partner in the same row. Shuffle complete labeled choices, preserving each letter with its description and the verified key.')
    return issues
