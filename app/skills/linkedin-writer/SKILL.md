---
name: linkedin-writer
description: Write a 150-300 word LinkedIn post from extracted_insights.md. Personal narrative, short paragraphs, what broke and what was learned. No corporate tone. Saves linkedin_draft.md.
metadata:
  version: "1.0"
  author: devvoice
---

# LinkedIn Post Writer Skill

You write a short, human LinkedIn post — a developer telling a real story, not a
press release.

## When to Use
- When `"linkedin"` is in the requested platforms and `extracted_insights.md`
  exists.

## Core Workflow
1. Read `/workspace/{job_id}/extracted_insights.md` (source of truth).
2. Read `/workspace/{job_id}/brief.md` for tone and audience.
3. Write a 150-300 word post.
4. Save it with `write_file` to `/workspace/{job_id}/linkedin_draft.md`.

## Platform Rules
- **150-300 words.** Count them.
- Short paragraphs (1-3 lines). Generous white space.
- Personal narrative: what you set out to do, what broke, what you learned.
- No corporate buzzwords ("leverage", "synergy", "excited to announce").
- Open with a specific moment or tension, not a summary.
- End with one genuine takeaway or an open question.
- Every claim traces to `extracted_insights.md`; never inflate `## Flags` items.

## Output Format (linkedin_draft.md)
```
# LinkedIn Post

<the post body, ready to paste>
```
