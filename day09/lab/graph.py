"""
graph.py — Supervisor Orchestrator
Sprint 1: Implement AgentState, supervisor_node, route_decision và kết nối graph.

Kiến trúc:
    Input → Supervisor → [retrieval_worker | policy_tool_worker | human_review] → synthesis → Output

Chạy thử:
    python graph.py
"""

import json
import os
from datetime import datetime
from typing import TypedDict, Literal, Optional

# Uncomment nếu dùng LangGraph:
# from langgraph.graph import StateGraph, END

# ─────────────────────────────────────────────
# 1. Shared State — dữ liệu đi xuyên toàn graph
# ─────────────────────────────────────────────

class AgentState(TypedDict):
    # Input
    task: str                           # Câu hỏi đầu vào từ user

    # Supervisor decisions
    route_reason: str                   # Lý do route sang worker nào
    risk_high: bool                     # True → cần HITL hoặc human_review
    needs_tool: bool                    # True → cần gọi external tool qua MCP
    hitl_triggered: bool                # True → đã pause cho human review

    # Worker outputs
    retrieved_chunks: list              # Output từ retrieval_worker
    retrieved_sources: list             # Danh sách nguồn tài liệu
    policy_result: dict                 # Output từ policy_tool_worker
    mcp_tools_used: list                # Danh sách MCP tools đã gọi

    # Final output
    final_answer: str                   # Câu trả lời tổng hợp
    sources: list                       # Sources được cite
    confidence: float                   # Mức độ tin cậy (0.0 - 1.0)

    # Trace & history
    history: list                       # Lịch sử các bước đã qua
    workers_called: list                # Danh sách workers đã được gọi
    supervisor_route: str               # Worker được chọn bởi supervisor
    latency_ms: Optional[int]           # Thời gian xử lý (ms)
    run_id: str                         # ID của run này


def make_initial_state(task: str) -> AgentState:
    """Khởi tạo state cho một run mới."""
    return {
        "task": task,
        "route_reason": "",
        "risk_high": False,
        "needs_tool": False,
        "hitl_triggered": False,
        "retrieved_chunks": [],
        "retrieved_sources": [],
        "policy_result": {},
        "mcp_tools_used": [],
        "final_answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": [],
        "workers_called": [],
        "supervisor_route": "",
        "latency_ms": None,
        "run_id": f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    }


# ─────────────────────────────────────────────
# 2. Supervisor Node — quyết định route
# ─────────────────────────────────────────────

def supervisor_node(state: AgentState) -> AgentState:
    task = state["task"]
    task_lower = task.lower()
    state["history"].append(f"[supervisor] received task: {task[:80]}")

    # ── Keyword sets ──────────────────────────────────────────
    POLICY_KEYWORDS   = ["hoàn tiền", "refund", "flash sale", "license",
                         "cấp quyền", "access level", "level 2", "level 3",
                         "quyền truy cập", "store credit", "ngoại lệ"]
    SLA_KEYWORDS      = ["p1", "sla", "ticket", "escalat", "sự cố",
                         "incident", "on-call", "oncall", "phản hồi",
                         "resolution", "xử lý sự cố"]
    UNKNOWN_ERR_PAT   = r"err[-_]\d{3,}"   # ERR-403, ERR_500, v.v.
    RISK_KEYWORDS     = ["emergency", "khẩn cấp", "2am", "ngoài giờ",
                         "không có ai", "bypass", "tạm thời"]

    import re

    # ── Detect signals ────────────────────────────────────────
    has_policy  = any(kw in task_lower for kw in POLICY_KEYWORDS)
    has_sla     = any(kw in task_lower for kw in SLA_KEYWORDS)
    has_err     = bool(re.search(UNKNOWN_ERR_PAT, task_lower))
    has_risk    = any(kw in task_lower for kw in RISK_KEYWORDS)

    # ── Routing decision (priority order) ─────────────────────
    # 1. Unknown error code với không đủ context → human_review
    if has_err and not (has_policy or has_sla):
        route        = "human_review"
        route_reason = f"unknown error code pattern detected (e.g. ERR-xxx), no domain context"
        risk_high    = True
        needs_tool   = False

    # 2. Policy / access control questions → policy_tool_worker
    elif has_policy:
        route        = "policy_tool_worker"
        matched      = [kw for kw in POLICY_KEYWORDS if kw in task_lower]
        route_reason = f"policy keyword matched: {matched}"
        risk_high    = has_risk
        needs_tool   = True   # cần gọi MCP check_access hoặc search_kb

    # 3. SLA / incident / ticket questions → retrieval_worker
    elif has_sla:
        route        = "retrieval_worker"
        matched      = [kw for kw in SLA_KEYWORDS if kw in task_lower]
        route_reason = f"SLA/incident keyword matched: {matched}"
        risk_high    = has_risk
        needs_tool   = False

    # 4. Default → retrieval_worker
    else:
        route        = "retrieval_worker"
        route_reason = "no specific keyword matched, default to retrieval"
        risk_high    = False
        needs_tool   = False

    # ── Risk override: luôn ghi lý do nếu risk_high ───────────
    if has_risk and risk_high:
        risk_matched  = [kw for kw in RISK_KEYWORDS if kw in task_lower]
        route_reason += f" | risk_high: {risk_matched}"

    # ── Multi-hop detection: có cả SLA lẫn policy → cần cả 2 ──
    if has_sla and has_policy:
        route        = "policy_tool_worker"   # policy worker sẽ gọi retrieval nếu cần
        route_reason = f"multi-hop: SLA+policy keywords both present → policy_tool_worker leads"
        needs_tool   = True

    state["supervisor_route"] = route
    state["route_reason"]     = route_reason
    state["needs_tool"]       = needs_tool
    state["risk_high"]        = risk_high
    state["history"].append(f"[supervisor] route={route} | reason={route_reason}")

    return state

# ─────────────────────────────────────────────
# 3. Route Decision — conditional edge
# ─────────────────────────────────────────────

def route_decision(state: AgentState) -> Literal["retrieval_worker", "policy_tool_worker", "human_review"]:
    """
    Trả về tên worker tiếp theo dựa vào supervisor_route trong state.
    Đây là conditional edge của graph.
    """
    route = state.get("supervisor_route", "retrieval_worker")
    return route  # type: ignore


# ─────────────────────────────────────────────
# 4. Human Review Node — HITL placeholder
# ─────────────────────────────────────────────

def human_review_node(state: AgentState) -> AgentState:
    """
    HITL node: pause và chờ human approval.
    Trong lab này, implement dưới dạng placeholder (in ra warning).

    TODO Sprint 3 (optional): Implement actual HITL với interrupt_before hoặc
    breakpoint nếu dùng LangGraph.
    """
    state["hitl_triggered"] = True
    state["history"].append("[human_review] HITL triggered — awaiting human input")
    state["workers_called"].append("human_review")

    # Placeholder: tự động approve để pipeline tiếp tục
    print(f"\n⚠️  HITL TRIGGERED")
    print(f"   Task: {state['task']}")
    print(f"   Reason: {state['route_reason']}")
    print(f"   Action: Auto-approving in lab mode (set hitl_triggered=True)\n")

    # Sau khi human approve, route về retrieval để lấy evidence
    state["supervisor_route"] = "retrieval_worker"
    state["route_reason"] += " | human approved → retrieval"

    return state
# ─────────────────────────────────────────────
# 5. Import Workers
# ─────────────────────────────────────────────

# TODO Sprint 2: Uncomment sau khi implement workers
# from workers.retrieval import run as retrieval_run
# from workers.policy_tool import run as policy_tool_run
# from workers.synthesis import run as synthesis_run


def retrieval_worker_node(state: AgentState) -> AgentState:
    """Wrapper gọi retrieval worker."""
    # TODO Sprint 2: Thay bằng retrieval_run(state)
    try:
        from workers.retrieval import run as retrieval_run
        return retrieval_run(state)
    except ImportError as e:
        # Fallback nếu worker chưa implement
        state["workers_called"].append("retrieval_worker")
        state["history"].append(f"[retrieval_worker] IMPORT ERROR: {e}")
        state["retrieved_chunks"] = []
        state["retrieved_sources"] = []
        return state


def policy_tool_worker_node(state: AgentState) -> AgentState:
    """Wrapper gọi policy/tool worker."""
    # TODO Sprint 2: Thay bằng policy_tool_run(state)
    try:
        from workers.policy_tool import run as policy_tool_run
        return policy_tool_run(state)
    except ImportError as e:
        state["workers_called"].append("policy_tool_worker")
        state["history"].append(f"[policy_tool_worker] IMPORT ERROR: {e}")
        state["policy_result"] = {}
        return state


def synthesis_worker_node(state: AgentState) -> AgentState:
    """Wrapper gọi synthesis worker."""
    # TODO Sprint 2: Thay bằng synthesis_run(state)
    try:
        from workers.synthesis import run as synthesis_run
        return synthesis_run(state)
    except ImportError as e:
        state["workers_called"].append("synthesis_worker")
        state["history"].append(f"[synthesis_worker] IMPORT ERROR: {e}")
        state["final_answer"] = f"SYNTHESIS_ERROR: {e}"
        state["confidence"] = 0.0
        return state


# ─────────────────────────────────────────────
# 6. Build Graph
# ─────────────────────────────────────────────

def build_graph():
    def run(state: AgentState) -> AgentState:
        import time
        start = time.time()

        # ── Step 1: Supervisor quyết định route ──────────────
        state = supervisor_node(state)
        route = route_decision(state)

        # ── Step 2: Route đến worker phù hợp ─────────────────
        if route == "human_review":
            # HITL: pause → auto-approve trong lab → tiếp tục retrieval
            state = human_review_node(state)
            state = retrieval_worker_node(state)
            state = synthesis_worker_node(state)

        elif route == "policy_tool_worker":
            # Multi-hop: retrieval trước để có chunks,
            # sau đó policy check dùng chunks đó
            state = retrieval_worker_node(state)
            state = policy_tool_worker_node(state)
            state = synthesis_worker_node(state)

        else:
            # Default: retrieval → synthesis
            state = retrieval_worker_node(state)
            state = synthesis_worker_node(state)

        # ── Step 3: Finalize ──────────────────────────────────
        state["latency_ms"] = int((time.time() - start) * 1000)
        state["history"].append(
            f"[graph] completed in {state['latency_ms']}ms | "
            f"workers={state['workers_called']} | "
            f"confidence={state.get('confidence', 0)}"
        )
        return state

    return run


# ─────────────────────────────────────────────
# 7. Public API
# ─────────────────────────────────────────────

_graph = build_graph()


def run_graph(task: str) -> AgentState:
    """
    Entry point: nhận câu hỏi, trả về AgentState với full trace.

    Args:
        task: Câu hỏi từ user

    Returns:
        AgentState với final_answer, trace, routing info, v.v.
    """
    state = make_initial_state(task)
    result = _graph(state)
    return result


def save_trace(state: AgentState, output_dir: str = "./artifacts/traces") -> str:
    """Lưu trace ra file JSON."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{output_dir}/{state['run_id']}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return filename


# ─────────────────────────────────────────────
# 8. Manual Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Day 09 Lab — Supervisor-Worker Graph")
    print("=" * 60)

    test_queries = [
        "SLA xử lý ticket P1 là bao lâu?",
        "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
        "Cần cấp quyền Level 3 để khắc phục P1 khẩn cấp. Quy trình là gì?",
    ]

    for query in test_queries:
        print(f"\n▶ Query: {query}")
        result = run_graph(query)
        print(f"  Route   : {result['supervisor_route']}")
        print(f"  Reason  : {result['route_reason']}")
        print(f"  Workers : {result['workers_called']}")
        print(f"  Answer  : {result['final_answer'][:100]}...")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Latency : {result['latency_ms']}ms")

        # Lưu trace
        trace_file = save_trace(result)
        print(f"  Trace saved → {trace_file}")

    print("\n✅ graph.py test complete. Implement TODO sections in Sprint 1 & 2.")
