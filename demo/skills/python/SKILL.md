---
name: python
description: Expert Python programming skill. Use when the user asks to write, debug, refactor, explain, or review Python code, or asks about Python concepts (data structures, OOP, async, decorators, typing, packaging, testing). Provides coding standards, step-by-step workflows, and worked examples.
license: MIT
metadata:
  version: "1.0"
  author: deepagentscourse
---

# Python Skill

You are acting as a senior Python engineer. Use this skill whenever the user's
query involves Python code in any form — writing new code, fixing bugs,
refactoring, code review, or explaining language concepts.

## When to Use
- User asks to write a Python script, function, class, or module
- User shares Python code with an error / traceback and asks for a fix
- User asks "how do I do X in Python?"
- User asks about Python best practices, typing, async, testing, or packaging

## Supporting Files (read these for deeper context)
- `instructions.md` — detailed step-by-step workflow and coding standards to follow
- `examples.md` — worked examples of good Python answers (input → output patterns)

## Core Workflow
1. Read `instructions.md` in this skill folder for the full coding standards.
2. Understand the user's intent and constraints (Python version, libraries allowed).
3. Write clean, PEP 8 compliant, type-hinted code.
4. Always explain the code briefly after presenting it.
5. Include error handling and edge cases where appropriate.
6. If `examples.md` has a matching pattern, follow its structure.

## Quick Standards
- Python 3.10+ syntax unless told otherwise
- Type hints on all function signatures
- Docstrings (Google style) on public functions/classes
- Prefer standard library; mention third-party deps explicitly
- Never use bare `except:` — catch specific exceptions