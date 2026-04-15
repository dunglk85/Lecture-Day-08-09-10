"""
workers/policy_tool.py — Policy & Tool Worker
Sprint 2+3: Kiểm tra policy dựa vào context, gọi MCP tools khi cần.

Input (từ AgentState):
    - task: câu hỏi
    - retrieved_chunks: context từ retrieval_worker
    - needs_tool: True nếu supervisor quyết định cần tool call

Output (vào AgentState):
    - policy_result: {"policy_applies", "policy_name", "exceptions_found", "source", "rule"}
    - mcp_tools_used: list of tool calls đã thực hiện
    - worker_io_log: log

Gọi độc lập để test:
    python workers/policy_tool.py
"""

import os
import sys
import json
import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to sys.path to allow importing from other files
sys.path.append(str(os.path.dirname(os.path.dirname(__file__))))

WORKER_NAME = "policy_tool_worker"


# ─────────────────────────────────────────────
# MCP Client — Interaction with mcp_server.py
# ─────────────────────────────────────────────

def _call_mcp_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Gọi MCP tool thông qua dispatch_tool của mcp_server.
    """
    try:
        from mcp_server import dispatch_tool
        result = dispatch_tool(tool_name, tool_input)
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": result,
            "error": None,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": None,
            "error": {"code": "MCP_CALL_FAILED", "reason": str(e)},
            "timestamp": datetime.now().isoformat(),
        }


# ─────────────────────────────────────────────
# LLM Analysis — Complex Policy Reasoning
# ─────────────────────────────────────────────

def _call_llm_analysis(task: str, context: str) -> Optional[Dict[str, Any]]:
    """
    Gọi LLM để phân tích policy và phát hiện exceptions.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        system_prompt = """Bạn là chuyên gia phân tích chính sách nội bộ (Policy Analyst).
Nhiệm vụ: Dựa vào context, xác định câu hỏi của user có vi phạm quy định nào không hoặc có ngoại lệ (exception) nào áp dụng không.

Các ngoại lệ phổ biến cần chú ý:
1. Flash Sale: Không được hoàn tiền.
2. Sản phẩm kỹ thuật số/License/Subscription: Không được hoàn tiền.
3. Sản phẩm đã kích hoạt/sử dụng: Không được hoàn tiền.
4. Đơn hàng trước 01/02/2026: Áp dụng chính sách v3 cũ (ngoài phạm vi tài liệu hiện tại).

Trả về kết quả dưới dạng JSON:
{
  "policy_applies": boolean,
  "policy_name": string,
  "exceptions_found": [{"type": string, "rule": string, "source": string}],
  "explanation": string
}
"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Task: {task}\n\nContext:\n{context}"}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"⚠️  LLM Analysis failed: {e}. Falling back to rule-based.")
        return None


# ─────────────────────────────────────────────
# Policy Analysis Logic
# ─────────────────────────────────────────────

def analyze_policy(task: str, chunks: List[Dict]) -> Dict[str, Any]:
    """
    Phân tích policy kết hợp Rule-based và LLM.
    """
    task_lower = task.lower()
    context_text = "\n".join([c.get("text", "") for c in chunks])
    
    # 1. Thử LLM Analysis trước nếu có data
    if chunks:
        analysis = _call_llm_analysis(task, context_text)
        if analysis:
            # Bổ sung source và version note
            analysis["source"] = list({c.get("source", "unknown") for c in chunks if c})
            analysis["policy_version_note"] = ""
            if "trước 01/02" in task_lower or "trước ngày 01/02" in task_lower:
                analysis["policy_version_note"] = "Đơn hàng trước 01/02/2026 áp dụng chính sách v3."
            return analysis

    # 2. Fallback: Rule-based exception detection
    exceptions_found = []
    
    if "flash sale" in task_lower or "flash sale" in context_text.lower():
        exceptions_found.append({
            "type": "flash_sale_exception",
            "rule": "Đơn hàng Flash Sale không được hoàn tiền (Điều 3, chính sách v4).",
            "source": "policy_refund_v4.txt",
        })

    if any(kw in task_lower for kw in ["license key", "license", "subscription", "kỹ thuật số"]):
        exceptions_found.append({
            "type": "digital_product_exception",
            "rule": "Sản phẩm kỹ thuật số không được hoàn tiền (Điều 3).",
            "source": "policy_refund_v4.txt",
        })

    if any(kw in task_lower for kw in ["đã kích hoạt", "đã đăng ký", "đã sử dụng"]):
        exceptions_found.append({
            "type": "activated_exception",
            "rule": "Sản phẩm đã kích hoạt không được hoàn tiền (Điều 3).",
            "source": "policy_refund_v4.txt",
        })

    policy_applies = len(exceptions_found) == 0
    policy_version_note = ""
    if "trước 01/02" in task_lower:
        policy_version_note = "Đơn hàng đặt trước 01/02/2026 áp dụng chính sách v3."

    return {
        "policy_applies": policy_applies,
        "policy_name": "refund_policy_v4",
        "exceptions_found": exceptions_found,
        "source": list({c.get("source", "unknown") for c in chunks if c}),
        "policy_version_note": policy_version_note,
        "explanation": "Analyzed via rule-based fallback.",
    }


# ─────────────────────────────────────────────
# Worker Entry Point
# ─────────────────────────────────────────────

def run(state: Dict) -> Dict:
    """
    Worker entry point.
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    needs_tool = state.get("needs_tool", False)

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state.setdefault("mcp_tools_used", [])

    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {"task": task, "chunks_count": len(chunks), "needs_tool": needs_tool},
        "output": None,
        "error": None,
    }

    try:
        # Step 1: Gọi MCP tools nếu cần
        if needs_tool:
            # A. Nếu chưa có chunks -> Search KB
            if not chunks:
                mcp_res = _call_mcp_tool("search_kb", {"query": task, "top_k": 3})
                state["mcp_tools_used"].append(mcp_res)
                if mcp_res.get("output") and "chunks" in mcp_res["output"]:
                    chunks = mcp_res["output"]["chunks"]
                    state["retrieved_chunks"] = chunks

            # B. Nếu hỏi về ticket -> get_ticket_info
            if any(kw in task.lower() for kw in ["ticket", "p1", "jira", "it-"]):
                ticket_id = "P1-LATEST"
                match = re.search(r"(IT-\d+)", task.upper())
                if match: ticket_id = match.group(1)
                
                mcp_res = _call_mcp_tool("get_ticket_info", {"ticket_id": ticket_id})
                state["mcp_tools_used"].append(mcp_res)

            # C. Nếu hỏi về quyền truy cập -> check_access_permission
            if any(kw in task.lower() for kw in ["quyền", "access", "level"]):
                level = 1
                if "level 2" in task.lower(): level = 2
                elif "level 3" in task.lower(): level = 3
                
                mcp_res = _call_mcp_tool("check_access_permission", {
                    "access_level": level,
                    "requester_role": "employee",
                    "is_emergency": "khẩn cấp" in task.lower() or "emergency" in task.lower()
                })
                state["mcp_tools_used"].append(mcp_res)

        # Step 2: Phân tích chính sách
        policy_result = analyze_policy(task, chunks)
        state["policy_result"] = policy_result

        worker_io["output"] = {
            "policy_applies": policy_result.get("policy_applies"),
            "exceptions": len(policy_result.get("exceptions_found", [])),
            "mcp_calls": len(state["mcp_tools_used"])
        }
        state["history"].append(f"[{WORKER_NAME}] Policy checked, {len(state['mcp_tools_used'])} MCP tools called.")

    except Exception as e:
        worker_io["error"] = {"code": "POLICY_WORKER_ERROR", "reason": str(e)}
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


if __name__ == "__main__":
    print("=" * 50)
    print("Policy Tool Worker — Standalone Test")
    print("=" * 50)

    # Test Case 1: Refund Exception
    test_task = "Khách hàng mua Flash Sale ngày 15/01/2026 muốn hoàn tiền license key đã kích hoạt được không?"
    print(f"\n▶ Test Case 1: {test_task}")
    test_state = {"task": test_task, "needs_tool": True}
    result = run(test_state)
    print(json.dumps(result["policy_result"], indent=2, ensure_ascii=False))
    
    # Test Case 2: Access Permission
    test_task2 = "Tôi cần cấp quyền level 2 khẩn cấp để sửa lỗi P1."
    print(f"\n▶ Test Case 2: {test_task2}")
    test_state2 = {"task": test_task2, "needs_tool": True}
    result2 = run(test_state2)
    print(f"MCP calls: {len(result2['mcp_tools_used'])}")
    for mcp in result2["mcp_tools_used"]:
        print(f"  - {mcp['tool']} -> {mcp['output'].get('can_grant') or 'KB search'}")

    print("\n✅ policy_tool_worker test done.")
