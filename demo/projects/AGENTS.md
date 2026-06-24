# Deep Agents Project Context

This file is intended to be loaded as shared context whenever a deep agent is invoked in this demo.

## What Deep Agents Are

Deep agents are long-running agents designed for tasks that require planning, tool use, context management, and iterative verification. In this tutorial project, the agent should be treated as an execution layer on top of an LLM rather than a simple chat interface.

## Core Architecture Concepts

1. `Model`
   The reasoning engine that interprets the request, decides what to do next, and produces responses.

2. `Agent Harness`
   The deep agent runtime coordinates the loop of understanding the task, using tools, tracking progress, and verifying results.

3. `Tools`
   Tools extend the model with external actions such as reading files, writing files, searching a workspace, or calling subagents.

4. `Context Layer`
   Context comes from the system prompt, user input, runtime state, memory backends, and project files like this one.

5. `Backend / Memory`
   Different backends can persist agent state, notes, files, and cross-thread information depending on the demo setup.

6. `Subagents`
   Complex tasks can be split into smaller focused tasks. Subagents help isolate context and reduce overload in the main thread.

## Suggested Execution Pattern

Deep agents in this project should generally follow:

1. Understand the user goal.
2. Break the task into smaller steps.
3. Use tools to inspect the environment before acting.
4. Write or update artifacts only after gathering enough context.
5. Verify the result against the original request.
6. Return a concise final summary with outcomes and any remaining risks.

## Context Engineering Notes

- Keep important project facts in stable files so they can be loaded repeatedly.
- Prefer concise, structured context over long narrative notes.
- Store architecture decisions, domain constraints, and expected workflows in reusable markdown files.
- Use runtime context only for transient task-specific details.

## Expectations For An Invoked Agent

When this file is loaded, the agent should assume:

- The repo is a tutorial workspace for learning deep agent patterns.
- The demo may include multiple backend strategies for memory and persistence.
- Context quality matters as much as model quality.
- The agent should inspect local files before making assumptions.
- The agent should be direct, structured, and verification-oriented.

## Example High-Level System View

`User Request -> Deep Agent -> Planning / Tool Use / Subagents -> Backend Memory / Filesystem -> Verified Output`

## Use Of This File

This file is not a task queue. It is baseline architectural context that helps the agent start with the right mental model whenever it is invoked inside the demo.
