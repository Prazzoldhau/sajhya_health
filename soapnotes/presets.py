"""Suggestion lists for the SOAP form (free text is always allowed; these only speed typing up)."""

RED_FLAGS = [
    ('night_pain', 'Constant / night pain unrelieved by rest'), ('weight_loss', 'Unexplained weight loss'), ('fever', 'Fever or feeling unwell'),
    ('cancer_history', 'History of cancer'), ('trauma', 'Significant recent trauma'), ('bladder_bowel', 'Bladder / bowel change'),
    ('saddle', 'Saddle numbness'), ('neuro_deficit', 'Progressive neurological deficit'), ('cardio', 'Chest pain / breathlessness / dizziness'),
    ('steroids', 'Long-term steroid use'), ('osteoporosis', 'Osteoporosis / fragility'), ('dvt', 'Calf swelling / suspected DVT'),
]

ROM_MOVEMENTS = [
    'Cervical flexion', 'Cervical extension', 'Cervical rotation', 'Cervical side flexion', 'Thoracic rotation', 'Lumbar flexion', 'Lumbar extension',
    'Lumbar side flexion', 'Shoulder flexion', 'Shoulder abduction', 'Shoulder external rotation', 'Shoulder internal rotation', 'Elbow flexion',
    'Elbow extension', 'Forearm supination', 'Forearm pronation', 'Wrist flexion', 'Wrist extension', 'Hip flexion', 'Hip extension', 'Hip abduction',
    'Hip internal rotation', 'Hip external rotation', 'Knee flexion', 'Knee extension', 'Ankle dorsiflexion', 'Ankle plantarflexion', 'Ankle inversion', 'Ankle eversion',
]

MUSCLES = [
    'Deltoid', 'Supraspinatus', 'Infraspinatus', 'Biceps', 'Triceps', 'Wrist extensors', 'Wrist flexors', 'Grip', 'Iliopsoas', 'Gluteus maximus',
    'Gluteus medius', 'Quadriceps', 'Hamstrings', 'Tibialis anterior', 'Gastrocnemius / soleus', 'Extensor hallucis longus', 'Core / abdominals', 'Neck flexors',
]

SPECIAL_TESTS = [
    'Straight leg raise (SLR)', 'Slump test', 'Lasegue', 'FABER / Patrick', 'Thomas test', 'Ober test', 'Lachman', 'Anterior drawer (knee)', 'Posterior drawer',
    'McMurray', 'Valgus stress (knee)', 'Varus stress (knee)', 'Anterior drawer (ankle)', 'Talar tilt', 'Neer impingement', 'Hawkins-Kennedy', 'Empty can / Jobe',
    'Drop arm', 'Apprehension (shoulder)', 'Speed test', 'Spurling', 'Cervical distraction', 'ULTT median nerve', 'Phalen', 'Tinel', 'Finkelstein',
    'Trendelenburg', 'Romberg', 'Berg balance (see Assessments)', 'Timed Up and Go (see Assessments)',
]

MANUAL_GRADES = ['0', '1', '2', '3', '3+', '4-', '4', '4+', '5']
SIDES = ['', 'Left', 'Right', 'Both']
TEST_RESULTS = ['positive', 'negative', 'inconclusive']
PAIN_CHARACTERS = ['Sharp', 'Dull ache', 'Burning', 'Throbbing', 'Tingling', 'Numbness', 'Stiffness', 'Shooting']
