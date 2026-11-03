---
title: Exam prep
description: What to revise, likely questions and a mock exam
order: 6
topic: optional
---
You are my exam coach for {{courses}}. Prepare me for the exam on {{period}}{{#topic}}, focusing on "{{topic}}"{{/topic}}.
{{part}}
Use the Study Companion tools:
{{steps}}

Then, in {{language}}:
- List the topics most likely to be examined, ranked, with why (emphasis in the slides, exercises, past quizzes)
- For each topic: the key facts or methods to know, citing file and page
- Write a mock exam of 6 to 8 questions in the style of the course exercises; give the solutions only when I ask
{{#time}}- Give me a revision schedule for {{time}}
{{/time}}{{#deadlines}}- Take the upcoming deadlines into account
{{/deadlines}}{{#save}}- Save the mock exam questions with save_questions(section_id, items), with the solution as answer; after I take the mock exam, record my score with record_quiz_result(course_id, score, total, topic, notes)
{{/save}}
{{depth}}
