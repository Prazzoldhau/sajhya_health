"""Starter activities for the departments that are not physiotherapy: occupational therapy, speech therapy and behaviour therapy.

The exercise library is kept per discipline: a physiotherapist sees only the physiotherapy library, an occupational therapist only the occupational
therapy one, and so on. The physiotherapy library is the imported catalogue (exercises/fixtures/library.json). These starter sets are plain
text activities with no pictures, meant to be adapted to the child and extended in the admin (Exercises, Exercises: set the Discipline). They use
high ids so they never clash with the imported catalogue, and they are only added when missing, so edits made in the admin are kept.
"""
REGION_BASE, SUBREGION_BASE, EXERCISE_BASE = 1000, 2000, 100000
NOTE = ' Starter activity: adapt it to the person and add your own pictures or video.'

# discipline -> region -> sub-region -> [(name, type, level, sets, reps, hold seconds, description)]
LIBRARY = {
    'ot': {
        'Fine motor and hand function': {
            'Hand strength': [
                ('Therapy putty squeezes', 'Hand strengthening', 1, 3, 10, 3, 'Squeeze soft therapy putty with the whole hand, then pinch it between the thumb and each finger in turn.'),
                ('Clothes-peg pinching', 'Pinch strengthening', 1, 2, 10, 2, 'Pinch clothes pegs onto the edge of a card using the thumb and index finger, then each other finger in turn.'),
            ],
            'Dexterity and coordination': [
                ('Bead threading', 'Fine motor control', 1, 2, 10, 0, 'Thread large beads onto a string, then smaller beads as control improves. Work on a stable, well-supported seat.'),
                ('Coin and palm translation', 'In-hand manipulation', 2, 3, 8, 0, 'Pick up coins one at a time from a table, move them from the fingertips into the palm and store several, then take them out one by one.'),
                ('Pegboard patterns', 'Hand-eye coordination', 2, 2, 12, 0, 'Copy a pattern of pegs on a pegboard from a picture card; start with a few pegs and build up.'),
            ],
        },
        'Sensory processing': {
            'Touch': [
                ('Textured tray search', 'Tactile discrimination', 1, 2, 6, 0, 'Hide small objects in a tray of dry rice or beans and let the child find them by touch, naming or matching each one.'),
            ],
            'Movement and heavy work': [
                ('Wall push-ups', 'Proprioceptive input', 1, 2, 10, 0, 'Stand arm\'s length from a wall and push the chest toward the wall and away again with straight, steady arms.'),
                ('Animal walks', 'Proprioceptive input', 2, 2, 6, 0, 'Bear walk, crab walk and frog jumps across the room, with a rest between each. Stop if the child is uncomfortable.'),
            ],
        },
        'Handwriting and self-care': {
            'Handwriting readiness': [
                ('Pre-writing strokes', 'Pre-writing', 1, 2, 10, 0, 'Practise vertical and horizontal lines, circles and crosses, first in sand or on a large sheet, then on paper.'),
                ('Cutting along lines', 'Scissor skills', 2, 2, 5, 0, 'Cut along straight, then curved and zig-zag lines, holding the paper with the other hand.'),
            ],
            'Daily living skills': [
                ('Button and zip board', 'Dressing practice', 2, 3, 5, 0, 'Practise buttons, zips and snaps on a practice board before using them on clothes.'),
            ],
        },
    },
    'speech': {
        'Articulation and oral motor': {
            'Oral motor': [
                ('Tongue movements', 'Oral motor exercise', 1, 2, 10, 2, 'Stick the tongue out, then up, down and side to side, in front of a mirror, holding each position briefly.'),
                ('Lip rounding and spreading', 'Oral motor exercise', 1, 2, 10, 3, 'Alternate rounded lips (say "oo") and a wide smile (say "ee"), exaggerating each movement.'),
                ('Blowing practice', 'Breath control', 1, 3, 5, 0, 'Blow bubbles, a feather or a whistle to practise controlled breath and lip closure.'),
            ],
            'Speech sounds': [
                ('Minimal pairs', 'Sound discrimination', 2, 2, 10, 0, 'Show picture cards of word pairs that differ by one sound (for example pat and bat) and have the child listen, point and say them.'),
                ('Sound in words', 'Articulation practice', 2, 3, 10, 0, 'Practise the target sound at the start, middle and end of words using picture cards, then in short phrases.'),
            ],
        },
        'Language': {
            'Understanding and words': [
                ('Naming everyday objects', 'Vocabulary', 1, 2, 10, 0, 'Show real objects or picture cards of familiar things and encourage the child to name them.'),
                ('Following instructions', 'Receptive language', 1, 2, 8, 0, 'Give one-step, then two-step instructions ("get the cup", "put the ball in the box") and praise correct responses.'),
            ],
            'Sentences and conversation': [
                ('Expanding phrases', 'Expressive language', 2, 2, 8, 0, 'Build on what the child says by adding a word or two ("ball" becomes "big ball", then "I want the big ball").'),
                ('Turn-taking conversation', 'Social communication', 2, 2, 5, 0, 'Use a picture prompt to practise asking and answering questions in turns.'),
            ],
        },
        'Voice and fluency': {
            'Voice': [
                ('Easy breathing and humming', 'Voice exercise', 1, 3, 5, 0, 'Breathe in gently through the nose and hum out slowly on one comfortable note.'),
            ],
            'Fluency': [
                ('Slow easy speech', 'Fluency practice', 2, 2, 5, 0, 'Practise a slower speaking rate with a short pause between phrases, starting with single phrases and building up.'),
            ],
        },
    },
    'behaviour': {
        'Behaviour support': {
            'Routines and rewards': [
                ('Visual schedule', 'Routine support', 1, 1, 1, 0, 'Show the order of the day with picture cards and let the child remove or move each card when the activity is done.'),
                ('First-then board', 'Routine support', 1, 1, 5, 0, 'Show a less-liked task followed by a liked one ("first tidy up, then play") and follow through every time.'),
                ('Token reward chart', 'Positive reinforcement', 2, 1, 5, 0, 'Give a token straight away for the target behaviour; when the agreed number is collected the child chooses a reward.'),
            ],
            'Calming and self-regulation': [
                ('Smell the flower, blow the candle', 'Calming breathing', 1, 3, 5, 0, 'Breathe in slowly through the nose as if smelling a flower, then blow out slowly as if blowing a candle.'),
                ('Calm-down corner', 'Self-regulation', 2, 1, 1, 0, 'Teach the child to go to a quiet corner with calming items when upset, and practise it when they are calm first.'),
            ],
        },
        'Social skills': {
            'Interaction': [
                ('Turn-taking games', 'Social skills', 1, 2, 5, 0, 'Play simple games such as rolling a ball back and forth, saying "my turn" and "your turn".'),
                ('Greeting role play', 'Social skills', 2, 2, 5, 0, 'Practise saying hello, making eye contact and answering a greeting, taking turns being the greeter.'),
                ('Social stories', 'Social understanding', 2, 1, 1, 0, 'Read a short story about a situation (waiting, sharing, a new place) and talk about what to do.'),
            ],
        },
    },
}


def sync(region_model, subregion_model, exercise_model):
    """Add any starter activity that is missing. `*_model` are the real models, or the historical ones inside a migration."""
    region_id, sub_id, exercise_id = REGION_BASE, SUBREGION_BASE, EXERCISE_BASE
    for discipline, regions in LIBRARY.items():
        for region_name, subregions in regions.items():
            region_id += 1
            region, _ = region_model.objects.get_or_create(id=region_id, defaults={'region_name': region_name})
            for sub_name, items in subregions.items():
                sub_id += 1
                sub, _ = subregion_model.objects.get_or_create(id=sub_id, defaults={'region_fk_id': region.pk, 'sub_region_name': sub_name})
                for name, kind, level, sets, reps, hold, description in items:
                    exercise_id += 1
                    exercise_model.objects.get_or_create(id=exercise_id, defaults={
                        'sub_region_fk_id': sub.pk, 'exercise_name': name, 'exercise_type': kind, 'difficulty_level': level, 'default_sets': sets, 'default_reps': reps,
                        'hold_time_sec': hold, 'default_rest_time_sec': 30, 'exercise_description': description + NOTE, 'discipline': discipline})
