# Report Writer Skill — Detailed Instructions

Follow these steps every time you generate a report.

## Step 1: When to Trigger
Write a report after answering when ANY of these hold:
- The answer required research, multiple steps, tool calls, or another skill
- The user asked a technical question and you produced a substantive answer
- The user explicitly requested a report or saved output

Do NOT write a report for greetings, one-word answers, or meta-questions
about your own capabilities.

## Step 2: File Naming and Location
- Directory: `/reports/` (create it implicitly by writing the file path)
- Filename: `<topic-slug>-report.md`
  - kebab-case, lowercase, 3-6 words max
  - Examples: `s3-upload-python-report.md`, `langgraph-memory-report.md`
- If a report for the same topic already exists in this session, overwrite it
  with the updated version rather than creating duplicates.

## Step 3: Report Template (use exactly this structure)

```markdown
# Report: <Short Title>

**Date:** <today's date>
**Requested by:** user
**Skills used:** <list of skills consulted, e.g., python, aws — or "none">

## 1. Question
<The user's question, restated clearly in one or two sentences.>

## 2. Approach
<2-5 bullets: what you did to answer — which skills/files you read,
which tools you called, what reasoning steps you took.>

## 3. Key Findings
<3-7 bullets with the most important facts, decisions, or code insights.
Each bullet must be self-contained and verifiable from the answer.>

## 4. Answer
<The final answer, condensed. Include the essential code block(s) if the
answer contained code. This section must stand alone.>

## 5. Sources / Tools Used
<Skill files read, tools invoked, URLs cited, or "model knowledge" if none.>

## 6. Caveats & Next Steps
<Limitations of the answer and 1-3 suggested follow-ups. Optional but
recommended.>
```

## Step 4: Writing Standards
1. **Self-contained** — a reader who never saw the chat must understand the report.
2. **Faithful** — only include claims that appeared in (or directly support) your answer. Never embellish.
3. **Concise** — target 150-400 words plus code blocks. A report is a summary, not a transcript.
4. **Code** — include final working code, not intermediate broken attempts.
5. **Honest caveats** — if you were unsure about something in the answer, say so in section 6.

## Step 5: Save and Confirm
1. Use the `write_file` tool with the full path, e.g.:
   `write_file(file_path="/reports/langgraph-memory-report.md", content=<report>)`
2. After saving, end your reply with a single confirmation line:
   `📄 Report saved to /reports/<filename>`
3. Do not paste the entire report into the chat unless the user asks —
   the answer itself is already in the conversation.