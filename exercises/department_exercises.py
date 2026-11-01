"""The exercises, activities and tools for the departments that are not physiotherapy: occupational therapy, speech therapy and behaviour therapy.

They come from the clinic reference sheets (Assessment folder: "Exercises" sheet of each workbook) and are added to each department's own exercise library, so a
therapist searches and prescribes them exactly as a physiotherapist does the physiotherapy exercises. They are text only (no pictures yet); add pictures or videos in
the admin (Exercises). Each row is
  (skill area, exercise / activity, how to do it, make it easier or harder, equipment).
`sync` adds only what is missing, so edits made in the admin are kept, and skips a name the department already has.
"""
REGION_BASE, SUBREGION_BASE, EXERCISE_BASE = 3000, 4000, 200000

# (sets, reps, hold seconds, rest seconds) suggested per skill area; the therapist changes it when prescribing
DOSES = {
    ('ot', 'Hand strength and dexterity'): (3, 10, 0, 30), ('ot', 'Pre-writing and handwriting'): (2, 5, 0, 30), ('ot', 'Bilateral and midline'): (2, 10, 0, 30),
    ('ot', 'Visual perception and visual motor'): (1, 5, 0, 30), ('ot', 'Posture, core and gross motor'): (3, 8, 0, 30), ('ot', 'Sensory regulation'): (2, 5, 0, 30),
    ('ot', 'Self-care'): (1, 3, 0, 30), ('ot', 'Cognition and attention'): (1, 5, 0, 30), ('ot', 'Play and social'): (1, 5, 0, 30), ('ot', 'Neurological conditions'): (3, 10, 0, 30),
    ('speech', 'Oral motor'): (3, 10, 2, 30), ('speech', 'Articulation'): (3, 10, 0, 30), ('speech', 'Language'): (2, 10, 0, 30), ('speech', 'Communication and AAC'): (2, 5, 0, 30),
    ('speech', 'Fluency'): (2, 5, 0, 30), ('speech', 'Voice'): (3, 5, 0, 30), ('speech', 'Feeding and swallowing'): (1, 3, 0, 60), ('speech', 'Hearing and listening'): (1, 5, 0, 30),
    ('speech', 'Early reading'): (2, 10, 0, 30),
    ('behaviour', 'Assessing behaviour'): (1, 1, 0, 0), ('behaviour', 'Rewards and praise'): (1, 5, 0, 0), ('behaviour', 'Preventing problems'): (1, 1, 0, 0),
    ('behaviour', 'Replacement skills'): (1, 5, 0, 0), ('behaviour', 'Calming and self-regulation'): (3, 5, 0, 30), ('behaviour', 'Social skills'): (1, 5, 0, 0),
    ('behaviour', 'Following instructions'): (1, 5, 0, 0), ('behaviour', 'Daily routines'): (1, 1, 0, 0), ('behaviour', 'Habits and tics'): (2, 5, 0, 30),
    ('behaviour', 'Anxiety and fears'): (1, 3, 0, 0), ('behaviour', 'Teaching new skills'): (1, 10, 0, 0), ('behaviour', 'Family'): (1, 1, 0, 0),
}
DEFAULT_DOSE = (2, 10, 0, 30)
HARDER = {('behaviour', 'Teaching new skills'), ('behaviour', 'Anxiety and fears')}  # a step up for the more skilled tools


OT = [
    ('Hand strength and dexterity', 'Therapy putty squeeze and pinch', 'Roll putty into a ball, squeeze with the whole hand, then pinch with the thumb and each finger in turn. Hide beads in the putty and find them.', 'Easier: soft putty. Harder: firmer putty, fewer fingers.', 'Therapy putty, small beads'),
    ('Hand strength and dexterity', 'Clothes-peg pinch', 'Pinch pegs onto the edge of a card or box and take them off again; use the thumb with each finger in turn.', 'Easier: loose pegs. Harder: stiffer pegs, timed.', 'Clothes pegs, card'),
    ('Hand strength and dexterity', 'Tongs and tweezers transfer', 'Move pom-poms, beans or cotton balls from one bowl to another using tongs, then tweezers.', 'Easier: large tongs, big items. Harder: tweezers, small items, sort by colour.', 'Tongs, tweezers, bowls, pom-poms'),
    ('Hand strength and dexterity', 'Sponge squeeze relay', 'Soak a sponge, carry it and squeeze the water into a second bowl until it is full.', 'Easier: small damp sponge. Harder: large sponge, use one hand only.', 'Sponges, two bowls, water'),
    ('Hand strength and dexterity', 'Spray bottle game', 'Spray water to water plants, knock over light cups or "paint" a wall with water.', 'Easier: trigger sprayer with light spring. Harder: use each hand, aim at small targets.', 'Spray bottle, cups'),
    ('Hand strength and dexterity', 'Play dough rolling, pinching and cutting', 'Roll snakes and balls, pinch small pieces, press shapes with cutters, cut with a plastic knife.', 'Easier: soft dough. Harder: firmer dough, hide objects inside.', 'Play dough, cutters, plastic knife'),
    ('Hand strength and dexterity', 'Paper tearing and scrunching', 'Tear paper into pieces to make a collage; scrunch paper into balls with one hand.', 'Easier: thin paper. Harder: thicker paper, one hand only.', 'Coloured paper, glue'),
    ('Hand strength and dexterity', 'Bead threading and lacing cards', 'Thread large beads on a string, then smaller beads; lace a card or sew with a blunt needle.', 'Easier: big beads, stiff lace. Harder: small beads, patterns to copy.', 'Beads, laces, lacing cards'),
    ('Hand strength and dexterity', 'Pegboard patterns', 'Copy a pattern of pegs from a picture card.', 'Easier: few pegs. Harder: more pegs, patterns from memory.', 'Pegboard, pegs, pattern cards'),
    ('Hand strength and dexterity', 'Finger isolation games', 'Finger puppets, finger piano on the table, tapping each finger to the thumb, pointing to pictures with one finger.', 'Easier: whole-hand tapping. Harder: tap in sequence, eyes closed.', 'Finger puppets'),
    ('Hand strength and dexterity', 'Pushing pins into foam', 'Push thumb-pins or golf tees into a foam board to make a picture.', 'Easier: big tees. Harder: small pins, follow a pattern.', 'Foam board, pushpins, tees'),
    ('Hand strength and dexterity', 'Coin collecting (in-hand manipulation)', 'Pick up coins one at a time and store several in the palm; then drop them into a bank one by one.', 'Easier: large coins or tokens. Harder: store more, no help from the other hand.', 'Coins, piggy bank'),
    ('Pre-writing and handwriting', 'Vertical surface drawing', 'Draw or paint on an easel or paper taped to the wall to build wrist and shoulder stability.', 'Easier: large crayons, big strokes. Harder: smaller shapes, letters.', 'Easel or wall, chalk, crayons'),
    ('Pre-writing and handwriting', 'Shaving foam or sand writing', 'Practise lines, circles and letters with a finger in foam or a sand tray, then with a stick.', 'Easier: whole-hand then finger. Harder: copy letters from a card.', 'Tray, shaving foam or sand'),
    ('Pre-writing and handwriting', 'Pre-writing shapes and mazes', 'Draw vertical and horizontal lines, circles, crosses, squares and triangles; follow mazes and join dots.', 'Easier: trace thick lines. Harder: copy from memory, smaller shapes.', 'Worksheets, markers'),
    ('Pre-writing and handwriting', 'Playdough letters and sky writing', 'Make letters from dough snakes, then write them in the air with a big arm movement before writing on paper.', 'Easier: big letters. Harder: a whole name.', 'Play dough'),
    ('Pre-writing and handwriting', 'Cutting progression', 'Snip fringes, cut along straight then curved lines, then zig-zags and shapes, holding the paper with the helper hand.', 'Easier: thick card. Harder: curves and small shapes.', 'Child scissors, paper, thick card'),
    ('Bilateral and midline', 'Drum patterns', 'Copy a drum or clapping pattern with both hands, then alternate hands.', 'Easier: both together. Harder: alternate, cross the middle.', 'Drum or tabletop'),
    ('Bilateral and midline', 'Figure-eight drawing', 'Draw a large figure of eight on big paper or a board, following it with the eyes.', 'Easier: trace over. Harder: draw from memory with each hand.', 'Large paper, markers'),
    ('Bilateral and midline', 'Cross-midline reaching', 'Reach across the body to place cups or cards on the opposite side; windmill touches (hand to opposite foot).', 'Easier: sitting. Harder: standing, quickly.', 'Cups, cards'),
    ('Bilateral and midline', 'Bean-bag toss', 'Throw bean bags at a target, passing them from hand to hand first.', 'Easier: large target near. Harder: small target, further away.', 'Bean bags, target'),
    ('Visual perception and visual motor', 'Puzzles', 'Do puzzles from 4 pieces up to 24 or more, first with outline boards.', 'Easier: knob puzzle. Harder: more pieces, no picture guide.', 'Puzzles'),
    ('Visual perception and visual motor', 'Hidden pictures and I-spy', 'Find hidden objects in busy pictures or around the room.', 'Easier: few, big items. Harder: busy pictures, timed.', 'Picture books, I-spy cards'),
    ('Visual perception and visual motor', 'Copy a block design or peg pattern', 'Copy a pattern from a card with blocks or pegs.', 'Easier: two blocks. Harder: patterns in 3D.', 'Blocks, pattern cards'),
    ('Visual perception and visual motor', 'Sorting and matching shapes and colours', 'Sort objects by shape, colour or size, then match pairs.', 'Easier: two categories. Harder: more categories or combined rules.', 'Shape sorters, cards'),
    ('Visual perception and visual motor', 'Eye tracking games', 'Follow a pen, torch or bubbles with the eyes only, without moving the head.', 'Easier: slow, large movements. Harder: faster, in diagonals.', 'Pen torch, bubbles'),
    ('Visual perception and visual motor', 'Balloon and ball tracking', 'Keep a balloon up, then catch a soft ball with both hands.', 'Easier: balloon. Harder: smaller ball, one hand.', 'Balloon, soft balls'),
    ('Posture, core and gross motor', 'Wheelbarrow walk', 'Walk on the hands while an adult holds the legs; move a short distance, then rest.', 'Easier: hold at the thighs. Harder: hold at the ankles, longer.', 'Open floor'),
    ('Posture, core and gross motor', 'Animal walks', 'Bear, crab, frog and snake walks across the room.', 'Easier: short distance. Harder: races, obstacles.', 'Open floor'),
    ('Posture, core and gross motor', 'Prone on elbows play', 'Lie on the tummy on elbows to play, read or build with blocks.', 'Easier: short time with support. Harder: reaching for toys.', 'Mat, toys'),
    ('Posture, core and gross motor', 'Balance beam and stepping stones', 'Walk along a line, beam or stepping stones with arms out.', 'Easier: wide, low beam. Harder: carry an object, walk backwards.', 'Beam or tape, stepping stones'),
    ('Posture, core and gross motor', 'Sitting on a therapy ball', 'Sit on a ball with feet on the floor and play a seated game.', 'Easier: with hand support. Harder: lift a foot, throw and catch.', 'Therapy ball'),
    ('Posture, core and gross motor', 'Hopscotch and jumping', 'Jump with two feet, then hop on one foot through a hopscotch grid.', 'Easier: two-foot jumps. Harder: hop on one foot, add numbers.', 'Chalk or tape'),
    ('Posture, core and gross motor', 'Obstacle course', 'Crawl under, climb over, walk along and jump into a course set up with cushions and tunnels.', 'Easier: three stations. Harder: more steps in order, timed.', 'Cushions, tunnel, mats'),
    ('Sensory regulation', 'Textured tray treasure hunt', 'Hide small objects in rice, beans or sand and find them by touch, naming each one.', 'Easier: eyes open, large objects. Harder: eyes closed, small objects.', 'Tray, rice or beans, small toys'),
    ('Sensory regulation', 'Deep-pressure squeeze', 'Squeeze the child between two cushions (a cushion sandwich) or roll in a blanket, with the child directing how firm and how long.', 'Always stop when the child asks; keep the head and face clear.', 'Cushions, blanket'),
    ('Sensory regulation', 'Heavy work tasks', 'Carry a laundry basket, push a loaded box, pull a wagon, help with shopping bags.', 'Easier: light loads. Harder: heavier loads, longer distance.', 'Basket, box, wagon'),
    ('Sensory regulation', 'Wall push-ups', "Stand an arm's length from a wall and push the chest toward the wall and away again.", 'Easier: fewer repeats. Harder: slow and held for 5 seconds.', 'Wall'),
    ('Sensory regulation', 'Slow linear swinging', 'Swing slowly forward and back on a platform swing, feet reaching the ground if needed.', 'Easier: low and slow. Harder: add a game or longer time.', 'Platform swing'),
    ('Sensory regulation', 'Trampoline or bouncing', 'Bounce on a trampoline or therapy ball in short bursts between table tasks.', 'Easier: sitting on the ball. Harder: counting jumps, jumping jacks.', 'Small trampoline, ball'),
    ('Sensory regulation', 'Crawling through tunnels', 'Crawl through tunnels and under tables to get to an object.', 'Easier: short, wide tunnel. Harder: longer, twisty.', 'Tunnel, tables'),
    ('Sensory regulation', 'Messy play, graded', 'Start with dry textures, then damp, then wet; finger paint with a brush before the hands.', 'Easier: tools first. Harder: bare hands.', 'Paint, foam, sand'),
    ('Sensory regulation', 'Oral sensory play', 'Blow bubbles, whistles and pinwheels; chew on a chewy tube during table tasks.', 'Easier: short blowing. Harder: longer, with a target.', 'Bubbles, whistles, chewy tube'),
    ('Sensory regulation', 'Calming breathing', '"Smell the flower, blow the candle": breathe in through the nose and blow out slowly.', 'Easier: with a pinwheel. Harder: count to five on the out-breath.', 'Pinwheel, picture cards'),
    ('Sensory regulation', 'Quiet corner', 'Set up a quiet, dim space with cushions and calming items that the child chooses to use.', 'Practise using it when calm, so it works when upset.', 'Cushions, soft lights, books'),
    ('Self-care', 'Dressing board and buttons', 'Practise buttons, zips, snaps and buckles on a board, then on clothes.', 'Easier: large buttons. Harder: small buttons on own clothes.', 'Dressing board or frames'),
    ('Self-care', 'Backward chaining for dressing', 'The adult does all the steps except the last one (for example pulling a sock over the heel); the child does that last step, then the last two.', 'Add one more step each time success is steady.', 'Own clothes'),
    ('Self-care', 'Spoon scooping and pouring', 'Scoop beans or rice with a spoon between bowls; pour from a small jug into a cup (dry first, then water).', 'Easier: wide bowl, dry beans. Harder: water, a full cup.', 'Spoons, bowls, jug'),
    ('Self-care', 'Tooth-brushing and hand-washing sequence cards', 'Use picture cards to follow the steps in order.', 'Easier: adult points. Harder: child follows the cards alone.', 'Picture cards'),
    ('Self-care', 'Shoe tying practice', 'Practise on a large board or a shoe with thick laces, with a rhyme for each step.', 'Easier: bunny-ears method with coloured laces. Harder: normal laces on the foot.', 'Laces, practice shoe'),
    ('Self-care', 'Toilet routine with pictures', 'Follow a picture sequence for each toilet visit.', 'Easier: adult prompts each step. Harder: child follows pictures alone.', 'Picture cards'),
    ('Cognition and attention', 'Sequencing cards', 'Put picture cards in the right order and tell the story.', 'Easier: three cards. Harder: six or more.', 'Sequencing cards'),
    ('Cognition and attention', 'Memory and matching games', 'Play pairs (memory) games and "what is missing" with a tray of objects.', 'Easier: few items. Harder: more items, shorter time.', 'Memory cards, tray'),
    ('Cognition and attention', 'Simon says and freeze games', 'Follow instructions, stop on a signal and wait for the next.', 'Easier: one step. Harder: two or three steps.', 'None'),
    ('Cognition and attention', 'Visual timer and checklist', 'Use a visual timer and a picture checklist for a task, ticking each step off.', 'Easier: three steps. Harder: the child makes the list.', 'Timer, checklist'),
    ('Play and social', 'Board games and turn-taking', 'Simple board or card games to practise waiting, taking turns, winning and losing.', 'Easier: two players, short game. Harder: group games.', 'Board games'),
    ('Play and social', 'Pretend play and dress-up', 'Play shop, doctor or kitchen, with the adult joining in and extending the story.', 'Easier: adult models. Harder: the child plans the scene.', 'Dress-up clothes, play sets'),
    ('Play and social', 'Cooperative building', 'Build a tower or model together, each adding a piece in turn.', 'Easier: pairs. Harder: small group with a shared plan.', 'Blocks'),
    ('Play and social', 'Emotion puppets and faces', 'Match faces to feelings and use puppets to act out how to cope.', 'Easier: happy and sad. Harder: more feelings and what helps.', 'Puppets, feelings cards'),
    ('Neurological conditions', 'Weight-bearing through the hands', 'Crawling, wheelbarrow walking or leaning on the hands while playing.', 'Easier: short and supported. Harder: longer, add reaching.', 'Mat, toys'),
    ('Neurological conditions', 'Reach and release with the weaker hand', 'Stack cups, place rings on a post or drop blocks into a tub with the weaker hand.', 'Easier: large objects. Harder: smaller objects, higher target.', 'Cups, rings, blocks'),
    ('Neurological conditions', 'Two-handed play', 'Games that need both hands: drumming, ball rolling, tearing paper, clapping songs.', 'Easier: hand-over-hand help. Harder: independent, different movements for each hand.', 'Drum, paper'),
    ('Neurological conditions', 'Hand-opening play', 'Finger-paint with an open hand, press play dough flat, roll a ball with an open palm.', 'Easier: with a gentle stretch first. Harder: longer, against resistance.', 'Paint, dough'),
]

SPEECH = [
    ('Oral motor', 'Tongue movements in a mirror', 'Stick the tongue out, up to the nose, down to the chin, and side to side, holding each for 2 seconds.', 'Easier: copy the adult. Harder: faster, in a sequence.', 'Mirror'),
    ('Oral motor', 'Lick the lips game', 'Put a little jam or yoghurt on the top lip, upper and lower, and lick it off (check for allergies).', 'Easier: lower lip. Harder: corners of the mouth.', 'Jam or yoghurt, spoon'),
    ('Oral motor', 'Lip stretches: "ee" and "oo"', 'Alternate a wide smile and a rounded kiss, saying "ee" and "oo".', 'Easier: slow. Harder: faster, then add "ee-oo-ee" sound.', 'Mirror'),
    ('Oral motor', 'Cheek puff and suck in', 'Puff out both cheeks and hold, move the air from side to side, then suck the cheeks in.', 'Easier: hold 2 seconds. Harder: hold 5 seconds, move the air.', 'None'),
    ('Oral motor', 'Straw blowing races', 'Blow a cotton ball or a feather along the table with a straw, or blow bubbles in a drink.', 'Easier: big cotton ball, short race. Harder: longer track, around obstacles.', 'Straw, cotton ball, cup'),
    ('Oral motor', 'Bubbles, whistle and pinwheel', 'Blow bubbles, a whistle or a pinwheel to practise a firm lip seal and steady breath.', 'Easier: short blows. Harder: long steady blows.', 'Bubbles, whistle, pinwheel'),
    ('Oral motor', 'Straw drinking', 'Drink a thick drink through a straw, then a thinner one.', 'Easier: short straw, thick drink. Harder: thin drink, longer straw.', 'Straws, cup'),
    ('Oral motor', 'Monster mouth', 'Open the mouth wide and close slowly, chomp like a monster, say "ah" and close with "m".', 'Easier: slow. Harder: faster, with sounds.', 'Mirror'),
    ('Articulation', 'Listening for the target sound', 'Read a short list of words that have the target sound and have the child clap or hold up a card when they hear it.', 'Easier: sound at the start of words. Harder: in the middle and end.', 'Word lists, cards'),
    ('Articulation', 'Lip sounds /p b m/', 'Say "pop pop pop", "bubble", "mmm" with a mirror, feeling the lips close.', 'Easier: sound alone. Harder: in words and phrases.', 'Mirror, bubbles'),
    ('Articulation', 'Tongue-tip sounds /t d n/', 'Feel the tongue tip tap behind the top teeth: "tick tock", "dad", "nose".', 'Easier: single sound. Harder: words with several.', 'Mirror, picture cards'),
    ('Articulation', 'Back sounds /k g/', 'Practise the sound at the back of the mouth: "cough", "gulp", "car", "go".', 'Easier: with the tongue held down by the adult as a cue. Harder: words and phrases.', 'Mirror, tongue depressor or spoon'),
    ('Articulation', '/s z/ snake sound', 'Make the snake sound with teeth together and tongue behind them, then in "sun", "bus", "zoo".', 'Easier: sound alone. Harder: s-clusters (spoon, stop).', 'Mirror, picture cards'),
    ('Articulation', '/sh ch/ quiet and train sounds', 'Say "shhh" for quiet and "ch ch" for a train, then in words.', 'Easier: sound alone. Harder: in sentences.', 'Picture cards'),
    ('Articulation', '/l/ sound practice', 'Touch the tongue tip behind the top teeth and sing "la la la", then use it in words.', 'Easier: "la" song. Harder: words with l in different positions.', 'Mirror, songs'),
    ('Articulation', '/r/ sound practice', 'Growl like a tiger, pulling the tongue back; then "car", "rabbit", "red".', 'Easier: sound alone. Harder: r-blends (tree, green).', 'Mirror, picture cards'),
    ('Articulation', 'Syllable repetition: pa-ta-ka', 'Repeat "pa-pa-pa", then "pa-ta-ka" quickly and clearly.', 'Easier: one syllable. Harder: longer sequences, faster.', 'None'),
    ('Articulation', 'Minimal pairs cards', 'Show picture pairs that differ by one sound (key and tea) and have the child say or point to the one named.', 'Easier: listen only. Harder: say both clearly.', 'Minimal pair cards'),
    ('Articulation', 'Picture cards at start, middle and end', 'Practise the sound in words, sorting cards by where the sound is.', 'Easier: start of words. Harder: end of words.', 'Picture cards'),
    ('Articulation', 'Carrier phrases', 'Use "I see a ___" or "I want a ___" with target words to move practice into sentences.', 'Easier: set phrase, target word only. Harder: child makes own sentence.', 'Picture cards'),
    ('Articulation', 'Sound spy conversation', 'Five minutes of talk where the child tries to spot and use the target sound; the adult gives a point for each good sound.', 'Easier: while looking at pictures. Harder: free conversation.', 'Score chart'),
    ('Articulation', 'Listen to my own voice', 'Record the child saying the words and listen back together, deciding "good" or "try again".', 'Easier: adult decides. Harder: child judges alone.', 'Phone or recorder'),
    ('Language', 'Narrate play: self-talk and parallel talk', 'Say what you are doing and what the child is doing in short sentences while playing.', 'Easier: one or two words. Harder: longer sentences.', 'Toys'),
    ('Language', 'Choice-making', 'Offer two choices ("juice or milk?") and wait for any sound, word or point.', 'Easier: show the items. Harder: ask without showing.', 'Real objects, pictures'),
    ('Language', 'Expanding what the child says', 'Repeat the child\'s words and add one: "ball" becomes "big ball", "red ball".', 'Easier: add one word. Harder: add a verb and a place.', 'Toys, books'),
    ('Language', 'Dialogic picture-book reading', 'Point, name and ask a question on each page; let the child tell what they see.', 'Easier: name and point. Harder: "what will happen next?"', 'Picture books'),
    ('Language', 'Feely bag naming', 'Put objects in a bag; the child feels one, guesses and names it.', 'Easier: two objects. Harder: describe it before naming.', 'Cloth bag, objects'),
    ('Language', 'Category sorting', 'Sort animals, foods and clothes into groups and name the groups.', 'Easier: two groups. Harder: more groups, say what does not belong.', 'Toys, cards'),
    ('Language', 'Treasure hunt with directions', 'Give one-, two- and three-step instructions to find hidden items.', 'Easier: one step. Harder: three steps with position words.', 'Hidden objects'),
    ('Language', 'Action verbs', 'Act out and name actions: jump, sleep, eat, wash; the child copies and guesses.', 'Easier: copy only. Harder: say the full sentence "he is jumping".', 'Action cards'),
    ('Language', 'Describing game (I spy)', 'Describe an object by colour, size and use; the other guesses it.', 'Easier: one clue. Harder: three clues.', 'Objects'),
    ('Language', 'Sentence building cards', 'Use colour-coded cards for who, doing, what and where to build sentences.', 'Easier: two cards. Harder: four cards, then own sentences.', 'Sentence cards'),
    ('Language', 'Story sequencing and retell', 'Order picture cards and tell the story, then retell it without the pictures.', 'Easier: three cards. Harder: five or more, with time words.', 'Sequencing cards'),
    ('Language', 'Wh-question games', 'Draw a card and answer who, what, where, when or why about a picture.', 'Easier: who and what. Harder: why and how.', 'Question cards'),
    ('Language', 'Songs and action rhymes', 'Sing action songs and rhymes in the home language and the school language.', 'Easier: copy the actions. Harder: fill in the missing word.', 'None'),
    ('Language', 'Pretend play: shop and kitchen', 'Play shop or cooking and use the words for items, quantities and requests.', 'Easier: adult leads. Harder: child sets up and directs.', 'Play sets'),
    ('Language', 'Word-finding cues', 'When stuck, practise the strategies: describe it, give the first sound, say the category.', 'Easier: adult cues. Harder: child uses a strategy alone.', 'Picture cards'),
    ('Language', 'Concept words', 'Practise under, over, before, after, big and small with objects and instructions.', 'Easier: demonstrate. Harder: follow without demonstration.', 'Toys'),
    ('Communication and AAC', 'Peekaboo and turn-taking games', 'Peekaboo, rolling a ball back and forth, and building a tower in turns to practise eye contact and taking turns.', 'Easier: adult leads. Harder: child starts the turn.', 'Ball, blocks'),
    ('Communication and AAC', 'Joint attention play', 'Point to interesting things and look at them together; use bubbles with "more" and "stop".', 'Easier: pointing to near objects. Harder: following a distant point.', 'Bubbles, toys'),
    ('Communication and AAC', 'Choice board', 'Use a board with photos of favourite items; the child touches or points to choose.', 'Easier: two pictures. Harder: more pictures.', 'Photo board'),
    ('Communication and AAC', 'Picture exchange (PECS) first step', 'Hand a picture of a favourite item to the adult to get it; a second adult helps with the hand at first.', 'Move on to choosing among pictures and building sentences.', 'Picture cards, favourite items'),
    ('Communication and AAC', 'Core vocabulary board', 'Use a board with common words: want, more, stop, help, go, finished; model them during daily routines.', 'Easier: three words. Harder: add action and place words.', 'Core word board'),
    ('Communication and AAC', 'Simple signs', 'Teach signs for more, eat, drink, finished with speech each time.', 'Easier: one sign. Harder: sign and word together.', 'None'),
    ('Communication and AAC', 'Conversation cards', 'Pick a topic card and take turns saying and asking something about it.', 'Easier: two turns. Harder: stay on topic for five turns.', 'Topic cards'),
    ('Communication and AAC', 'Role-play greetings and requests', 'Practise saying hello, asking for help and saying thank you in play situations.', 'Easier: with a script. Harder: in real situations.', 'Puppets'),
    ('Communication and AAC', 'Feelings cards', 'Match faces to feelings and say "I feel ___" and what helps.', 'Easier: happy and sad. Harder: more feelings and how to cope.', 'Feelings cards'),
    ('Fluency', 'Easy start words', 'Take a slow breath and start the word gently ("soft start") without pushing.', 'Easier: single words. Harder: phrases and sentences.', 'None'),
    ('Fluency', 'Turtle talk', 'Practise slow, stretched speech for short phrases, then go back to normal speed.', 'Easier: copy the adult. Harder: in conversation.', 'Turtle toy'),
    ('Fluency', 'Pausing phrases', 'Read a short text with slash marks at pauses and take a breath at each one.', 'Easier: short text. Harder: free speech with pauses.', 'Marked text'),
    ('Fluency', 'Calm family turn-taking', "At meals, let each person finish before the next speaks, and wait without finishing the child's sentences.", 'Practise daily; the whole family joins.', 'None'),
    ('Fluency', 'Short daily smooth-speech time', 'Five to ten minutes of relaxed play talk each day where the parent praises smooth speech and does not correct stutters.', 'Easier: play-based. Harder: during daily routines.', 'Toys, books'),
    ('Voice', 'Straw phonation', 'Hum through a straw into a cup of water, making gentle bubbles.', 'Easier: short hum. Harder: glide up and down.', 'Straw, cup of water'),
    ('Voice', 'Volume ladder', 'Use a picture ladder of quiet to loud voices and match the voice to the place (library, playground).', 'Easier: two levels. Harder: five levels.', 'Picture ladder'),
    ('Voice', 'Belly breathing', 'Lie down with a toy on the tummy and make it rise and fall with slow breaths.', 'Easier: lying down. Harder: sitting, then speaking on one breath.', 'Soft toy'),
    ('Voice', 'Voice care habits', 'Drink water, avoid shouting and use a quiet voice; reward with a daily chart.', 'Easier: one habit. Harder: all habits for a week.', 'Chart, water bottle'),
    ('Voice', 'Phrase on one breath', 'Say short phrases in one breath, then longer ones (useful for weak speech such as in cerebral palsy).', 'Easier: three words. Harder: a full sentence.', 'Picture cards'),
    ('Feeding and swallowing', 'Safe mealtime position', 'Sit upright with hips, knees and feet supported, at a good table height, calm and without distraction.', 'Check before every meal; adjust seating.', 'Supportive chair, foot rest'),
    ('Feeding and swallowing', 'Open cup drinking practice', 'Teach sips from a small open cup with a little liquid at a time, as advised for the child.', 'Easier: straw or spouted cup. Harder: open cup.', 'Small cups'),
    ('Feeding and swallowing', 'Chewing practice', 'Offer soft solids on the side teeth, or a safe chewy item, only as advised after a feeding assessment.', 'Easier: soft foods. Harder: firmer textures.', 'Safe chewy tool'),
    ('Feeding and swallowing', 'Gentle oral touch', 'Touch the cheeks, lips and gums with a soft toy or finger before eating to prepare the mouth (with professional advice).', 'Easier: face only. Harder: inside the mouth gradually.', 'Soft brush or toy'),
    ('Feeding and swallowing', 'Steps to eating a new food', 'Move from looking, touching, smelling, licking and tasting to eating, never forcing.', "Go at the child's pace; celebrate each step.", 'New foods'),
    ('Hearing and listening', 'Sound awareness walk', 'Walk around and name each sound (bird, horn, water, voices), pointing to where it comes from.', 'Easier: loud sounds. Harder: quiet or far sounds.', 'None'),
    ('Hearing and listening', 'Shaker-box matching', 'Match pairs of shaker boxes by sound, then guess loud or soft, near or far.', 'Easier: very different sounds. Harder: similar sounds.', 'Shaker boxes'),
    ('Hearing and listening', 'Hearing-aid care routine', 'Check, clean and fit the aid at the same time each day, and teach the child to tell when it is not working.', 'Easier: adult does it. Harder: child checks it alone.', 'Hearing aid kit'),
    ('Early reading', 'Syllable clapping and rhyme games', 'Clap the syllables in names and words; find words that rhyme.', 'Easier: syllables. Harder: first sounds and rhyme judgement.', 'Picture cards'),
    ('Early reading', 'Letter-sound cards and blending', 'Say the letter sounds and blend them to read simple words (c-a-t).', 'Easier: two-letter words. Harder: longer words.', 'Letter cards'),
]

BEHAVIOUR = [
    ('Assessing behaviour', 'ABC chart (before, behaviour, after)', 'Write down, each time it happens: what happened just before, exactly what the child did, and what happened straight after. Do it for one to two weeks.', 'Easier: only the worst episodes. Harder: every episode, with time and place.', 'Notebook or printed chart'),
    ('Assessing behaviour', 'Counting how often and how long', 'Tally how many times the behaviour happens each day and time the longest episodes, to see if it improves.', 'Easier: one period of the day. Harder: the whole day, graphed weekly.', 'Tally sheet, timer'),
    ('Assessing behaviour', 'Times and places chart', 'Mark on a grid when the behaviour happens across the day to find patterns (hunger, tiredness, demands).', 'Fill in daily for a week.', 'Chart'),
    ('Assessing behaviour', 'Reward preference check', 'Offer a choice of items and activities and note which the child picks, to find what works as a reward.', 'Repeat every few weeks because likes change.', 'Items to choose from'),
    ('Rewards and praise', 'Specific praise', 'Say exactly what was good ("thank you for putting the shoes away") straight after it happens.', 'Easier: aim for 5 praises for every correction. Harder: fade to occasional praise.', 'None'),
    ('Rewards and praise', 'Sticker or token chart', 'Give a sticker or token straight after the target behaviour; a set number earns a chosen reward.', 'Easier: reward after 2 tokens. Harder: 5 or more tokens.', 'Chart, stickers, rewards'),
    ('Rewards and praise', 'Reward menu', 'A picture menu of rewards the child can choose from when they have earned them.', 'Easier: three rewards. Harder: bigger rewards for longer goals.', 'Menu cards'),
    ('Rewards and praise', 'First-then board', 'Show a less-liked task, then the liked activity that follows ("first tidy up, then play").', 'Easier: very short task. Harder: longer or two tasks.', 'Board, pictures'),
    ('Rewards and praise', 'Catch them being good', "Notice and name good behaviour at least three times a day, especially in the child's hard times.", 'Keep a daily count.', 'None'),
    ('Rewards and praise', 'Daily report card', 'The teacher marks two or three agreed behaviours each day; reward at home for meeting the goal.', 'Easier: one goal. Harder: more goals, only some days rewarded.', 'Card'),
    ('Preventing problems', 'Visual schedule', 'Show the order of the day or a task with picture cards; the child moves a card when each step is done.', 'Easier: three cards. Harder: whole day.', 'Picture cards, strip'),
    ('Preventing problems', 'Visual timer and countdown', 'Use a visual timer and warnings (5 minutes, 2 minutes, 1 minute) before a change.', 'Easier: one warning. Harder: several warnings, then no warning.', 'Visual timer'),
    ('Preventing problems', 'Offering choices', 'Give two acceptable choices instead of a command ("blue cup or red cup?").', 'Easier: two choices. Harder: choices inside a routine.', 'None'),
    ('Preventing problems', 'Pre-correction before going out', 'Before a place, say the rules, the job, and the reward in a few words and ask the child to repeat them.', 'Easier: one rule. Harder: several rules.', 'Rule card'),
    ('Preventing problems', 'Simple, clear instructions', 'Use short, calm instructions, one step at a time, with a gesture or picture.', 'Easier: one step. Harder: two steps.', 'None'),
    ('Preventing problems', 'Adjusting the environment', 'Reduce noise and clutter, give a quiet spot and plan tasks for when the child is rested and fed.', 'Test one change at a time.', 'None'),
    ('Replacement skills', 'Break card practice', 'Teach the child to give a "break" card to get a short, planned rest; practise when calm and honour it every time.', 'Easier: break always given. Harder: ask to wait a moment.', 'Break card'),
    ('Replacement skills', 'Help card and asking nicely', 'Teach a card, word or sign for "help", "more", "stop" and respond at once.', 'Easier: prompt the child. Harder: child asks without prompts.', 'Picture cards'),
    ('Replacement skills', 'Waiting card', 'Show a "wait" card with a timer for a short time and reward waiting calmly.', 'Easier: 10 seconds. Harder: several minutes.', 'Wait card, timer'),
    ('Replacement skills', 'Practising calm requests', 'Role play asking for things with the right words and receiving them straight away.', 'Easier: the adult leads. Harder: in real situations.', 'Puppets'),
    ('Calming and self-regulation', 'Balloon (belly) breathing', 'Imagine a balloon in the tummy: breathe in slowly to blow it up, out slowly to let it down.', 'Easier: with a pinwheel. Harder: count to 5 for each breath.', 'Pinwheel or picture'),
    ('Calming and self-regulation', 'Calm-down corner', 'A quiet space with cushions and calming items the child chooses; practise using it when calm.', 'Easier: with an adult. Harder: the child goes alone.', 'Cushions, soft toys, books'),
    ('Calming and self-regulation', 'Feelings thermometer', 'A picture scale from calm to very upset; the child points to where they are and picks a coping step for that level.', 'Easier: three levels. Harder: five levels.', 'Thermometer poster'),
    ('Calming and self-regulation', 'Five senses grounding', 'Name five things seen, four touched, three heard, two smelled and one tasted.', 'Easier: three senses. Harder: all five.', 'None'),
    ('Calming and self-regulation', 'Tense and relax muscles', 'Squeeze fists and shoulders hard for a few seconds, then let go; move through the body.', 'Easier: hands only. Harder: whole body.', 'None'),
    ('Calming and self-regulation', 'Stop, breathe and think', 'Teach the steps "stop, take a breath, think of a choice" and practise with pretend upsets.', 'Easier: with a picture. Harder: in real moments.', 'Step card'),
    ('Calming and self-regulation', 'Squeeze ball or fidget', 'Give a squeeze ball or fidget to hold during hard tasks.', 'Easier: any time. Harder: only when upset.', 'Squeeze ball'),
    ('Social skills', 'Turn-taking games', 'Roll a ball back and forth saying "my turn, your turn", then simple board games.', 'Easier: two players. Harder: groups.', 'Ball, board game'),
    ('Social skills', 'Greeting practice', 'Practise saying hello, looking at the person and answering, taking turns being the greeter.', 'Easier: with a puppet. Harder: with a stranger or in a group.', 'Puppets'),
    ('Social skills', 'Social stories', 'Read a short story about a situation (waiting, sharing, a new place) and talk about what to do.', 'Easier: pictures. Harder: the child helps write the story.', 'Short stories'),
    ('Social skills', 'Video modelling', 'Watch a short video of a child doing the skill well, then practise the same steps.', 'Easier: copy straight after. Harder: do it later without help.', 'Phone or tablet'),
    ('Social skills', 'Joining a game', 'Practise watching, asking "can I play?" and joining in at a good moment.', 'Easier: one friend. Harder: a group.', 'Games'),
    ('Social skills', 'Sharing with a timer', 'Share a favourite toy for a short time with a timer, then get it back with praise.', 'Easier: 1 minute. Harder: longer and less liked toy.', 'Timer, toys'),
    ('Social skills', 'Good game practice', 'Play short games and practise saying "good game" whether winning or losing.', 'Easier: lose on purpose with the adult. Harder: lose to a peer.', 'Games'),
    ('Social skills', 'Feelings faces', 'Match faces to feelings and talk about what to do when each feeling comes.', 'Easier: happy, sad. Harder: more feelings and causes.', 'Face cards'),
    ('Following instructions', 'Do-what-I-say game', 'Give a series of easy instructions ("clap", "touch your nose") with quick praise, then add real tasks.', 'Easier: one step. Harder: two steps, further away.', 'None'),
    ('Following instructions', 'Easy requests before a hard one', 'Give three quick easy requests the child usually follows, then the harder one.', 'Easier: more easy requests. Harder: fewer.', 'None'),
    ('Following instructions', 'Beat the clock tidy-up', 'Set a timer for a short tidy-up and try to finish before it rings; reward success.', 'Easier: few items. Harder: whole room.', 'Timer'),
    ('Daily routines', 'Morning routine chart', 'A picture chart of morning steps with tick boxes and a reward for finishing on time.', 'Easier: three steps. Harder: whole routine.', 'Chart'),
    ('Daily routines', 'Bedtime routine and reward chart', 'The same calm steps each night (wash, brush, story, light off) with a chart for staying in bed.', 'Easier: reward for part of the routine. Harder: reward for whole night.', 'Chart, books'),
    ('Daily routines', 'Task analysis picture steps', 'Break a skill (washing hands, dressing) into small steps with a picture for each.', 'Easier: adult does most steps. Harder: child does all steps.', 'Picture cards'),
    ('Daily routines', 'Toilet schedule', 'Take the child to the toilet at set times with a reward for trying and for success.', 'Easier: every hour. Harder: longer gaps.', 'Chart, timer'),
    ('Daily routines', 'Homework routine', 'Same time and place, 10 to 15 minutes of work, a short break, and a reward when finished.', 'Easier: 5 minutes. Harder: 20 minutes.', 'Timer, quiet table'),
    ('Daily routines', 'Mealtime sitting practice', 'Sit at the table for a short time with a timer, then leave with praise; slowly increase the time.', 'Easier: 3 minutes. Harder: the whole meal.', 'Timer, chair with foot support'),
    ('Daily routines', 'Chore chart', 'Simple jobs with pictures and a tick for each; small rewards for a week of ticks.', 'Easier: one job. Harder: several jobs.', 'Chart'),
    ('Habits and tics', 'Awareness training', 'Help the child notice when the habit starts, using a mirror, a signal word or a log.', 'Easier: adult notices. Harder: child notices.', 'Mirror, log'),
    ('Habits and tics', 'Competing response', 'Teach a different action that cannot happen at the same time as the habit (for example holding hands together) for one to two minutes.', 'Easier: with prompts. Harder: during real moments.', 'None'),
    ('Habits and tics', 'Habit-free days chart', 'Mark days without the habit and give a reward for a run of them.', 'Easier: part-day goals. Harder: full days.', 'Chart'),
    ('Anxiety and fears', 'Fear ladder', 'List small to big steps toward the feared thing and practise each step until it is easy, rewarding bravery.', 'Easier: very small first step. Harder: bigger steps.', 'Paper ladder'),
    ('Anxiety and fears', 'Worry box or worry time', 'Write or draw worries and put them in a box to talk about at a set time.', 'Easier: draw it. Harder: write and review.', 'Box, paper'),
    ('Anxiety and fears', 'Brave self-talk cards', 'Cards with coping statements ("I can try", "it will pass") to say in hard moments.', 'Easier: adult reads. Harder: child chooses.', 'Cards'),
    ('Anxiety and fears', 'Goodbye routine', 'A short, same-every-time goodbye ritual and a promise of when you will be back.', 'Easier: with a comfort item. Harder: shorter and shorter.', 'Comfort item'),
    ('Teaching new skills', 'Discrete trial teaching', 'Give a clear instruction, wait for the response, give help if needed and reward success, in short repeated trials.', 'Easier: with prompts. Harder: no prompts.', 'Materials for the skill, rewards'),
    ('Teaching new skills', 'Prompting and fading', 'Help just enough for the child to succeed (show, point, say) and gradually give less help.', 'Fade help one level at a time.', 'None'),
    ('Teaching new skills', 'Backward chaining', 'The adult does all steps except the last; the child does the last step and gets the reward, then the last two, and so on.', 'Add one more step when success is steady.', 'Task materials'),
    ('Teaching new skills', 'Imitation (copy me)', 'Copy simple actions, then actions with objects, then sequences, with quick rewards.', 'Easier: one action. Harder: three actions in a row.', 'Toys'),
    ('Teaching new skills', 'Play-based teaching', "Teach skills inside the child's favourite play so learning happens naturally.", 'Easier: adult leads. Harder: child leads and the adult follows.', "Child's toys"),
    ('Family', 'Special time', 'Ten to fifteen minutes a day when the child leads play and the parent gives full attention without questions or corrections.', 'Easier: five minutes. Harder: add a second child later.', 'Toys'),
    ('Family', 'House rules poster', 'Three to five short rules in positive words with pictures, put where everyone can see them.', 'Review monthly.', 'Poster'),
    ('Family', 'Behaviour diary', 'The parent writes down the best thing and one problem each day to see progress.', 'Easier: three lines. Harder: add what helped.', 'Notebook'),
    ('Family', 'Planned ignoring of small attention-seeking behaviour', 'Calmly look away from minor behaviour while staying nearby, then give attention the moment the child behaves well. Only for safe, minor behaviour and after agreeing with the therapist.', 'Never use it for unsafe behaviour.', 'None'),
    ('Family', 'Safety and crisis plan', 'Write down what to do if the child is a danger to self or others: keep calm, keep everyone safe, remove hazards, who to call.', 'Review after any incident.', 'Printed plan'),
]

DEPARTMENTS = [('ot', 'Occupational therapy activities', OT), ('speech', 'Speech therapy activities', SPEECH), ('behaviour', 'Behaviour therapy tools', BEHAVIOUR)]


def _sentence(text):
    text = (text or '').strip()
    return text if not text or text[-1] in '.!?' else text + '.'


def describe(how, levels, equipment):
    parts = [_sentence(how)]
    if levels:
        parts.append('Easier or harder: ' + _sentence(levels))
    if equipment and equipment.strip().lower() != 'none':
        parts.append('You need: ' + _sentence(equipment))
    return ' '.join(parts)


def sync(region_model, subregion_model, exercise_model):
    """Add the department exercises that are missing. `*_model` are the real models, or the historical ones inside a migration."""
    exercise_id, sub_id = EXERCISE_BASE, SUBREGION_BASE
    for region_number, (discipline, region_name, rows) in enumerate(DEPARTMENTS, start=1):
        region, _ = region_model.objects.get_or_create(id=REGION_BASE + region_number, defaults={'region_name': region_name})
        have = {n.lower() for n in exercise_model.objects.filter(discipline=discipline).values_list('exercise_name', flat=True)}
        subs = {}
        for area, name, how, levels, equipment in rows:
            exercise_id += 1
            if area not in subs:
                sub_id += 1
                subs[area] = sub_id
            if name.lower() in have:
                continue  # the department already has one with this name
            sub, _ = subregion_model.objects.get_or_create(id=subs[area], defaults={'region_fk_id': region.pk, 'sub_region_name': area})
            sets, reps, hold, rest = DOSES.get((discipline, area), DEFAULT_DOSE)
            exercise_model.objects.get_or_create(id=exercise_id, defaults={
                'sub_region_fk_id': sub.pk, 'exercise_name': name, 'exercise_type': area, 'difficulty_level': 2 if (discipline, area) in HARDER else 1, 'default_sets': sets,
                'default_reps': reps, 'hold_time_sec': hold, 'default_rest_time_sec': rest, 'exercise_description': describe(how, levels, equipment), 'discipline': discipline})
