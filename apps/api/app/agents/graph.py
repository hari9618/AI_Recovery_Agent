"""LangGraph wiring for the Revenue Recovery agent.

Two explicit graphs with a durable hand-off in PostgreSQL (approvals can take hours or days and must
survive restarts):

  investigation:  load_context → analyze_conversation → assess_risk ─(low risk)→ END
                  → retrieve_knowledge → recommend → ground_check → policy_check → persist_recommendation
                  ─(approval required / blocked)→ END
                  ─(auto)→ execute_action → verify → END

  execution (after a human approves):  execute_action → verify → END

There is no open-ended agent loop: every transition is a named edge with a deterministic condition.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.state import RevenueRecoveryState


def _after_load(state: RevenueRecoveryState) -> str:
    return END if state.get("status") == "failed" else "analyze_conversation"


def _after_risk(state: RevenueRecoveryState) -> str:
    return END if state.get("status") in ("failed", "no_action_needed") else "retrieve_knowledge"


def _after_persist(state: RevenueRecoveryState) -> str:
    return END if state.get("status") in ("awaiting_approval", "blocked", "failed") else "execute_action"


@lru_cache
def investigation_graph():
    g = StateGraph(RevenueRecoveryState)
    for name in (
        "load_context",
        "analyze_conversation",
        "assess_risk",
        "retrieve_knowledge",
        "recommend",
        "ground_check",
        "policy_check",
        "persist_recommendation",
        "execute_action",
        "verify",
    ):
        g.add_node(name, getattr(nodes, name))
    g.add_edge(START, "load_context")
    g.add_conditional_edges("load_context", _after_load, ["analyze_conversation", END])
    g.add_edge("analyze_conversation", "assess_risk")
    g.add_conditional_edges("assess_risk", _after_risk, ["retrieve_knowledge", END])
    g.add_edge("retrieve_knowledge", "recommend")
    g.add_edge("recommend", "ground_check")
    g.add_edge("ground_check", "policy_check")
    g.add_edge("policy_check", "persist_recommendation")
    g.add_conditional_edges("persist_recommendation", _after_persist, ["execute_action", END])
    g.add_edge("execute_action", "verify")
    g.add_edge("verify", END)
    return g.compile()


@lru_cache
def execution_graph():
    g = StateGraph(RevenueRecoveryState)
    g.add_node("execute_action", nodes.execute_action)
    g.add_node("verify", nodes.verify)
    g.add_edge(START, "execute_action")
    g.add_edge("execute_action", "verify")
    g.add_edge("verify", END)
    return g.compile()


def mermaid() -> str:
    """Rendered into docs/agent-workflow.md."""
    return investigation_graph().get_graph().draw_mermaid()
