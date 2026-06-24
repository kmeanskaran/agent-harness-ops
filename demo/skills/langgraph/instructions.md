# LangGraph Skill — Detailed Instructions

Follow this methodology for every LangGraph-related query.

## Step 1: Identify the Graph Shape
Classify the user's problem before writing code:

| Shape | Signal | Approach |
|-------|--------|----------|
| Linear pipeline | Fixed sequence of steps | `START -> a -> b -> END` static edges |
| Router | "If X do A else B" | One router node + `add_conditional_edges` |
| Agent loop (ReAct) | LLM decides which tools to call | `create_react_agent` or LLM node ⇄ tool node loop |
| Multi-agent / Deep agent | Parallel research, planning, subagents | `create_deep_agent`, subgraphs, supervisor pattern |

## Step 2: Design State FIRST
- Use `TypedDict` (or Pydantic) for the state schema.
- For chat: extend `MessagesState` or use `Annotated[list, add_messages]`.
- Add a **reducer** for any key written by multiple nodes (e.g., `operator.add` for lists).
- Keep state minimal — only what downstream nodes need.

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]
    summary: str          # last-write-wins (no reducer)
```

## Step 3: Write Nodes
- A node is a function `def node(state: State) -> dict:` returning a **partial update**.
- Never mutate `state` in place; return only the keys you changed.
- Keep LLM calls, tool calls, and pure logic in separate nodes when possible.

## Step 4: Wire Edges
- Static: `graph.add_edge("a", "b")`; entry: `graph.add_edge(START, "a")`.
- Conditional: router function returns the next node name (or `END`):

```python
def route(state: State) -> str:
    return "tools" if state["messages"][-1].tool_calls else END

graph.add_conditional_edges("llm", route, ["tools", END])
```

- For dynamic handoffs, return `Command(goto="node", update={...})` from a node.

## Step 5: Persistence & Memory
- Compile with a checkpointer to get per-thread memory:

```python
from langgraph.checkpoint.memory import MemorySaver
app = graph.compile(checkpointer=MemorySaver())
app.invoke(inputs, config={"configurable": {"thread_id": "user-1"}})
```

- Same `thread_id` = same conversation; new `thread_id` = fresh state.
- Cross-thread / long-term memory: use a `BaseStore` (e.g., `InMemoryStore`) passed as `store=`.
- Production: SQLite (`SqliteSaver`) or Postgres (`PostgresSaver`) checkpointers.

## Step 6: Human-in-the-Loop
- Use `interrupt()` inside a node to pause and surface a payload to the caller.
- Resume with `Command(resume=value)`.
- Requires a checkpointer — interrupts are checkpointed pauses.

## Step 7: Streaming
- `app.stream(inputs, config, stream_mode="values")` — full state each step.
- `stream_mode="updates"` — only the delta from each node.
- `stream_mode="messages"` — LLM tokens for chat UIs.

## Common Pitfalls (warn the user about these)
1. **Missing reducer** → concurrent node writes raise `InvalidUpdateError`.
2. **Forgetting `thread_id`** when a checkpointer is set → `ValueError` at invoke.
3. **Mutating state in place** → silent bugs; always return new partial dicts.
4. **No recursion limit handling** → agent loops hit the default limit (25); raise it via `config={"recursion_limit": 50}` deliberately, not blindly.
5. **Doing everything in one node** → defeats checkpointing, retries, and streaming granularity.

## Debugging Checklist
- `app.get_state(config)` — inspect current checkpoint values & next nodes.
- `app.get_state_history(config)` — time-travel through checkpoints.
- Draw the graph: `app.get_graph().draw_mermaid()` to verify wiring.