"""Local checks for answer disclosures in printed student classification tables."""
import re
from html.parser import HTMLParser


def printed_words(markup: str) -> str:
    """Read actual text without treating image prompts or teacher keys as evidence."""
    parts=[];parser=HTMLParser(convert_charrefs=True);parser.handle_data=parts.append
    parser.feed(markup);parser.close()
    return ' '.join(' '.join(parts).split())


def classification_leaks(page: dict) -> list[str]:
    """Flag filled classification/reason cells, leaving source cards and worked examples intact."""
    exercise=page.get('exercise',{})
    task=' '.join([str(exercise.get('directions',''))]+[str(q.get('prompt','')) for q in exercise.get('questions',[])])
    if not re.search(r'\b(?:classif\w*|categor\w*|sort|label)\b',task,re.I):return []
    categories=[]
    for term in ('fact','opinion','direct observation','cultural interpretation'):
        if re.search(r'\b'+re.escape(term)+r's?\b',task,re.I):categories.append(term)
    if len(categories)<2:return []
    from core.content_binding import CanonicalTextContainers
    from core.print_grid import literal_html
    parser=CanonicalTextContainers({});parser.feed(page.get('html',''));parser.close();issues=[]

    def rows(node):
        """Read rows inside this table only; nested tables have their own ownership."""
        if isinstance(node,str) or 'comment' in node:return []
        if node['tag']=='tr':return [node]
        return [row for child in node['children'] if not isinstance(child,dict) or child.get('tag')!='table' for row in rows(child)]

    def visit(node):
        """Require a classification/reason column before inspecting its answer cells."""
        if isinstance(node,str) or 'comment' in node:return
        if node['tag']=='table':
            records=rows(node)
            if records:
                headers=[printed_words(literal_html(c)) for c in records[0]['children'] if isinstance(c,dict) and c.get('tag') in {'td','th'}]
                worked=any(re.search(r'\bworked example\b',h,re.I) for h in headers)
                columns=[i for i,h in enumerate(headers) if re.search(r'\b(?:classif\w*|category|reason\w*|evidence)\b',h,re.I)]
                if columns and not worked:
                    for row in records[1:]:
                        cells=[c for c in row['children'] if isinstance(c,dict) and c.get('tag') in {'td','th'}]
                        if any(i<len(cells) and any(re.search(r'\b'+re.escape(term)+r's?\b',printed_words(literal_html(cells[i])),re.I) for term in categories) for i in columns):
                            issues.append('Student classification/reasoning table reveals a requested category. Leave response cells blank; preserve the source statements and move solutions to the final key.')
                            break
        for child in node['children']:visit(child)

    for node in parser.root:visit(node)
    return list(dict.fromkeys(issues))
