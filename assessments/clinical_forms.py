"""Clinical assessment forms: history-and-examination style forms (text, tick boxes, tables) that are filled in once for a patient, as opposed to the
scored scales in models.AssessmentScale. A form is data: sections of fields, kept in the database (ClinicalForm.definition) and loaded from here by
migration / `manage.py load_clinical_forms`. Every form belongs to one discipline, so an occupational therapy form never shows up under physiotherapy and
the other way round.

Field types:
  text / textarea / date        one box
  choice                        pick one of `options`
  multi                         tick any of `options` (`other`: also a free-text box labelled with that word)
  yesno                         Yes / No, plus an optional text box (`detail` is its label)
  grid                          a table: one row per item in `rows`, with `cols` of type radio (pick one of `options`), check (tick any of `options`) or text
`prefill` fills a box from the patient record (name, age, gender, diagnosis).
"""

PRESENT_ABSENT = ['Present', 'Absent']
COMMENTS = 'Comments (hypersensitive, hyposensitive or within functional limits)'


def text(key, label, **extra):
    return {'key': key, 'type': 'text', 'label': label, **extra}


def area(key, label, **extra):
    return {'key': key, 'type': 'textarea', 'label': label, **extra}


def choice(key, label, options, **extra):
    return {'key': key, 'type': 'choice', 'label': label, 'options': options, **extra}


def multi(key, label, options, **extra):
    return {'key': key, 'type': 'multi', 'label': label, 'options': options, **extra}


def yesno(key, label, detail='', **extra):
    return {'key': key, 'type': 'yesno', 'label': label, 'detail': detail, **extra}


def radio(key, options, label=''):
    return {'key': key, 'type': 'radio', 'label': label, 'options': options}


def check(key, options, label=''):
    return {'key': key, 'type': 'check', 'label': label, 'options': options}


def cell(key, label):
    return {'key': key, 'type': 'text', 'label': label}


def grid(key, label, rows, cols, row_label=''):
    return {'key': key, 'type': 'grid', 'label': label, 'rows': rows, 'cols': cols, 'row_label': row_label}


def present_absent(key, label, rows):
    return grid(key, label, rows, [radio('status', PRESENT_ABSENT), cell('comments', COMMENTS)])


PEDIATRIC_OT = {
    'code': 'ot-pediatric',
    'name': 'Paediatric occupational therapy assessment',
    'discipline': 'ot',
    'description': 'Full paediatric OT history and examination: birth and development history, motor, sensory and daily-living skills, goals and approaches.',
    'sections': [
        {'title': 'Demographic data', 'fields': [
            text('name', 'Name', prefill='name'), text('age', 'Age', prefill='age'), text('gender', 'Gender', prefill='gender'),
            text('diagnosis', 'Diagnosis', prefill='diagnosis'), text('referred_by', 'Referred by'), text('informant', 'Informant'),
            area('chief_complaints', 'Chief complaints'), area('felt_need', 'Felt need of the parent'),
        ]},
        {'title': 'Pre-natal history', 'fields': [
            choice('marriage', 'Type of marriage', ['Consanguineous', 'Non-consanguineous']),
            text('parent_age_marriage_father', 'Age of father at the time of marriage'), text('parent_age_marriage_mother', 'Age of mother at the time of marriage'),
            text('parent_age_conception_father', 'Age of father at the time of conception'), text('parent_age_conception_mother', 'Age of mother at the time of conception'),
            text('antenatal_when', 'Ante-natal care: when started'), text('antenatal_where', 'Ante-natal care: where'),
            yesno('abortion', 'History of abortion', 'Why?'),
            multi('chronic_disease', 'History of chronic disease', ['Diabetes', 'Hypertension', 'Jaundice'], other='Others'),
            yesno('fall', 'History of fall', 'Why / when?'),
            text('first_quickening', 'First quickening'), text('usg_report', 'USG report'),
            area('prenatal_other', 'Other complications during pregnancy'),
        ]},
        {'title': 'Peri-natal history', 'fields': [
            yesno('term_baby', 'Term baby', 'When / why?'),
            multi('delivery', 'Type of delivery', ['Caesarean section', 'Breech presentation', 'Forceps', 'Normal']),
            text('birth_weight', 'Birth weight'), choice('birth_cry', 'Birth cry', ['Immediately', 'Delayed']),
            yesno('birth_jaundice', 'History of jaundice immediately after birth', 'Treatment?'),
            text('appearance', 'Appearance at birth'), yesno('incubated', 'Child incubated', 'Why?'),
            area('perinatal_other', 'Other complications'),
        ]},
        {'title': 'Post-natal history', 'fields': [
            yesno('breast_feeding', 'Breast feeding', 'Why not / details'), yesno('seizures', 'History of seizures'),
            area('postnatal_other', 'Other history immediately after birth'),
        ]},
        {'title': 'Medical history', 'fields': [
            area('hospitalization', 'Any medical reason for hospitalization after delivery'),
        ]},
        {'title': 'Family history', 'fields': [
            yesno('family_similar', 'Any significant history of similar condition in the 1st and 2nd degree family', 'Details'),
            area('family_tree', 'Family tree (describe)'),
        ]},
        {'title': 'Educational history', 'fields': [
            text('edu_father', 'Level of education of father'), text('edu_mother', 'Level of education of mother'), text('edu_child', 'Level of education of child'),
        ]},
        {'title': 'Socio-economic history', 'fields': [
            area('economic', "Parent's economic status: bread winner, income etc."),
        ]},
        {'title': 'Developmental history', 'fields': [
            grid('motor_dev', 'Motor development', ['Head control', 'Rolling', 'Crawling / creeping', 'Sitting', 'Standing'],
                 [radio('status', ['Not attained', 'Attained']), cell('age', 'Age attained')], row_label='Skills'),
            grid('oral_dev', 'Oral motor development', ['Babbling', 'Monosyllabic', 'Bisyllabic', 'Two word sentences', 'More than two words'],
                 [radio('status', ['Not attained', 'Attained']), cell('age', 'Age attained')], row_label='Skills'),
        ]},
        {'title': 'On observation', 'fields': [
            area('observation', 'Child behaviour, play skill, gait pattern, physical appearance, if well groomed, etc.'),
        ]},
        {'title': 'On examination', 'fields': [
            choice('vision', 'Vision', ['Intact', 'Impaired']), text('vision_note', 'Vision: details'),
            choice('hearing', 'Hearing', ['Intact', 'Impaired']), text('hearing_note', 'Hearing: details'),
            choice('speech', 'Speech', ['Intact', 'Impaired']), text('speech_note', 'Speech: details'),
        ]},
        {'title': 'Gross motor skills', 'fields': [
            yesno('running', 'Running', 'Describe'), yesno('jumping', 'Jumping', 'Describe'), yesno('hopping', 'Hopping', 'Describe'),
            yesno('ball_skills', 'Ball throwing and catching', 'Describe'),
        ]},
        {'title': 'Fine motor skills', 'fields': [
            choice('reach', 'Reach', ['In all directions', 'In some directions or not at all']), text('reach_note', 'Reach: describe'),
            multi('grasp', 'Grasp', ['Cylindrical', 'Spherical', 'Hook']),
            multi('pinch', 'Pinch', ['Tip to tip', 'Palmar pinch', 'Lateral pinch']),
            choice('transfer', 'Transfer', ['Present', 'Absent']),
            choice('release', 'Release', ['Voluntary', 'Involuntary']),
            choice('placement', 'Placement', ['Voluntary', 'Involuntary']),
            grid('in_hand', 'In-hand manipulation', ['Translation: finger to palm', 'Translation: palm to finger', 'Shift: vertical', 'Shift: horizontal',
                                                     'Rotation: simple 180 degrees', 'Rotation: complex 360 degrees'],
                 [check('stabilization', ['With stabilization', 'Without stabilization'])], row_label='Skills'),
        ]},
        {'title': 'Proximal senses: vestibular and proprioceptive system', 'fields': [
            present_absent('vestibular', 'Vestibular and proprioceptive system', [
                'Bilateral hand use: difficulty manipulating small objects (buttons, snaps), eating in a sloppy manner',
                'Sits properly in a chair and steps off smoothly',
                'Clumsy movements, tendency to fall, lack of awareness of body position in space, odd body positioning',
                'Balance reaction: righting', 'Balance reaction: equilibrium', 'Balance reaction: protective',
                'Dyspraxia: resistance to new motor movement activities',
                'Writing (reversals), using a pencil, a spoon to drink soup, buttoning a shirt',
                'Swings, slides, ramps, inclines', 'Trouble learning to climb or descend stairs or hills',
                'Apprehensive walking or crawling on uneven or unstable surfaces', 'Excessive body whirling, jumping, running, walking and / or spinning']),
            present_absent('gravitational', 'Gravitational insecurity', ['Difficulty in walking', 'Fear of falling or heights', 'Dislikes tilting the head down or when pushed back',
                                                                         'Avoids jumping, climbing and walking on raised surfaces']),
        ]},
        {'title': 'Proximal senses: tactile', 'fields': [
            present_absent('tactile', 'Tactile perception', ['Finger identification', 'Graphesthesia', 'Localization of tactile stimuli', 'Stereognosis',
                                                             'Response to pain, pressure and temperature']),
            present_absent('tactile_defensive', 'Tactile defensive behaviour', [
                'Avoids being touched on the face', 'Avoids / feels discomfort during dental work, hair cut', 'Avoids certain textures',
                'Avoids playing in sand, finger paint, paste etc.', 'Avoids physical contact with friends, pulls away from a hug']),
            present_absent('dyspraxia', 'Developmental dyspraxia', ['Speed and initiation of motor planning', 'Body scheme / awareness', 'Emotionally sensitive and adamant']),
        ]},
        {'title': 'Distal senses: vision', 'fields': [
            present_absent('vision_skills', 'Vision', ['Visual tracking', 'Visual fixation', 'Eye contact', 'Visual closure', 'Others: nystagmus, squint']),
            present_absent('visual_perception', 'Visual perception disorder', ['Visual spatial orientation', 'Figure-ground perception', 'Colour discrimination', 'Depth perception',
                                                                              'Visual praxis', 'Shapes and forms concept', 'Writing skills', 'Eye-hand coordination']),
        ]},
        {'title': 'Distal senses: hearing, smell and taste', 'fields': [
            present_absent('auditory', 'Auditory disorder', ['Response to loud noises: mild', 'Response to loud noises: moderate', 'Seeks sounds', 'Withdraws from sound',
                                                             'Auditory discrimination', 'Other hearing problem']),
            present_absent('olfactory', 'Olfactory disorder', ['Deliberately smells objects', 'Withdraws from smell']),
            present_absent('gustatory', 'Gustatory disorder', ['Chewing or licking non-food objects', 'Craves certain food and taste', 'Tongue movement', 'Drooling']),
            present_absent('reflexes', 'Reflexes', ['Rooting', 'Sucking']),
        ]},
        {'title': 'Activities of daily living', 'fields': [
            grid('adl', 'ADL skills', ['Dressing: upper body', 'Dressing: lower body', 'Bathing', 'Toileting', 'Eating', 'Grooming', 'Bladder management', 'Bowel management'],
                 [radio('level', ['No helper', 'Helper: modified dependence', 'Helper: complete dependence'])], row_label='ADL skills'),
        ]},
        {'title': 'Pre-handwriting skills and behaviour', 'fields': [
            grid('prehandwriting', 'Pre-handwriting skills', ['Trunk, neck and shoulder', 'Shoulder and arm', 'Forearm supination', 'Wrist', 'Thumb opposition', 'Web space'],
                 [radio('status', ['Stable', 'Unstable'])], row_label='Components'),
            grid('behaviour', 'Behaviour problems', ['Adamant', 'Rigid', 'Temper tantrums', 'Disobedience', 'Head banging', 'Teeth grinding'],
                 [radio('status', PRESENT_ABSENT)], row_label='Behaviours'),
        ]},
        {'title': 'Play development', 'fields': [
            area('play', 'Classification of play and description of the level'),
        ]},
        {'title': 'Problem identification, goals and approaches', 'fields': [
            area('problems', 'Problem identification'), area('short_term_goal', 'Short term goal'), area('long_term_goal', 'Long term goal'),
            area('approaches', 'Approaches'), area('techniques', 'Techniques'),
        ]},
    ],
}

FORMS = [PEDIATRIC_OT]


def sync(model):
    """Add the shipped forms to the database, or bring an existing one up to date (raising its version when the questions changed).
    `model` is ClinicalForm, or the historical model inside a migration."""
    for spec in FORMS:
        definition = {'sections': spec['sections']}
        row = model.objects.filter(code=spec['code']).first()
        if row is None:
            model.objects.create(code=spec['code'], name=spec['name'], discipline=spec['discipline'], description=spec['description'], definition=definition)
        elif row.definition != definition:
            row.definition, row.version = definition, row.version + 1
            row.save()
