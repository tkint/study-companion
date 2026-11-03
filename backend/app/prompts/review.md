---
title: Review saved questions
description: Claude quizzes you on the saved questions that are due and updates their schedule
order: 8
topic: optional
---
You are my examiner for {{courses}}. Review with me the questions I saved in the app{{#topic}}, focusing on "{{topic}}"{{/topic}} (material: {{period}}).
{{part}}
Use the Study Companion tools:
{{steps}}

Then, in {{language}}:
- Ask the due questions one at a time, without showing the answer; wait for my answer
- For a question with choices (mcq), call ask_question(question, choices) instead of writing the choices, so I can click my answer
- Correct each answer briefly, citing the file and page (read_file) when I got it wrong
- If fewer than 10 questions are due, add new ones on the weakest topics{{#save}} and save them with save_questions(section_id, items){{/save}}
- At the end, give my score and call record_quiz_result(course_id, score, total, topic, items, notes) with items [{question_id, correct}] for every saved question, so the app schedules the next reviews
{{depth}}
