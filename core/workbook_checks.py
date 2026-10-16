"""Local checks for answer disclosures in printed student classification tables."""
import re
from html.parser import HTMLParser


def printed_words(markup: str) -> str:
    """Read actual text without treating image prompts or teacher keys as evidence."""
    parts=[];parser=HTMLParser(convert_charrefs=True);parser.handle_data=parts.append
    parser.feed(markup);parser.close()
    return ' '.join(' '.join(parts).split())


def classification_leaks(page: dict) -> list[str]:
    """Flag filled answer cells, not unselected choices, sources or table headings."""
    exercise=page.get('exercise',{})
    task=' '.join([str(exercise.get('directions',''))]+[str(q.get('prompt','')) for q in exercise.get('questions',[])])
    if not re.search(r'\b(?:classif\w*|categor\w*|sort|label)\b',task,re.I):return []
    categories=[]
    for term in ('fact','opinion','direct observation','cultural interpretation'):
        if re.search(r'\b'+re.escape(term)+r's?\b',task,re.I):categories.append(term)
    if len(categories)<2:return []
    from core.content_binding import CanonicalTextContainers
    from core.print_grid import literal_html
    parser=CanonicalTextContainers({});parser.feed(page.get('html',''));parser.close();issues=[];table_number=0

    def response_header(value):
        """Distinguish an explicit answer column from a source/evidence-statement column."""
        if re.search(r'\b(?:classif\w*|categor\w*)\b|^(?:statement\s+)?type$',value,re.I):return True
        if re.search(r'\b(?:statements?|sources?|claims?|records?|excerpts?|descriptions?)\b',value,re.I):return False
        if re.search(r'\b(?:reason\w*|explanations?|justification|supporting\s+(?:evidence|phrase)|your\s+evidence)\b',value,re.I):return True
        # Plain "Evidence" can introduce supplied observations. Ambiguous
        # columns remain the responsibility of independent content review.
        if any(re.fullmatch(re.escape(c)+r's?',value.strip(),re.I) for c in categories):return True
        return unselected_choices(value)

    def unselected_choices(value):
        """Recognize only empty choice scaffolds; selected marks and reasoning are answers."""
        if re.search(r'[☑☒✓✔●]|[\[(]\s*[xX*]\s*[\])]',value):return False
        present=[c for c in categories if re.search(r'\b'+re.escape(c)+r's?\b',value,re.I)]
        if not present:return False
        if any(len(re.findall(r'\b'+re.escape(c)+r's?\b',value,re.I))>1 for c in present):return False
        empty_box=bool(re.search(r'[☐□○◯]|\[\s*\]|\(\s*\)',value))
        if not empty_box and len(present)!=len(categories):return False
        remaining=value
        for category in categories:remaining=re.sub(r'\b'+re.escape(category)+r's?\b',' ',remaining,flags=re.I)
        remaining=re.sub(r'\b(?:circle|choose|select|check|one|or|and|option|category)\b',' ',remaining,flags=re.I)
        return not re.sub(r'[\s_:/|(),.;?\[\]☐□○◯-]+','',remaining)

    def rows(node):
        """Read rows inside this table only; nested tables have their own ownership."""
        if isinstance(node,str) or 'comment' in node:return []
        if node['tag']=='tr':return [node]
        return [row for child in node['children'] if not isinstance(child,dict) or child.get('tag')!='table' for row in rows(child)]

    def visit(node):
        """Require a classification/reason column before inspecting its answer cells."""
        nonlocal table_number
        if isinstance(node,str) or 'comment' in node:return
        if node['tag']=='table':
            table_number+=1
            records=rows(node)
            if records:
                header_cells=[c for c in records[0]['children'] if isinstance(c,dict) and c.get('tag') in {'td','th'}]
                headers=[printed_words(literal_html(c)) for c in header_cells]
                worked=any(re.search(r'\bworked example\b',h,re.I) for h in headers)
                merged=any(str(dict(c['attrs']).get(k,'1'))!='1' for c in header_cells for k in ('colspan','rowspan'))
                columns=[i for i,h in enumerate(headers) if response_header(h)]
                if columns and not worked and not merged:
                    for row_number,row in enumerate(records[1:],1):
                        cells=[c for c in row['children'] if isinstance(c,dict) and c.get('tag') in {'td','th'}]
                        if any(str(dict(c['attrs']).get(k,'1'))!='1' for c in cells for k in ('colspan','rowspan')):continue
                        for i in columns:
                            if i>=len(cells):continue
                            text=printed_words(literal_html(cells[i]))
                            category=any(re.search(r'\b'+re.escape(term)+r's?\b',text,re.I) for term in categories)
                            selection=bool(re.search(r'[☑☒✓✔]|^\s*[xX]\s*$',text)) and any(
                                re.fullmatch(re.escape(c)+r's?',headers[i].strip(),re.I) for c in categories)
                            if (category and not unselected_choices(text)) or selection:
                                issues.append(f'Student classification/reasoning table reveals a requested category: '
                                    f'table {table_number}, data row {row_number}, column {i+1} ({headers[i]!r}), '
                                    f'printed cell {text[:180]!r}. Clear only this student answer cell; preserve '
                                    'its border, dimensions, source statement and all source evidence. Keep its '
                                    'verified solution in the final key. If an answer-only caption owns this cell, '
                                    'remove that caption and its binding together, leaving the cell blank; never '
                                    'remove a source/header caption or another required source slot. Empty Fact/Opinion choice labels are '
                                    'allowed; do not rewrite the activity or delete source text to fix this cell.')
        for child in node['children']:visit(child)

    for node in parser.root:visit(node)
    return list(dict.fromkeys(issues))


def unsupported_fact_claims(page: dict) -> list[str]:
    """Catch an asserted factual quoted claim naming entities absent from its evidence.

    This narrow check does not fact-check history or reject valid false-statement
    corrections. A positively classified FACT/TRUE claim cannot ask for textual
    proof of a named place/person that the retained reading never mentions.
    """
    exercise=page.get('exercise',{})
    source=' '.join([str(exercise.get('passage',''))]+
        [str(s.get('text','')) for s in exercise.get('stimuli',[]) if isinstance(s,dict)]+
        [str(c.get('text','')) for c in exercise.get('captions',[]) if isinstance(c,dict)])
    source=' '.join(source.split()).casefold();issues=[]
    for q in exercise.get('questions',[]):
        if not isinstance(q,dict):continue
        prompt=str(q.get('prompt',''));answer=str(q.get('answer',''))
        if not (re.search(r'\b(?:supporting text|evidence|based on|according to|from the passage|from the text)\b',prompt,re.I)
                and re.match(r'^\s*(?:classification\s*:\s*)?(?:fact|true)\b',answer,re.I)):continue
        claims=re.findall(r'[\x27\"‘“]([^\x27\"’”]{20,})[\x27\"’”]',prompt)
        for claim in claims:
            for entity in re.findall(r'\b(?:[A-Z][a-z]+\s+){1,5}[A-Z][a-z]+\b',claim):
                if ' '.join(entity.split()).casefold() not in source:
                    issues.append(f'Question {q.get("id")}: the key classifies a claim as FACT/TRUE, but its named detail {entity!r} is absent from the reading. Remove the unsupported detail or supply verified source evidence; do not invent a supporting quote.')
    return list(dict.fromkeys(issues))
