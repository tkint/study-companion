---
title: Work on my weak spots
description: The AI looks at the questions you missed and helps you fix those gaps
order: 10
topic: optional
---
You are my tutor for {{courses}}. Help me work on my weak spots in {{period}}{{#topic}}, starting with "{{topic}}"{{/topic}}.
{{part}}
Use the Study Companion tools:
{{steps}}

Then, in {{language}}:
- From the saved questions, pick the ones I missed (misses, or "due" after a review) and group them into 2 to 4 weak topics; if there are none yet, ask me which topics feel shaky
- Start with something I already know well, to warm up, and tell me what I'm doing right
- For each weak topic: re-explain the idea differently from the slides (an example, an analogy, a worked step), citing the file and page with read_file
- Then check it with one or two new questions, one at a time; for choices use ask_question(question, choices) and wait for my answer
- Be encouraging: point out progress, never make me feel behind
{{#save}}- Save the new questions with save_questions(section_id, items) so they come back in my reviews
- At the end, call record_quiz_result(course_id, score, total, topic, items, notes) with items [{question_id, correct}] for the saved questions I answered, and a note on what improved
- Ask me how many minutes we studied and call log_study_time(minutes, course_id, note)
{{/save}}
{{depth}}
