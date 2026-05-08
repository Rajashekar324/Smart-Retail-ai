from typing import TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover
    END = None
    StateGraph = None


class ChatState(TypedDict):
    query: str
    intent: str


def detect_intent(state: ChatState):
    q = state["query"].lower()
    if "order" in q or "track" in q:
        return {"intent": "order_support"}
    if "product" in q or "size" in q or "price" in q:
        return {"intent": "product_support"}
    return {"intent": "general_support"}


def build_agent_graph():
    if StateGraph is None:
        return None
    graph = StateGraph(ChatState)
    graph.add_node("detect_intent", detect_intent)
    graph.set_entry_point("detect_intent")
    graph.add_edge("detect_intent", END)
    return graph.compile()


agent_graph = build_agent_graph()
