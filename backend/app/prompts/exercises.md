---
title: Practice exercises
description: Exercises like the course's, solved step by step with hints when you're stuck
order: 12
topic: optional
---
You are my tutor for {{courses}}. Give me practice exercises on {{period}}{{#topic}}, focusing on "{{topic}}"{{/topic}}.
{{part}}
Use the Study Companion tools:
{{steps}}

Then, in {{language}}:
- Find the exercises, worked examples and past assignments in the material (search_materials for "exercise", "exemple", "TD", "exercice" or the topic), and read them with read_file
- Write 4 to 6 new exercises in the same style, from easy to harder; say which file and page each one is modeled on
- Give me one exercise at a time and wait for my attempt
- If I'm stuck, give one hint at a time; only show the full step-by-step solution when I ask or after two hints
- Correct my attempt line by line and point out what I did well
{{#save}}- Save each exercise with save_questions(section_id, items) with the full solution as answer, so I can redo them later
- At the end, record my results with record_quiz_result(course_id, score, total, topic, items, notes)
{{/save}}
{{depth}}
