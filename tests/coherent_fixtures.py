"""Provider-free canonical exercise examples for regression and print inspection."""


def authored_page(title='Garden Detectives', mechanic='design shelter'):
    """Invent a concrete open design challenge in a freely authored layout."""
    return {
        'html': '<h1 data-content="title" style="color:#167E80;background-color:#DFF4EF;padding:3mm;border-radius:4mm"></h1>'
                '<p data-content="directions"></p><img data-asset="scene" style="width:175mm;height:75mm"/>'
                '<div data-content="question_1" style="background-color:#FFF7DE;padding:3mm;border-radius:4mm"></div>',
        'images': [{'id':'scene','prompt':'A large original potted plant, a watering can and sunshine on a white backdrop, expressive friendly shapes. No text.'}],
        'exercise': {'render_mode':'authored','mechanic':mechanic,'goal':'Design a useful plant shelter.',
                     'directions':'Help a plant grow. Invent a shelter that lets sunlight reach it.',
                     'questions':[{'id':'1','prompt':'Draw your shelter. Show a way to water the plant.',
                                   'answer':'Accept a design that provides sunlight and access for watering.','space_mm':45}]}
    }


def exact_page(spec):
    """Place one exact mechanism in a large colorful freely authored panel."""
    return {'html':'<h1 data-content="title" style="color:#5F4183;background-color:#F2E8FA;padding:4mm;border-radius:4mm"></h1>'
                   '<p data-content="name"></p><div style="padding:2mm;border:1mm solid #E6AE37;border-radius:5mm">'
                   f'<img data-visual="{spec["id"]}" style="width:175mm;height:150mm"/></div>',
            'images':[], 'exercise':{'render_mode':'exact','mechanic':spec['kind'],
                                    'goal':'Practice precise visual reasoning.','visual':spec,'questions':[]}}


def visual_examples():
    """Return varied complete puzzle parameters whose answers are computable."""
    orange={'shape':'pumpkin','color':'orange','size':'large'}
    bat={'shape':'bat','color':'purple','size':'large'}
    ghost={'shape':'ghost','color':'teal','size':'large'}
    return [
        dict(id='pattern',question=1,kind='pattern',motif=[orange,bat],choices=[bat,ghost,orange]),
        dict(id='pairs',question=1,kind='matching',mode='shadow',seed=4,items=[orange,bat,ghost]),
        dict(id='sizes',question=1,kind='balance',rows=[{'left':dict(orange,size='small'),'right':orange},
                                                    {'left':bat,'right':dict(bat,size='small')}]),
        dict(id='counts',question=1,kind='count',rows=[[orange]*3,[bat]*5,[ghost]*2]),
        dict(id='trail',question=1,kind='maze',rows=5,cols=5,seed=12,tokens=3),
        dict(id='groups',question=1,kind='sort',attribute='shape',items=[orange,bat,ghost,bat,orange,ghost]),
        dict(id='changes',question=1,kind='differences',items=[orange,bat,ghost,orange],changes=[dict(index=2,field='color',value='blue')])]
