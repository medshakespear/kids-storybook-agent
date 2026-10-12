"""Opt-in varied exercises with model-authored, individually print-checked layouts."""
from copy import deepcopy

from core.creative_generator import generate_creative_pack
from core.grade_policy import require_active_grade


def generate_varied_pack(theme, grade_band, grade_config, *, source_context=None, book_title=None):
    """Keep Gemini's compositions while retaining shared answers and print checks.

    This configuration copy never changes the reading/QCM mode or global defaults.
    Content slots bind the model's layout to verified exercise wording and answers;
    Python does not replace these pages with the legacy canonical worksheet layout.
    """
    require_active_grade(grade_band)
    config = deepcopy(grade_config)
    profile = config[grade_band]
    profile['purposeful_activity_layout'] = False
    context = (source_context or '') + '''
WORKBOOK TYPE: mixed, original student exercises, not a reading/QCM collection.
Invent meaningful tasks for this specific theme and grade. Possible inspirations include
comparing short texts, vocabulary in context, sequencing a process, interpreting an authored
table, applied mathematics, persuasive or explanatory writing, investigations and design
challenges. These are possibilities, not a ten-page template to repeat. Choose at least five
different student actions; at least half the activities should be authored and context-specific.
Do not make babyish counting, generic shape puzzles or a QCM-only pack for grades 3–6.
Use clear age-appropriate language, short instructions and practical writing/drawing space.
Gemini owns each page composition, color palette, panels and hierarchy. Vary the compositions
while keeping one professional visual identity. Use substantial purposeful illustrations.
All needed information, tables, measurements and labels must be written in the exercise's
passage/caption/question fields and bound HTML slots; artwork cannot supply exact data.
Never fabricate a primary source, quotation, ordinance, historical achievement or cultural
practice. Label invented case studies and simulated source excerpts clearly as fictional.
Use named, accurate cultural contexts rather than mixing traditions across Indigenous nations.
Provide exact answers for closed tasks and concise concrete success criteria for open tasks.
No teacher guide. No answers on student pages. One consolidated final answer key.
'''
    pack = generate_creative_pack(theme, grade_band, config, source_context=context,
                                  book_title=book_title, require_variety=True)
    pack.update(book_type='varied_activities', content_format='varied_activities',
                design_engine='gemini_authored_activities')
    return pack
