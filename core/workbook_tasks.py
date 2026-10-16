"""Check all printed student actions, including table rows beyond registered question IDs."""
import re
from core.content_binding import CanonicalTextContainers


def page_tree(page: dict):
    """Read retained layout bindings where available, without looking at teacher answers."""
    parser=CanonicalTextContainers({});parser.feed(page.get('source_layout',page.get('html','')));parser.close()
    return parser.root


def node_words(node, exercise: dict, *, sources_only: bool = False) -> str:
    """Resolve only declared printed text, retaining source values and excluding private keys."""
    if isinstance(node,str):return node
    if 'comment' in node:return ''
    slot=dict(node['attrs']).get('data-content','') or ''
    if sources_only and (slot in {'title','name','date','directions','continuation_title'} or slot.startswith('question_')):return ''
    if slot.startswith('caption_'):
        matches=[c['text'] for c in exercise.get('captions',[]) if isinstance(c,dict) and 'caption_'+str(c.get('id'))==slot]
        if len(matches)==1:return matches[0]
    if slot.startswith('stimulus_'):
        matches=[s['text'] for s in exercise.get('stimuli',[]) if isinstance(s,dict) and 'stimulus_'+str(s.get('id'))==slot]
        if len(matches)==1:return matches[0]
    if slot=='passage':return exercise.get('passage','')
    return ' '.join(node_words(c,exercise,sources_only=sources_only) for c in node['children'])


def tables_in(nodes):
    """Enumerate actual tables, including nested data tables, without flattening rows."""
    for node in nodes:
        if isinstance(node,str) or 'comment' in node:continue
        if node['tag']=='table':yield node
        yield from tables_in(node['children'])


def own_rows(table):
    """Read rows owned by one table, excluding rows of nested layout/data tables."""
    rows=[]
    for child in table['children']:
        if isinstance(child,str) or 'comment' in child:continue
        if child['tag']=='tr':rows.append(child)
        elif child['tag'] in {'thead','tbody','tfoot'}:rows.extend(own_rows(child))
    return rows


def row_cells(row):
    """Keep each cell in its actual row and column order."""
    return [c for c in row['children'] if isinstance(c,dict) and c.get('tag') in {'td','th'}]


def task_coverage_issues(page: dict) -> list[str]:
    """Catch missing labels, incomplete table solutions and items-versus-points wording."""
    exercise=page.get('exercise',{})
    if exercise.get('render_mode')!='authored':return []
    questions=exercise.get('questions',[]);roots=page_tree(page);issues=[]
    source=' '.join(node_words(n,exercise,sources_only=True) for n in roots)
    for q in questions:
        prompt=str(q.get('prompt',''));answer=str(q.get('answer',''))
        numbered=re.search(r'\bnumbered\b.{0,45}\b(?:terms?|items?|components?)\b\s*\(\s*1\s*[-–]\s*([2-8])\s*\)',prompt,re.I)
        if numbered:
            labels=set(re.findall(r'(?<!\w)([1-8])[.)]\s',source))
            # HTML ordered lists supply real printed numbering even when their
            # manifest text has no manually authored numerals.
            def list_count(nodes):
                """Recognize an actual ordinary ordered list, not a guessed reading order."""
                for n in nodes:
                    if isinstance(n,str) or 'comment' in n:continue
                    if n['tag']=='ol' and not dict(n['attrs']).get('data-content','').startswith('question_'):
                        yield sum(isinstance(c,dict) and c.get('tag')=='li' for c in n['children'])
                    yield from list_count(n['children'])
            count=int(numbered[1]);missing=[str(i) for i in range(1,count+1) if str(i) not in labels]
            if missing and count not in list(list_count(roots)):
                issues.append(f'Question {q.get("id")}: references numbered items 1-{count}, but printed source labels {missing} are absent. '
                    'Print each referenced term as its own numbered entry, retaining the original term/order and matching key; do not invent new terms.')
        if (re.search(r'\btotal number of (?:matched )?items\b',prompt,re.I)
                and re.search(r'\beach\b.{0,35}\b(?:earns?|worth)\b.{0,25}\bpoints\b',prompt,re.I)
                and re.search(r'\bpoints\b',answer,re.I)):
            issues.append(f'Question {q.get("id")}: the question asks for a number of items, but the solution is points. '
                'Ask for total points earned for the stated correct matches, or change the calculation/key to the requested item count; align units and preserve all source values.')
    directions=str(exercise.get('directions',''))
    classify_all=bool(re.search(r'\bclassif\w*\b.{0,60}\b(?:each|every|all)\b',directions,re.I))
    if classify_all:
        for table_number,table in enumerate(tables_in(roots),1):
            rows=own_rows(table)
            if len(rows)<4:continue
            headers=[node_words(c,exercise) for c in row_cells(rows[0])]
            if not any(re.search(r'\b(?:classif\w*|fact\s*(?:or|/)\s*opinion)\b',h,re.I) for h in headers):continue
            count=len(rows)-1
            keys=' '.join(str(q.get('answer','')) for q in questions)
            verdicts=re.findall(r'\b(?:fact|opinion)\b',keys,re.I)
            if len(verdicts)<count:
                issues.append(f'Classification table {table_number}: directions require all {count} data rows, but the key supplies fewer category verdicts. '
                    'Make one registered question own the complete table task and list a verdict and concise reason for EVERY row in its answer. '
                    'Retain all rows and student writing space; do not limit the key to the separately discussed rows.')
    return issues


def repeated_inventory_sources(page: dict, exercise: dict) -> set[str]:
    """Find exact pipe-formatted inventory copies whose complete values already occur in a table."""
    signatures=[]
    compact=lambda value:re.sub(r'\s+','',value).casefold()
    for table in tables_in(page_tree(page)):
        rows=own_rows(table)
        if len(rows)<3:continue
        cells=[row_cells(r) for r in rows]
        if any(len(r)!=4 for r in cells):continue
        headings=[compact(node_words(c,exercise)) for c in cells[0]]
        if (headings[1] not in {'initial','initialstock'} or headings[2]!='distributed'
                or headings[3] not in {'returned','returned(usable)'}):continue
        records=[]
        for row in cells[1:]:
            words=[node_words(c,exercise).strip() for c in row]
            if not all(re.fullmatch(r'\d+',v) for v in words[1:]):break
            records.append((compact(words[0]),*(int(v) for v in words[1:])))
        else:signatures.append(records)
    duplicate=set()
    pattern=re.compile(r'\s*([^|.]{1,80}?)\s*\|\s*Initial:\s*(\d+)\s*\|\s*Distributed:\s*(\d+)\s*\|\s*Returned:\s*(\d+)\s*(?:\.|$)',re.I)
    for source in exercise.get('stimuli',[]):
        text=source.get('text') if isinstance(source,dict) else None
        if not isinstance(text,str):continue
        body=re.sub(r'^\s*(?:Supply Tracking Table|Supply Log|Inventory Log):\s*','',text,flags=re.I)
        matches=list(pattern.finditer(body))
        if not 2<=len(matches)<=6 or pattern.sub('',body).strip():continue
        records=[(compact(m[1]),*(int(m[i]) for i in (2,3,4))) for m in matches]
        if records in signatures:duplicate.add(source['id'])
    return duplicate
