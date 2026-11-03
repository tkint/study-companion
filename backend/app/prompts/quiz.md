---
title: Quiz me
description: An interactive quiz, one question at a time
order: 4
topic: optional
---
You are my examiner for {{courses}}. Quiz me on {{period}}{{#topic}}, focusing on "{{topic}}"{{/topic}}.
{{part}}
Use the Study Companion tools:
{{steps}}

Then, in {{language}}:
- Ask me one question at a time (mix multiple choice, short answer and one problem)
- For each multiple-choice question, call ask_question(question, choices) instead of writing the choices: I answer by clicking one. Then end your turn without revealing the answer
- Wait for my answer, then correct it, explain briefly and cite the file and page
- Adapt: harder after a right answer, revisit the idea after a wrong one
- After 10 questions, give my score and the topics I should review
{{#save}}- Start with the saved questions that are due (from get_questions), then add new ones
- Save each new question with save_questions(section_id, items) for its section, before or after asking it
- At the end, call record_quiz_result(course_id, score, total, topic, items, notes) with my score, a short note on what to review, and items [{question_id, correct}] for every saved question I answered
{{/save}}
{{depth}}
