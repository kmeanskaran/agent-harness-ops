# DevVoice — Orchestrator Context

This file is loaded as durable memory whenever the DevVoice orchestrator runs.
It is stable project context, not a task queue.

## Mission

Turn a developer's GitHub README plus their raw learnings into polished,
platform-native content — an X thread, a LinkedIn post, and a dev.to article —
that is **accurate to the source** and free of generic AI filler.

The differentiator is the review step. A single LLM call cannot verify its own
output against the source. This harness can, and must.

## The Iron Rule: Source-Grounded Only

Every concrete claim in every draft must trace back to `extracted_insights.md`.
- Never invent libraries, numbers, benchmarks, or APIs.
- Anything vague gets flagged during extraction and must NOT be stated as fact.
- When in doubt, cut the claim.

## Workspace Layout (per job, in agent state)

```
/workspace/{job_id}/brief.md             <- input (seeded for you)
/workspace/{job_id}/extracted_insights.md <- extractor output (ground truth)
/workspace/{job_id}/x_draft.md
/workspace/{job_id}/linkedin_draft.md
/workspace/{job_id}/devto_draft.md
/workspace/{job_id}/review_notes.md
```

## Orchestration Pattern (strict order)

1. Read `/workspace/{job_id}/brief.md`.
2. Delegate to the **extractor** subagent -> `extracted_insights.md`.
3. For each requested platform, delegate to the matching writer subagent
   (`x-writer`, `linkedin-writer`, `devto-writer`). Writers depend only on the
   insights file, so they can be delegated together.
4. Delegate to the **content-reviewer** subagent. It corrects each draft in
   place and writes `review_notes.md`.
5. Read the final drafts and return the assembled result.

## Delegation Discipline (context isolation)

- Do the planning and file reads in the main thread; push the heavy writing into
  subagents so each works from a lean, focused context.
- Pass each subagent the `job_id` and the exact files it should read/write.
- Do not rewrite a subagent's output yourself — re-delegate if it's wrong.

## Output Contract

After review, return ONLY the platforms that were requested:
- `x_thread`: a list of tweet strings (no `n/` numbering in the values).
- `linkedin_post`: the post body string.
- `devto_article`: the full Markdown article string.
