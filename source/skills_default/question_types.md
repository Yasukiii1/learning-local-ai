# Card types. Each "## name" section is one type; the app picks a type for every card
# and gives that section to the student. Edit the text, but keep the "## name" lines
# and the line labels the app reads (QUESTION / STATEMENT / SENTENCE / KEYWORD / A) B) C) / CORRECT / RIGHT / WRONG / ANSWER).
# These rules work for ANY lesson: never write anything about one particular subject here.

## explain_why
Ask the Teacher to EXPLAIN WHY or HOW something in your notes works or happens.
The question starts with "Why" or "How" and is under 20 words.
The answer is 1 or 2 short sentences that give the reason from your notes.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## what_if
Ask a "What would happen if ...?" question about a cause and its effect that your notes explain.
The question starts with "What would happen if" and is under 20 words.
The answer says what would happen and why, in 1 or 2 short sentences, using your notes.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## compare
Ask for the DIFFERENCE between two things that are both in your notes.
The question starts with "What is the difference between" or "How is", and is under 20 words.
The answer gives the main difference in 1 or 2 short sentences.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## fill_blank
Copy ONE true, short sentence from your notes and pick ONE important key word in it (a lesson term,
never a small word like "the" or "is"). The app hides that word and the Teacher fills it in.
The sentence has no styling and is under 25 words. The key word is 1 to 3 words, written exactly as in the sentence.
The answer is one short sentence about what the key word means.
Reply with exactly these three lines:
SENTENCE: ...
KEYWORD: ...
ANSWER: ...

## pick_one
A multiple choice question with exactly 3 options and exactly ONE correct option.
- Every option is SHORT: 1 to 6 words, no full sentences, no explanations inside the options.
- All 3 options are the same kind of thing (3 names, 3 numbers, 3 places, 3 actions...), so they look alike
  and the Teacher has to really know the answer. The 2 wrong options are close but clearly wrong if you
  know the lesson (for example a related term from the notes, or a number that is near but not right).
- The RIGHT option is the answer the fact gives to the question, in its words.
- Each WRONG option must be clearly FALSE as an answer to this question: never the right option said another way
  ("force × distance" and "distance × force" are the SAME answer), and never something else that is also true about
  the word asked. A different lesson word that answers a DIFFERENT question is a good wrong option.
- The answer is 1 short sentence saying why the RIGHT option is right, using the RIGHT option's words. Never mention
  letters (A, B, C) and never the wrong options.
Reply with exactly these lines (the app puts the options in a random order):
QUESTION: ...
RIGHT: <the right answer: 1 to 6 words, not a sentence>
WRONG: <a wrong answer: 1 to 6 words, the same kind of thing>
WRONG: <another wrong answer: 1 to 6 words>
ANSWER: ...
Example (for a different lesson - do NOT copy it):
QUESTION: What do plants make from **sunlight**?
RIGHT: Food (sugar)
WRONG: Water
WRONG: Soil
ANSWER: Plants use sunlight to make their own **food**, a sugar.

## spot_mistake
Write ONE statement about something in your notes that sounds right but has ONE wrong fact in it
(a wrong word, number or name). It is a statement, NOT a question, one sentence.
The answer is one short sentence that says what was wrong and what is right.
Reply with exactly these two lines:
STATEMENT: ...
ANSWER: ...

## lightning
A QUICK and EASY question: the Teacher only has 10 seconds, so it must be answerable with 1 to 3 words.
- The answer is the key word: {keyword}
- Describe it using the fact, and ask for its name (like "What do we call ...?", "What is the name for ...?").
  Do not write the key word in the question.
- Never ask "why" or "how", never ask to explain, compare or list several things.
- The question is under 12 words.
- The answer STARTS with the 1 to 3 word answer in **bold**, then a few words, like: **Evaporation**, when water turns into vapour.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## whos_right
Two students disagree about a question. Write the question, one RIGHT claim and one WRONG claim.
- Both claims are one short sentence (under 15 words) that a student would say, like "I think it's ...".
  Never write "the teacher says" in a claim: each student just says what they think.
- The wrong claim sounds believable: a mix-up a real student could make, using words from the lesson.
- The question is under 20 words. The answer is 1 short sentence saying why the right claim is right.
Reply with exactly these four lines:
QUESTION: ...
RIGHT: ...
WRONG: ...
ANSWER: ...

## silver
A SILVER card: a slightly harder question than normal. Go one step beyond the basic fact: ask why or how
it works, or how the fact is used in a real situation - but the answer must still be in your notes.
The question is under 22 words. The answer is 1 or 2 short sentences.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## infected
A ZOMBIE has infected this question! Ask about the same idea again, but slightly harder: go one step beyond
the basic fact (why, how, or how it is used). The answer must still be in your notes.
The question is under 22 words. The answer is 1 or 2 short sentences.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## boss
This is the ZOMBIE BOSS: a hard question in TWO PARTS that connects your topic ({topic}) with {other_topic}.
Notes on {other_topic}:
<other>
{other_notes}
</other>
Part 1 asks one important thing. Part 2 builds on part 1 and goes deeper (why, how, or what would happen).
Each question is under 22 words; each answer is 1 or 2 short sentences, using only the two sets of notes.
Reply with exactly these four lines:
PART1: ...
ANSWER1: ...
PART2: ...
ANSWER2: ...

## second_chance
Earlier the Teacher missed this question: "{orig_question}"
The correct answer was: "{orig_answer}"
Ask about the SAME thing again in different words (not a copy), so the Teacher gets a second chance.
The question is under 20 words. The answer is 1 or 2 short sentences.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## streak
The Teacher is on a hot streak! Ask a slightly HARDER question: one that needs real understanding
(a why or how, or connecting two facts from your notes).
The question is under 22 words. The answer is 2 short sentences.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...

## challenge
This is a GOLD CHALLENGE card. It connects TWO topics: yours ({topic}) and {other_topic}.
Notes on {other_topic}:
<other>
{other_notes}
</other>
Ask how the two are connected, work together, or are different - using only the two sets of notes.
The question is under 25 words. The answer is 2 short sentences.
Reply with exactly these two lines:
QUESTION: ...
ANSWER: ...
