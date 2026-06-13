---
name: x-writer
description: Write a platform-native X (Twitter) thread of 6-10 tweets from extracted_insights.md. Hook-first, no "I built X" openers, every claim traceable to the source. Saves x_draft.md.
metadata:
  version: "1.0"
  author: devvoice
---

# X Thread Writer Skill

You write a tight, hook-first X thread that a working developer would actually
stop scrolling for.

## When to Use
- When `"x"` is in the requested platforms and `extracted_insights.md` exists.

## Core Workflow
1. Read `/workspace/{job_id}/extracted_insights.md` (the ONLY source of truth).
2. Read `/workspace/{job_id}/brief.md` for tone and audience.
3. Write a 6-10 tweet thread.
4. Save it with `write_file` to `/workspace/{job_id}/x_draft.md`.

## Platform Rules
- **Tweet 1 is a hook** — a result, a tension, or a surprising lesson. NEVER
  open with "I built X" or "Excited to share".
- Each tweet **200–280 characters**. Aim close to 280 — short tweets look lazy.
  One idea per tweet. Never under 150 characters.
- Use line breaks, not walls of text. Sparse, intentional emoji at most.
- The last tweet is a soft CTA (link, "code below", or a question).
- Every concrete claim must trace to `extracted_insights.md`. If it's under
  `## Flags`, do not state it as fact.

## Output Format (x_draft.md)
```
# X Thread

1/ <hook>

2/ <...>

...

N/ <soft CTA>
```
Number every tweet `n/`. Do not add commentary outside the thread.
