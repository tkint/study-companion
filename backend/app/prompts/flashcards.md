---
title: Flashcards
description: Question and answer cards to memorise the key facts
order: 5
topic: optional
---
You are my tutor for {{courses}}. Make flashcards for {{period}}{{#topic}}, focusing on "{{topic}}"{{/topic}}.
{{part}}
Use the Study Companion tools:
{{steps}}

Then, in {{language}}:
- Write 20 flashcards as a table: front (question or term), back (short answer), source (file and page)
- Cover definitions, formulas, key results and typical pitfalls
- Order them from the basics to the harder ones
{{#save}}- Save them to the app with save_questions(section_id, items), one call per section, with kind "flashcard", the front as question, the back as answer and the file and page as source; I will review them in the app's study mode
{{/save}}
{{depth}}
