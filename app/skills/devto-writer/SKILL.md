---
name: devto-writer
description: Write a 1000-1500 word dev.to technical article from extracted_insights.md following Problem -> What I built -> How it works -> What I learned -> What's next. Honest about tradeoffs. Saves devto_draft.md.
metadata:
  version: "1.0"
  author: devvoice
---

# dev.to Article Writer Skill

You write a substantive, honest technical article a developer would bookmark.

## When to Use
- When `"devto"` is in the requested platforms and `extracted_insights.md`
  exists.

## Core Workflow
1. Read `/workspace/{job_id}/extracted_insights.md` (source of truth).
2. Read `/workspace/{job_id}/brief.md` for tone and audience.
3. Write a 1000-1500 word article in Markdown.
4. Save it with `write_file` to `/workspace/{job_id}/devto_draft.md`.

## Structure (use these sections)
1. **The Problem** — what hurt, why it mattered.
2. **What I Built** — the thing, concretely.
3. **How It Works** — architecture and key decisions, with small code/config
   blocks where the source supports them.
4. **What I Learned** — the earned insights and hard parts.
5. **What's Next** — honest about what's missing.

## Platform Rules
- 1000-1500 words. Markdown with `##` headings and fenced code blocks.
- Honest about tradeoffs — name what you'd do differently.
- Concrete over generic. Pull specifics from the insights, never invent APIs,
  numbers, or benchmarks. Do not state `## Flags` items as fact.

## Output Format (devto_draft.md)
A complete Markdown article starting with an `#` H1 title.
