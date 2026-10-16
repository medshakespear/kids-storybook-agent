"""Opt-in varied exercises with model-authored, individually print-checked layouts."""
from copy import deepcopy

from core.creative_generator import generate_creative_pack
from core.grade_policy import require_active_grade


def generate_varied_pack(theme, grade_band, grade_config, *, source_context=None, book_title=None):
    """Generate simple written exercises with model layouts and checked answers.

    This configuration copy never changes the reading/QCM mode or global defaults.
    Content slots bind the model's layout to verified exercise wording and answers;
    Failed geometry receives bounded reflow of the same verified content before
    requesting another model design; successful model compositions stay intact.
    """
    require_active_grade(grade_band)
    config = deepcopy(grade_config)
    profile = config[grade_band]
    profile['purposeful_activity_layout'] = False
    profile['table_caption_limit'] = 36
    profile['context_caption_limit'] = 24
    profile['stimulus_limit'] = 8
    profile['items_per_page'] = 2
    profile.update(student_workbook=True,minimum_response_mm=35,extended_response_mm=50,
                   minimum_response_width_mm=150,content_review_batch_size=3,
                   allow_activity_continuations=True)
    profile.update(simple_exercises_only=True, grade_band=grade_band)
    profile.update(max_operand=1000 if grade_band=='3rd-4th' else 10000,
                   max_result=10000 if grade_band=='3rd-4th' else 100000)
    profile['skill_notes']='Clear grade-appropriate reading, vocabulary, text reasoning, data interpretation and useful mathematics. Short written responses; no crafts, drawings or design projects.'
    from core.simple_exercises import exercise_guidance
    context = (source_context or '') + '\n' + exercise_guidance(grade_band) + '''
WORKBOOK TYPE: simple varied written exercises, not a QCM-only collection.
Gemini chooses the original content and clean, colorful page layouts. Use authored mode
only. Keep source cards short (about 70 words combined for grades 3-4, 100 for grades 5-6).
Sources use stimuli [{id,label,text}] and data-content="stimulus_ID". Longer text belongs
in stimuli, not short captions. Bind each source, question and heading once. Declare all
short table cells and headings in captions with data-content="caption_ID". Do not prefix
IDs inside the manifest. Keep tables small and preserve every printed data value.
Provide one or two focused questions with full-width response areas, at least 35mm for
short answers and 50mm for longer explanations. Do not request practice drawing boxes.
Use named accurate cultural contexts; identify fictional sources as fictional.
No teacher guide. No answers on student pages. One consolidated final answer key.
'''
    pack = generate_creative_pack(theme, grade_band, config, source_context=context,
                                  book_title=book_title, require_variety=True)
    pack.update(book_type='varied_activities', content_format='varied_activities',
                design_engine='gemini_authored_activities')
    return pack
