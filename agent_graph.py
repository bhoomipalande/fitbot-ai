import json
import re
from typing import TypedDict, Callable
from google import genai
from google.genai import types

from rag_engine import retrieve_relevant_context

try:
    from langgraph.graph import StateGraph, END
except ImportError:
    END = "__end__"

    class _CompiledGraph:
        def __init__(self, nodes, edges, cond_edges, entry):
            self.nodes = nodes
            self.edges = edges
            self.cond_edges = cond_edges
            self.entry = entry

        def invoke(self, state: dict) -> dict:
            curr = self.entry
            while curr and curr != END:
                updates = self.nodes[curr](state)
                if updates:
                    state.update(updates)
                if curr in self.cond_edges:
                    router_fn, mapping = self.cond_edges[curr]
                    curr = mapping[router_fn(state)]
                else:
                    curr = self.edges.get(curr, END)
            return state

    class StateGraph:
        def __init__(self, state_schema):
            self.nodes = {}
            self.edges = {}
            self.cond_edges = {}
            self.entry = None

        def add_node(self, name: str, fn: Callable):
            self.nodes[name] = fn

        def set_entry_point(self, name: str):
            self.entry = name

        def add_edge(self, src: str, dst: str):
            self.edges[src] = dst

        def add_conditional_edges(self, src: str, router_fn: Callable, mapping: dict):
            self.cond_edges[src] = (router_fn, mapping)

        def compile(self):
            return _CompiledGraph(self.nodes, self.edges, self.cond_edges, self.entry)


class AgentState(TypedDict):
    query: str
    conversation_history: str
    active_gym: dict
    gym_data: str
    rag_docs: list[dict]
    rag_embeddings: list[list[float]]
    retrieved_chunks: list[dict]
    tool_decision: dict
    tool_output: str
    final_response: str
    nodes_visited: list[str]


def build_fitbot_graph(
    client: genai.Client,
    models: list[str],
    calc_macros_fn: Callable,
    book_trainer_fn: Callable,
):
    """Builds a multi-node StateGraph for Semantic RAG + Autonomous Tool Routing."""

    def _call_llm(prompt: str) -> str:
        for model_name in models:
            try:
                res = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.3),
                )
                return res.text or ""
            except Exception:
                continue
        return ""

    # ---------------------------------------------------------
    # NODE 1: Semantic RAG Retrieval
    # ---------------------------------------------------------
    def retrieve_rag_node(state: AgentState) -> dict:
        chunks = []
        if state["rag_embeddings"]:
            chunks = retrieve_relevant_context(
                client=client,
                query=state["query"],
                docs=state["rag_docs"],
                doc_embeddings=state["rag_embeddings"],
                top_k=3,
            )
        return {
            "retrieved_chunks": chunks,
            "nodes_visited": state["nodes_visited"] + ["1. retrieve_rag"],
        }

    # ---------------------------------------------------------
    # NODE 2: Autonomous Intent & Tool Router
    # ---------------------------------------------------------
    def agent_router_node(state: AgentState) -> dict:
        router_prompt = f"""
Analyze the latest user query and decide if an external backend tool must be executed.

AVAILABLE TOOLS:
1. "calculate_macros": Use when the user asks for daily calories, diet macros, or protein targets and provides weight in kg.
   Args: {{"weight_kg": float, "goal": "weight loss" | "muscle gain" | "maintenance"}}
2. "book_trainer_session": Use when the user wants to book/schedule a personal training session with a trainer.
   Args: {{"trainer_name": str, "time_slot": str, "member_name": str}}
3. "none": Use for policy questions, workout advice, timings, fees, or general chat.

CONVERSATION:
{state['conversation_history']}

LATEST USER QUERY: {state['query']}

Return ONLY valid JSON with keys "tool" and "args". Example:
{{"tool": "book_trainer_session", "args": {{"trainer_name": "Rahul Sharma", "time_slot": "tomorrow at 7 AM", "member_name": "Bhoomi"}}}}
or
{{"tool": "none", "args": {{}}}}
"""
        raw = _call_llm(router_prompt)
        decision = {"tool": "none", "args": {}}
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if parsed.get("tool") in ["calculate_macros", "book_trainer_session", "none"]:
                    decision = parsed
        except Exception:
            decision = {"tool": "none", "args": {}}

        return {
            "tool_decision": decision,
            "nodes_visited": state["nodes_visited"] + ["2. agent_router"],
        }

    # ---------------------------------------------------------
    # CONDITIONAL EDGE: Should Execute Tool?
    # ---------------------------------------------------------
    def route_after_decision(state: AgentState) -> str:
        tool_name = state.get("tool_decision", {}).get("tool", "none")
        if tool_name in ["calculate_macros", "book_trainer_session"]:
            return "execute_tools"
        return "generate_reply"

    # ---------------------------------------------------------
    # NODE 3: Backend Tool & Database Executor
    # ---------------------------------------------------------
    def execute_tools_node(state: AgentState) -> dict:
        decision = state["tool_decision"]
        tool_name = decision.get("tool")
        args = decision.get("args", {})
        output = ""

        if tool_name == "calculate_macros":
            weight = float(args.get("weight_kg", 70.0))
            goal = str(args.get("goal", "maintenance"))
            output = calc_macros_fn(weight_kg=weight, goal=goal)

        elif tool_name == "book_trainer_session":
            trainer = str(args.get("trainer_name", "Rahul Sharma"))
            slot = str(args.get("time_slot", "Tomorrow 7:00 AM"))
            member = str(args.get("member_name", "Walk-in Member"))
            output = book_trainer_fn(trainer_name=trainer, time_slot=slot, member_name=member)

        return {
            "tool_output": output,
            "nodes_visited": state["nodes_visited"] + [f"3. execute_tools ({tool_name})"],
        }

    # ---------------------------------------------------------
    # NODE 4: Grounded Final Response Synthesizer
    # ---------------------------------------------------------
    def generate_reply_node(state: AgentState) -> dict:
        active_gym = state["active_gym"]
        rag_context = "\n".join(
            [f"- [{c['title']} | Match: {c['score']}]: {c['content']}" for c in state["retrieved_chunks"]]
        )
        tool_section = f"\nBACKEND TOOL EXECUTION RESULT:\n{state['tool_output']}\n" if state["tool_output"] else ""

        final_prompt = f"""
You are FitBot AI, the virtual concierge for {active_gym['name']} ({active_gym['city']}).

ACTIVE BRANCH PROFILE:
- Club: {active_gym['name']} ({active_gym['city']})
- Hours: {active_gym['timings']}
- Standard Plan: {active_gym['monthly_fee']}

RETRIEVED KNOWLEDGE BASE (RAG):
{rag_context}

TRAINERS & SESSIONS:
{state['gym_data']}
{tool_section}
CONVERSATION HISTORY:
{state['conversation_history']}

INSTRUCTIONS:
- Ground policy, freeze, refund, guest pass, and pricing answers strictly in the retrieved RAG context.
- If a backend tool executed above, confirm the exact action/calculation clearly and mention any relevant club rule from RAG.
- Keep the response warm, structured, and concise.
"""
        reply = _call_llm(final_prompt)
        return {
            "final_response": reply or "I'm ready to help! Could you please repeat your request?",
            "nodes_visited": state["nodes_visited"] + ["4. generate_reply"],
        }

    workflow = StateGraph(AgentState)
    workflow.add_node("retrieve_rag", retrieve_rag_node)
    workflow.add_node("agent_router", agent_router_node)
    workflow.add_node("execute_tools", execute_tools_node)
    workflow.add_node("generate_reply", generate_reply_node)

    workflow.set_entry_point("retrieve_rag")
    workflow.add_edge("retrieve_rag", "agent_router")
    workflow.add_conditional_edges(
        "agent_router",
        route_after_decision,
        {
            "execute_tools": "execute_tools",
            "generate_reply": "generate_reply",
        },
    )
    workflow.add_edge("execute_tools", "generate_reply")
    workflow.add_edge("generate_reply", END)

    return workflow.compile()