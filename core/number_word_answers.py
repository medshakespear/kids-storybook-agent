"""Recognize unambiguous elementary whole-number answer keys without inferring arithmetic."""
import re

SMALL = dict(zip(('zero one two three four five six seven eight nine ten eleven twelve '
                  'thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split(),range(20)))
TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(),range(20,100,10)))
UNITS = {'bead','beads','item','items','block','blocks','student','students','coin','coins',
         'pencil','pencils','book','books','flower','flowers','pumpkin','pumpkins','unit','units',
         'point','points','counter','counters','button','buttons','shape','shapes'}


def whole_number_word_answer(text: str) -> int | None:
    """Read a complete cardinal answer (0–99), optionally with a simple counting unit."""
    if not isinstance(text,str):
        return None
    value = re.sub(r'^(?:answer|result)(?:\s+is)?\s*[:=]?\s*','',text.strip().casefold())
    value = re.sub(r'(?<=[a-z])-(?=[a-z])',' ',value.rstrip('.').strip())
    words = value.split()
    if words and words[-1] in UNITS:
        words.pop()
    if len(words)==1:
        return SMALL.get(words[0],TENS.get(words[0]))
    if len(words)==2 and words[0] in TENS and words[1] in SMALL and 1<=SMALL[words[1]]<=9:
        return TENS[words[0]]+SMALL[words[1]]
    return None
