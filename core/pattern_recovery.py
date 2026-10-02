"""Repair pattern options from the retained motif, never from model-generated answers."""
from copy import deepcopy

from core.task_visuals import symbol


def recover_pattern_choices(spec: dict) -> dict:
    """Keep a valid motif and derive 2–4 distinct options with exactly one correct symbol."""
    if not isinstance(spec,dict) or spec.get('kind')!='pattern':
        return spec
    motif,choices=spec.get('motif'),spec.get('choices')
    if not isinstance(motif,list) or not 2<=len(motif)<=3:
        return spec
    if not isinstance(choices,list) or not 2<=len(choices)<=4:
        return spec
    try:
        normalized_motif=[symbol(v) for v in motif]
        normalized_choices=[symbol(v) for v in choices]
    except (ValueError,TypeError):
        return spec
    if len({tuple(sorted(v.items())) for v in normalized_motif})<2:
        return spec
    correct=normalized_motif[-1]
    unique=[]
    for choice in normalized_choices:
        if choice not in unique:
            unique.append(choice)
    if len(unique)==len(choices) and unique.count(correct)==1:
        return spec
    if correct not in unique:
        if len(unique)==4:
            unique[-1]=correct
        else:
            unique.append(correct)
    if len(unique)<2:
        unique.append(next(v for v in normalized_motif if v!=correct))
    result=deepcopy(spec)
    result['choices']=unique
    return result
