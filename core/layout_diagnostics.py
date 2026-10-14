"""Capture a bounded failed-layout replay without prompts, credentials or request headers."""
from copy import deepcopy


def build_layout_diagnostic(page: dict, label: str, font: int, area: float, attempts: list) -> dict:
    """Keep only generated exercise content and the print settings required for replay."""
    config=page.get('_recovery_config') or {}
    if not isinstance(config,dict): config={}
    allowed=('student_font_pt','minimum_text_pt','visual_area_mm2','items_per_page',
             'stimulus_limit','context_caption_limit','table_caption_limit',
             'purposeful_activity_layout','max_result','max_operand','operations')
    raw_images=page.get('images') or []
    if not isinstance(raw_images,list): raw_images=[]
    images=[{key:deepcopy(image[key]) for key in ('id','prompt') if key in image}
            for image in raw_images if isinstance(image,dict)]
    return dict(format='workbook-layout-diagnostic',version=1,label=label,
        title=page.get('_recovery_title','Layout replay'),minimum_font=font,visual_area=area,
        config={key:deepcopy(config[key]) for key in allowed if key in config},
        page=dict(html=page.get('html',''),images=images,exercise=deepcopy(page.get('exercise',{}))),
        recovery_attempts=deepcopy(attempts[-32:]))
