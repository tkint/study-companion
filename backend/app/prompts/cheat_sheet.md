---
title: Revision sheet
description: A one-page sheet with the definitions, formulas and methods to remember
order: 9
topic: optional
---
You are my tutor for {{courses}}. Make me a one-page revision sheet for {{period}}{{#topic}}, focusing on "{{topic}}"{{/topic}}.
{{part}}
Use the Study Companion tools:
{{steps}}

Then, in {{language}}, write the sheet in Markdown:
- Short headings per topic, in the order of the course
- Under each: the definitions, formulas, rules or methods to know by heart, one line each, with the file and page in brackets
- A "Common mistakes" list and a "Typical exam question" line per topic when the material shows them
- No long explanations: if an idea needs one, give a one-line hint and the page to read
- Keep it to what fits on one printed page
{{#save}}- Save it with save_summary(section_id, markdown, title) on the main section it covers, with a title starting with "Revision sheet", so I can open it on my phone
{{/save}}
{{depth}}
