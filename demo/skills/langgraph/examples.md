# LangGraph Skill — Worked Examples

Runnable patterns to copy and adapt.

---

## Example 1: Minimal Linear Graph

```python
from typing import TypedDict

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    topic: str
    draft: str


def write_draft(state: State) -> dict:
    return {"draft": f"A short note about {state['topic']}."}


graph = StateGraph(State)
graph.add_node("write_draft", write_draft)
graph.add_edge(START, "write_draft")
graph.add_edge("write_draft", END)

app = graph.compile()
print(app.invoke({"topic": "LangGraph"}))
```

---

## Example 2: Conditional Routing (Router Pattern)

```python
from typing import Literal, TypedDict

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    question: str
    category: str
    answer: str


def classify(state: State) -> dict:
    q = state["question"].lower()
    return {"category": "math" if any(c.isdigit() for c in q) else "general"}


def math_node(state: State) -> dict:
    return {"answer": "Routing to the math solver..."}


def general_node(state: State) -> dict:
    return {"answer": "Routing to general Q&A..."}


def route(state: State) -> Literal["math_node", "general_node"]:
    return "math_node" if state["category"] == "math" else "general_node"


graph = StateGraph(State)
graph.add_node("classify", classify)
graph.add_node("math_node", math_node)
graph.add_node("general_node", general_node)
graph.add_edge(START, "classify")
graph.add_conditional_edges("classify", route, ["math_node", "general_node"])
graph.add_edge("math_node", END)
graph.add_edge("general_node", END)

app = graph.compile()
```

---

## Example 3: Chat Agent with Tools + Memory

```python
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent


@tool
def get_weather(city: str) -> str:
    """Return the current weather for a city."""
    return f"It is sunny in {city}."


model = init_chat_model("openai:gpt-4o-mini")
agent = create_react_agent(model, tools=[get_weather], checkpointer=MemorySaver())

config = {"configurable": {"thread_id": "demo-1"}}
r1 = agent.invoke({"messages": [{"role": "user", "content": "Weather in Paris?"}]}, config)
# Same thread_id -> the agent remembers the prior turn
r2 = agent.invoke({"messages": [{"role": "user", "content": "And what city did I just ask about?"}]}, config)
print(r2["messages"][-1].content)
```

---

## Example 4: Deep Agent with Filesystem Backend (deepagents)

```python
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    model="openai:gpt-4o-mini",
    backend=FilesystemBackend(root_dir="projects", virtual_mode=True),
    memory=["AGENTS.md"],          # loads projects/AGENTS.md as durable context
    checkpointer=MemorySaver(),
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Who are you?"}]},
    config={"configurable": {"thread_id": "fs-1"}},
)
print(result["messages"][-1].content)
```

---

## Example 5: Streaming Updates

```python
for chunk in app.stream(
    {"messages": [{"role": "user", "content": "hello"}]},
    config={"configurable": {"thread_id": "s-1"}},
    stream_mode="updates",
):
    for node, update in chunk.items():
        print(f"[{node}] -> {update}")
```

---

## Example 6: Human-in-the-Loop Interrupt

```python
from langgraph.types import Command, interrupt


def approval_node(state: State) -> dict:
    decision = interrupt({"question": "Approve this draft?", "draft": state["draft"]})
    return {"approved": decision}


# First invoke pauses at the interrupt; resume with:
app.invoke(Command(resume=True), config={"configurable": {"thread_id": "hitl-1"}})
```