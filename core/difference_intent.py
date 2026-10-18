"""Distinguish picture-change puzzles from comparing written facts, opinions or numbers."""
from html.parser import HTMLParser
import re


def printed_instructions(page: dict) -> list[str]:
    """Read student tasks, never illustration briefs or words joined across unrelated fields."""
    exercise=page.get('exercise')
    if page.get('exercise_binding') and isinstance(exercise,dict):
        values=[exercise.get('directions','')]
        values.extend(q.get('prompt','') for q in exercise.get('questions',[]) if isinstance(q,dict))
        # A short caption may itself declare a task. Do not read source stories,
        # answer keys, metadata goals or image-generation prompts as directions.
        values.extend(c.get('text','') for c in exercise.get('captions',[]) if isinstance(c,dict))
        return [v for v in values if isinstance(v,str) and v.strip()]
    parts=[];parser=HTMLParser(convert_charrefs=True)

    def boundary(tag,attrs=None):
        """Keep inline words together while separating independent printed text blocks."""
        if tag in {'p','div','section','h1','h2','h3','h4','h5','h6','li','td','th','br'}:
            parts.append('\n')

    parser.handle_starttag=boundary;parser.handle_endtag=boundary
    parser.handle_data=parts.append;parser.feed(page.get('html',''));parser.close()
    return ''.join(parts).splitlines()


def requires_exact_differences(page: dict) -> bool:
    """Require exact rows for a picture puzzle without converting textual comparisons into one.

    Generic 'spot the differences' tasks still require computed visuals. A clear
    comparison of facts, passages or numeric quantities does not. No mechanic-wide
    exemption is granted: an extra picture puzzle on a statement path is checked.
    """
    action=r'\b(?:find|spot|circle|mark|identify|locate|list)\b[^.!?;\n]{0,70}?\bdifferences?\b'
    text_targets=r'\b(?:facts?|opinions?|claims?|statements?|arguments?|passages?|texts?|accounts?|perspectives?|reports?|sources?|definitions?|evidence|wording|sentences?|descriptions?|viewpoints?|ideas?|numbers?|amounts?|totals?|prices?|measurements?|temperatures?)\b'
    picture_target=r'^\s*(?:between|in|among|on)\s+(?:(?:the|these|those|two|both|top|bottom|first|second|following|original|changed|pair\s+of)\s+){0,5}(?:pictures?|images?|illustrations?|drawings?|scenes?|photos?|photographs?|objects?|symbols?|shapes?)\b'
    numeric_target=r'^\s*(?:between|of)\s+[-−]?\d+(?:\.\d+)?\s+(?:and|versus|vs\.?)\s+[-−]?\d+(?:\.\d+)?\b'
    instructions=printed_instructions(page)
    written_cards=bool(page.get('exercise_binding') and isinstance(page.get('exercise'),dict)
                       and (page['exercise'].get('stimuli') or page['exercise'].get('passage')))
    for instruction in instructions:
        # Plans describe the written sources before their actual excerpts exist.
        # Recognize that explicit context within this field, never from titles,
        # mechanic labels, illustration prompts or another planning field.
        written_context=bool(re.search(
            r'\b(?:read|compare|contrast|examine|analyze|analyse)\b[^.!?;\n]{0,80}\b'
            r'(?:passages?|texts?|accounts?|reports?|sources?|written\s+cards?|printed\s+cards?)\b',
            instruction,re.I))
        picture_context=bool(re.search(
            r'\b(?:pictures?|images?|illustrations?|drawings?|scenes?|photos?|photographs?)\b',
            instruction,re.I))
        for clause in re.split(r'[!?;\n]+|(?<!\d)\.|\.(?!\d)',instruction):
            for match in re.finditer(action,clause,re.I):
                target=clause[match.end():]
                if re.search(picture_target,target,re.I): return True
                if re.search(r'\b(?:rows?|objects?|symbols?|shapes?)\b',target,re.I) and not re.search(text_targets,target,re.I):
                    return True
                comparison=re.split(r'\b(?:then|and\s+(?:explain|write|tell|record|justify|draw|color|colour|answer))\b',target,maxsplit=1,flags=re.I)[0]
                textual=(re.match(r'^\s*(?:between|in|among|of|across|using|from|through|based\s+on)\b',comparison,re.I)
                         and (re.search(text_targets,comparison,re.I) or re.search(r'\b(?:written|printed|source)\s+cards?\b',comparison,re.I)))
                conceptual=(re.match(r'^\s*(?:between|in|among|across)\b',comparison,re.I)
                            and re.search(r'\b(?:customs?|traditions?|celebrations?|practices?)\b',comparison,re.I)
                            and not re.search(r'\b(?:pictures?|images?|illustrations?|drawings?|scenes?|photos?)\b',comparison,re.I))
                labeled_cards=(written_cards and re.match(r'^\s*(?:between|in|among)\s+(?:(?:the|these|two|both|written|printed)\s+)*(?:cards?\b|(?:Card\s+)?[A-H]\s+(?:and|versus|vs)\s+(?:Card\s+)?[A-H]\b)',comparison,re.I))
                if (textual and not picture_context) or conceptual or labeled_cards or re.search(numeric_target,target,re.I):
                    continue
                if written_context and not picture_context:
                    continue
                return True  # A generic picture-change task needs the exact component too.
    return False
