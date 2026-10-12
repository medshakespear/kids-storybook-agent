"""Keep source excerpts and scenarios separate from short visual captions."""
import re


def prepare_stimuli(page: dict, exercise: dict) -> list[dict]:
    """Move complete overlong caption text into source blocks without truncating it.

    Only text already present in the shared specification is moved. The layout's
    corresponding slot is renamed; question wording, answers and data stay intact.
    """
    stimuli = exercise.get('stimuli', [])
    if not isinstance(stimuli, list):
        raise ValueError('Exercise stimuli must be a JSON list')
    captions = exercise.get('captions', [])
    if not isinstance(captions, list):
        return stimuli
    retained = []
    ids = {item.get('id') for item in stimuli if isinstance(item,dict)}
    for caption in captions:
        if (isinstance(caption,dict) and isinstance(caption.get('text'),str)
                and 120 < len(caption['text'].strip())):
            cid = caption.get('id')
            if not isinstance(cid,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',cid):
                retained.append(caption)
                continue
            if cid in ids:
                raise ValueError('Source stimulus IDs must not collide with migrated caption IDs')
            stimuli.append(dict(caption))
            ids.add(cid)
            # Both prefix conventions are accepted elsewhere for declared IDs.
            pattern = r'(\bdata-content\s*=\s*)([\'\"])(?:caption_)?'+re.escape(cid)+r'\2'
            page['html'] = re.sub(pattern,lambda m:m[1]+m[2]+'stimulus_'+cid+m[2],page['html'])
        else:
            retained.append(caption)
    exercise['captions'] = retained
    exercise['stimuli'] = stimuli
    return stimuli


def source_density_repair(draft: dict, prompt: str, error: str) -> str | None:
    """Request content revision when an opt-in mixed source page cannot fit unchanged."""
    target = re.search(r'combined passage and stimuli target <=(\d+) words',prompt)
    exercise = draft.get('exercise') if isinstance(draft,dict) else None
    if not target or not error.startswith(('Design overflow:', 'Design content extends outside printable bounds:')) or not isinstance(exercise,dict):
        return None
    texts = [exercise.get('passage','')]
    for field in ('stimuli','captions'):
        values = exercise.get(field,[])
        if isinstance(values,list):
            texts += [s.get('text','') for s in values if isinstance(s,dict)
                      and (field=='stimuli' or len(str(s.get('text',''))) > 120)]
    words = sum(len(text.split()) for text in texts if isinstance(text,str))
    limit = int(target[1])
    if words <= limit:
        return None
    return (f'This mixed activity has {words} source/passage words and cannot fit unchanged. '
            f'Return a complete revised exercise and layout targeting {limit} combined source words, '
            'not an HTML-only repair. Shorten source phrasing while retaining every fact, quantity '
            'and distinction required by the printed questions. Keep the planned title, mechanic, '
            'learning goal, substantive images, readable font and response space. Realign the shared '
            'answer criteria to the revised sources. Use stimuli for excerpts and short captions for '
            'labels. Do not delete questions, invent evidence or shrink typography to force a fit.')
