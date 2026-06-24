---
name: report-writer
description: Report writing skill that should be applied AFTER answering any user query. Whenever the deep agent produces a final answer, use this skill to also write a structured markdown report of the interaction (question, approach, findings, answer, sources) and save it as a file using the write_file tool. Use for every substantive answer, and especially when the user asks for a report, summary document, or saved output.
license: MIT
metadata:
  version: "1.0"
  author: deepagentscourse
---

# Report Writer Skill

This is a **post-answer** skill: after you finish answering ANY substantive
user query, generate a structured report of what was asked, what you did,
and what you concluded — and save it to a file with the `write_file` tool.

## When to Use
- ALWAYS after producing a final answer to a substantive question
- When the user explicitly asks for a report, summary document, or saved output
- After research tasks, code generation tasks, or multi-step workflows
- Skip only for trivial exchanges (greetings, clarifying questions)

## Supporting Files (read these for deeper context)
- `instructions.md` — the exact report template, file-naming rules, and writing standards
- `examples.md` — sample reports showing the expected quality and structure

## Core Workflow
1. Answer the user's question first, as normal (possibly using other skills).
2. Read `instructions.md` in this skill folder for the report template.
3. Fill in the template: title, date, question, approach, key findings, answer, sources.
4. Save the report with `write_file` to `/reports/<topic-slug>-report.md`.
5. Tell the user the report was saved and where.

## Quick Standards
- Reports are markdown files saved under `/reports/`
- File name: kebab-case topic slug + `-report.md` (e.g., `/reports/lambda-cost-report.md`)
- Always include: Question, Approach, Key Findings, Answer, Sources/Tools Used
- Keep the report self-contained — readable without the chat transcript
- Be factual; do not add claims to the report that were not in your answer