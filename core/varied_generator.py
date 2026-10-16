"""Opt-in varied exercises with model-authored, individually print-checked layouts."""
from copy import deepcopy

from core.creative_generator import generate_creative_pack
from core.grade_policy import require_active_grade


def generate_varied_pack(theme, grade_band, grade_config, *, source_context=None, book_title=None):
    """Keep Gemini's compositions while retaining shared answers and print checks.

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
Longer source excerpts, scenario cards and comparison texts belong in exercise.stimuli,
not captions. Use up to eight SHORT {id,text} cards, each <=650 characters, bound once with
data-content="stimulus_ID". Captions stay short labels <=120 characters. Sources
use bare IDs such as "placard_text", never "stimulus_placard_text"; the HTML slot
alone adds the stimulus_ prefix, as in data-content="stimulus_placard_text".
Source blocks are NOT eight full-length reading passages: keep combined text short enough for this
single activity page and its substantial illustration and writing space.
Table headers and each data cell are short captions: declare each unique id/text pair,
then use data-content="caption_ID" in that cell. Caption IDs themselves should NOT
start with caption_. Mixed pages allow up to 36 short table cells in addition to
24 short contextual labels and eight diagram identifiers. All cells must fit on one page.
Never fabricate a primary source, quotation, ordinance, historical achievement or cultural
practice. Label invented case studies and simulated source excerpts clearly as fictional.
Use named, accurate cultural contexts rather than mixing traditions across Indigenous nations.
Provide exact answers for closed tasks and concise concrete success criteria for open tasks.
Semantic matching of claims to measurements, definitions or evidence is an AUTHORED text
activity: declare the complete source cards and question/key. Exact matching is only for
identical pictures or shadows. Do not put a picture puzzle beneath unrelated text-matching
instructions. Bind all headings, labels and directions in the initial response, not only the
first instruction. Use a full-width, aspect-preserving computed diagram with readable labels
on exact pages; budget its height together with captions and all response areas.
Fact/opinion or reading-checkpoint paths are authored statement_path activities. Print every
candidate statement, label and next-step connection, and a complete unique route in the key.
The geometric exact maze has only walls and stars; it cannot host statement checkpoints.
For this student workbook use ONLY authored contextual activities. Do not plan generic shape
sorting, shadow matching, counting, geometric puzzles or statement-path/checkpoint mazes.
Teach the requested skill directly through varied text, evidence, editing, investigations,
data and original written/drawn responses. A fact/opinion activity must use actual statements.
Each source has id, label and text. Python prints label and text together in stimulus_ID;
never print a separate empty Card A/Source A column or repeat the label in captions.
Keep combined sources short: aim for 70 words in grades 3-4, 100 in grades 5-6.
Use at most two focused questions. Allow at least 35mm height per short written answer and
50mm for paragraphs, rewriting, plans or drawings. Answers need full width (at least 150mm),
normally below the source/illustration region. Never put writing in a narrow side column.
Do not print Fact/Opinion classifications, correct matches or indicator-word solutions in
student source cards unless explicitly marked as a worked example separate from the questions.
Ask for all items or any stated number consistently. Check science instruments and units.
Quantities and measurements must come from printed data, never exact features of AI artwork.
BLANK WORK MATERIALS: For a half-pattern symmetry activity, use an outline of a skull,
butterfly, leaf, heart or pumpkin; Python prints a large sharp template with reference motifs
on the left and a genuinely blank decorative right half. Ask students to mirror the LEFT
patterns into the blank RIGHT half. Do not ask Cloudflare to leave a half unfinished.
Banner/papel-picado design tasks get a large, white, locally drawn blank banner with a fold
guide, not an AI picture of paper or a pre-cut completed design. Reserve the template its
own full-width image slot: symmetry 150x110mm; banner 168x95.2mm. Refer to the large blank
template on this page rather than an unspecified box above/below. Template prompts must
name their subject clearly. Decorative AI artwork may remain as separately declared assets.
No teacher guide. No answers on student pages. One consolidated final answer key.
'''
    pack = generate_creative_pack(theme, grade_band, config, source_context=context,
                                  book_title=book_title, require_variety=True)
    pack.update(book_type='varied_activities', content_format='varied_activities',
                design_engine='gemini_authored_activities')
    return pack
