---
name: langgraph
description: LangGraph expertise for building stateful, multi-step agent workflows. Use when the user asks about LangGraph, StateGraph, nodes, edges, conditional routing, checkpointers, persistence, memory, human-in-the-loop, subgraphs, streaming, or building agents with langgraph / langchain. Provides architecture patterns, API workflows, and runnable examples.
license: MIT
metadata:
  version: "1.0"
  author: deepagentscourse
---

# LangGraph Skill

You are acting as a LangGraph specialist. Use this skill whenever the user's
query involves building, debugging, or understanding LangGraph applications —
graphs, agents, state management, persistence, or streaming.

## When to Use
- User asks to build an agent or workflow with LangGraph
- User mentions: `StateGraph`, nodes, edges, `add_conditional_edges`, `MessagesState`,
  checkpointer, `MemorySaver`, thread_id, interrupt, `Command`, subgraphs
- User asks how to add memory / persistence / human-in-the-loop to an agent
- User is debugging LangGraph state, routing, or streaming behavior

## Supporting Files (read these for deeper context)
- `instructions.md` — detailed build workflow, state design rules, and common pitfalls
- `examples.md` — runnable graph examples (basic graph, conditional routing, memory, tools)

## Core Workflow
1. Read `instructions.md` in this skill folder for the full build methodology.
2. Identify the graph shape: linear pipeline, router, agent loop, or multi-agent.
3. Design the state schema FIRST (TypedDict / Pydantic with reducers).
4. Define nodes as pure functions: `state -> partial state update`.
5. Wire edges (static, then conditional), compile with a checkpointer if memory is needed.
6. Show how to invoke with `thread_id` config and how to stream.
7. Match the patterns in `examples.md` when one applies.

## Quick Standards
- Always show the state schema before the graph wiring
- Nodes return partial updates, never mutate state in place
- Use `MessagesState` / `add_messages` reducer for chat history
- Checkpointer (`MemorySaver` for demos, SQLite/Postgres for prod) + `thread_id` = memory
- Prefer `create_react_agent` / `create_deep_agent` prebuilts before hand-rolling loops