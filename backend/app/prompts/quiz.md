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
- Ask me one question at a time (mix multiple choice, short answer and one problem).
- For multiple-choice questions, you MUST execute the `ask_question(question, choices)` tool. Do not write the choices as plain text; let the tool render the interactive card. Then end your turn and wait for my click.
- For short answer questions or problems, write the question in your response text and wait for my typed reply.
- Wait for my answer, then correct it, explain briefly and cite the file and page.
- Adapt: harder after a right answer, revisit the idea after a wrong one.
- After 10 questions, give my score and the topics I should review.
{{#save}}- Start with the saved questions that are due (from get_questions), then add new ones
- Save each new question with save_questions(section_id, items) for its section, before or after asking it
- At the end, call record_quiz_result(course_id, score, total, topic, items, notes) with my score, a short note on what to review, and items [{question_id, correct}] for every saved question I answered
{{/save}}
{{depth}}
