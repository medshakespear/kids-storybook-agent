"""Repair missing printed path details without asking the model to redesign the worksheet."""
from copy import deepcopy
import json
import re
from html.parser import HTMLParser


def repair_schema(design_schema: dict | None) -> dict:
    """Constrain a path repair to the canonical directions, labels and source cards."""
    from core.response_schemas import obj,array,text
    props=(design_schema or {}).get('properties',{}).get('exercise',{}).get('properties',{})
    labels=array(obj({'id':text(24),'text':text(120)}),0,32)
    cards=array(obj({'id':text(24),'text':text(650)}),2,8)
    return obj({'exercise':obj({'directions':deepcopy(props.get('directions',text(350))),
        'captions':deepcopy(props.get('captions',labels)),
        'stimuli':deepcopy(props.get('stimuli',cards))},['captions','stimuli'])})


def repair_messages(system: dict, page: dict, error: str) -> list[dict]:
    """Provide missing prerequisites and frozen exercise content, not an HTML-only retry."""
    return [system,{'role':'user','content':
        'Repair ONLY the missing printed route details of this authored statement_path activity. '
        'Return JSON {"exercise":{"directions":"...","captions":[{"id":"...","text":"..."}],'
        '"stimuli":[{"id":"...","text":"..."}]}}. No HTML, images, questions or replacement task. '
        'Retain every original card and label id and its complete wording. You may add endpoint '
        'or next-step wording around a retained card/label, but never delete, paraphrase or change '
        'its facts or quantities. Add short route captions or clearly fictional source cards if '
        'needed. Print a start and finish and explicit next-step connections beside their checkpoint '
        'labels, such as START: A, A → B and B → FINISH. Markers can be captions or source cards; '
        'connections must yield one complete route consistent with the retained questions and key. '
        'Print all candidate branches and their conditions, including distractors; do not print '
        'only the solved route, identify correct choices for students, or expose the answer key. '
        'Use directions only to clarify text-based routing, not to add student actions. Illustrations '
        'may accompany the activity, but never supply its exact route. Aim for concise added text '
        'to preserve one-page layout. Prefer short endpoint/branch clauses on the existing cards '
        'over separate repeated source cards. Never duplicate an old card under a new ID. '
        'Keep route-only captions brief; do not add an introduction or extra practice. '
        'Python can reflow complete cards into columns and place art beside response boxes '
        'after measured print checks; it cannot discard source facts or shrink working space. '
        'Python retains the original HTML, artwork, question actions, '
        'answers and response space, normalizes only explicit AI-media routing references to the '
        'printed cards, and inserts slots for genuinely new labels/cards. '
        'Missing requirements: '+error+'\nRetained shared exercise:\n'+json.dumps(page['exercise'])}]


def merge_repair(original: dict, correction: dict) -> dict:
    """Keep original task data and HTML; adopt bounded route additions in canonical slots."""
    supplied=correction.get('exercise') if isinstance(correction,dict) else None
    if not isinstance(supplied,dict):
        raise ValueError('Statement-path repair must return an exercise object with captions and stimuli')
    result=deepcopy(original);exercise=result['exercise'];new_slots=[]

    def normalize(value):
        """Ignore whitespace differences when protecting complete original wording."""
        return ' '.join(value.split()) if isinstance(value,str) else ''

    for field,prefix,limit in (('captions','caption_',120),('stimuli','stimulus_',650)):
        old=exercise.get(field,[]);new=supplied.get(field)
        if not isinstance(old,list) or not isinstance(new,list):
            raise ValueError(f'Statement-path repair needs exercise.{field} as a JSON list')
        merged=deepcopy(old);by_id={item['id']:item for item in merged};seen=set()
        for item in new:
            if not isinstance(item,dict) or not isinstance(item.get('id'),str):
                raise ValueError(f'Statement-path repair needs explicit {field} id/text objects')
            sid=item['id']
            if sid in by_id:
                pass  # An explicitly retained ID wins over a namespace-looking spelling.
            elif prefix=='stimulus_':
                from core.activity_stimuli import source_id
                sid=source_id(sid)
            elif sid.startswith(prefix):
                sid=sid[len(prefix):]
            value=item.get('text')
            if (not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',sid) or sid in seen
                    or not isinstance(value,str) or not 1<=len(value.strip())<=limit):
                raise ValueError(f'Statement-path repair needs unique short {field} IDs and complete bounded text')
            seen.add(sid);value=value.strip()
            if sid in by_id:
                # Protect original facts without rejecting harmless added route labels.
                if normalize(by_id[sid]['text']) in normalize(value):
                    by_id[sid]['text']=value
            else:
                merged.append({'id':sid,'text':value});new_slots.append(prefix+sid)
        exercise[field]=merged
    if isinstance(supplied.get('directions'),str) and supplied['directions'].strip():
        from core.prompt_recovery import numeric_values
        proposed=supplied['directions'].strip()
        if not numeric_values(exercise.get('directions',''))-numeric_values(proposed):
            exercise['directions']=proposed
    # Fix only explicit routing references, not incidental coloring/image tasks.
    exercise['directions']=printed_route_reference(exercise.get('directions',''))
    for question in exercise.get('questions',[]):
        question['prompt']=printed_route_reference(question['prompt'])
    if new_slots:
        font=(result.get('_recovery_config') or {}).get('minimum_text_pt',12)
        labels=[slot for slot in new_slots if slot.startswith('caption_')]
        sources=[slot for slot in new_slots if slot.startswith('stimulus_')]
        style=f'font-size:{font}pt;line-height:1.15;margin:0;padding:0.5mm'
        additions=''
        if labels:
            additions='<table style="width:100%;table-layout:fixed;border-collapse:collapse;margin:1mm 0"><tbody>'
            for offset in range(0,len(labels),2):
                additions+='<tr>'+''.join(f'<td style="width:50%;padding:0.5mm;vertical-align:top;border:0.3mm solid #167E80;background-color:#EAF5F2"><p data-content="{slot}" style="{style}"></p></td>' for slot in labels[offset:offset+2])
                if len(labels[offset:offset+2])==1: additions+='<td style="width:50%;padding:0.5mm"></td>'
                additions+='</tr>'
            additions+='</tbody></table>'
        additions+=''.join(f'<p data-content="{slot}" style="{style};margin:0 0 1mm;border:0.3mm solid #167E80"></p>' for slot in sources)
        # Insert before the first question at a real tag boundary, preserving all old nodes.
        parser=HTMLParser(convert_charrefs=True);starts=[]
        def visit(tag,attrs):
            """Find the first question placeholder without matching arbitrary source wording."""
            if (dict(attrs).get('data-content') or '').startswith('question_'):
                starts.append(parser.getpos())
        parser.handle_starttag=visit;parser.feed(result['html']);parser.close()
        if starts:
            line,column=starts[0];lines=result['html'].splitlines(keepends=True)
            offset=sum(len(part) for part in lines[:line-1])+column
            result['html']=result['html'][:offset]+additions+result['html'][offset:]
        else:
            result['html']+=additions
    return result


def printed_route_reference(value: str) -> str:
    """Replace an explicit AI-media route reference with the existing printed-card route."""
    art=r'(?:(?:the|a|an)\s+)?(?:[a-z-]+\s+){0,3}(?:image|illustration|picture|artwork|photo)\b'
    value=re.sub(r'(\b(?:trace|follow|find|choose|navigate|read)\b[^.!?]{0,45}\b(?:path|route|maze|trail|checkpoints?)\b[^.!?]{0,30}?)\b(?:in|on|through|from)\s+'+art,
        lambda match:match[1]+'using the printed source cards and route connections',value,flags=re.I)
    return re.sub(r'(\b(?:use|read|look at|refer to)\s+)'+art+r'(?=\s+to\s+(?:trace|follow|find|navigate)\b[^.!?]{0,25}\b(?:path|route|maze|checkpoints?)\b)',
        lambda match:match[1]+'the printed source cards and route connections',value,flags=re.I)
