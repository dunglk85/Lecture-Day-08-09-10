"""
workers/synthesis.py — Synthesis Worker
Sprint 2: Tổng hợp câu trả lời từ retrieved_chunks và policy_result.

Input (từ AgentState):
    - task: câu hỏi
    - retrieved_chunks: evidence từ retrieval_worker
    - policy_result: kết quả từ policy_tool_worker

Output (vào AgentState):
    - final_answer: câu trả lời cuối với citation
    - sources: danh sách nguồn tài liệu được cite
    - confidence: mức độ tin cậy (0.0 - 1.0)

Gọi độc lập để test:
    python workers/synthesis.py
"""

import os
import json
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

WORKER_NAME = "synthesis_worker"

SYSTEM_PROMPT = """Bạn là trợ lý AI chuyên nghiệp thuộc bộ phận CS + IT Helpdesk nội bộ.
Nhiệm vụ: Tổng hợp câu trả lời chính xác, trung thực dựa trên các TÀI LIỆU và KẾT QUẢ POLICY được cung cấp.

QUY TẮC NGHIÊM NGẶT:
1. CHỨNG CỨ: Chỉ trả lời dựa trên context được cung cấp. Không dùng kiến thức bên ngoài.
2. TRÍCH DẪN: Luôn trích dẫn nguồn ở cuối câu hoặc đoạn văn bằng số thứ tự của tài liệu trong dấu ngoặc vuông: [1], [2]. Ví dụ: "Thời gian phản hồi P1 là 15 phút [1]".
3. TRUNG THỰC: Nếu không tìm thấy thông tin trong context, hãy nói: "Tôi xin lỗi, thông tin này không có trong tài liệu nội bộ."
4. NGOẠI LỆ: Nếu có POLICY EXCEPTIONS (ví dụ: Flash Sale, Digital Product), phải nêu rõ các ngoại lệ này trước khi kết luận.
5. ĐỊNH DẠNG: Sử dụng bullet points cho danh sách điều kiện hoặc quy trình để dễ đọc.
"""


def _call_llm(messages: list, response_format: str = "text") -> str:
    """
    Gọi LLM để tổng hợp câu trả lời.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "[SYNTHESIS ERROR] OPENAI_API_KEY not found in .env"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        params = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 0,
            "max_tokens": 800,
        }
        
        if response_format == "json_object":
            params["response_format"] = {"type": "json_object"}
            
        response = client.chat.completions.create(**params)
        return response.choices[0].message.content
    except Exception as e:
        return f"[LLM ERROR] {str(e)}"


def _build_context(chunks: list, policy_result: dict) -> str:
    """Xây dựng context string từ chunks và policy result có đánh số để trích dẫn."""
    parts = []
    current_idx = 1

    parts.append("=== DANH SÁCH TÀI LIỆU & QUY ĐỊNH (CONTEXT) ===")

    # 1. Thêm các chunks từ retrieval
    if chunks:
        for chunk in chunks:
            source = chunk.get("source", "unknown")
            text = chunk.get("text", "")
            score = chunk.get("score", 0)
            parts.append(f"[{current_idx}] (Nguồn: {source}, Relevance: {score:.2f}):\n{text}")
            current_idx += 1

    # 2. Thêm các thông tin từ policy tool như là các tài liệu có thể trích dẫn
    if policy_result:
        # Thêm các quy tắc (rules) hoặc ngoại lệ (exceptions) được tìm thấy
        if policy_result.get("exceptions_found"):
            for ex in policy_result["exceptions_found"]:
                type_ex = ex.get('type', 'Exception')
                rule = ex.get('rule', '')
                source = ex.get('source', 'Policy Tool')
                parts.append(f"[{current_idx}] (Nguồn: {source}, Loại: {type_ex}):\nQuy định: {rule}")
                current_idx += 1
        
        # Thêm lưu ý về version nếu có
        if policy_result.get("policy_version_note"):
            parts.append(f"[{current_idx}] (Lưu ý hệ thống): {policy_result['policy_version_note']}")
            current_idx += 1

    if len(parts) <= 1:
        return "KHÔNG CÓ DỮ LIỆU ĐẦU VÀO."

    return "\n\n".join(parts)


def _evaluate_groundedness(task: str, context: str, answer: str) -> float:
    """
    Sử dụng LLM-as-Judge để đánh giá mức độ tin cậy (Confidence).
    """
    try:
        judge_prompt = f"""Bạn là chuyên gia kiểm định chất lượng AI. 
Hãy đánh giá câu trả lời (Answer) dựa trên Context (Tài liệu).

Tiêu chí:
1. Groundedness: Câu trả lời có hoàn toàn dựa trên context không? (0.0 - 1.0)
2. Citation: Có trích dẫn nguồn [tên_file] đầy đủ không? (0.0 - 1.0)
3. Accuracy: Có bỏ sót ngoại lệ nào trong context không? (0.0 - 1.0)

Context: {context[:2000]}
Answer: {answer}

Trả về duy nhất JSON format:
{{"confidence_score": float}}
"""
        messages = [{"role": "user", "content": judge_prompt}]
        response = _call_llm(messages, response_format="json_object")
        data = json.loads(response)
        return float(data.get("confidence_score", 0.5))
    except:
        return 0.5


def synthesize(task: str, chunks: list, policy_result: dict) -> dict:
    """
    Tổng hợp câu trả lời từ chunks và policy context.
    """
    context = _build_context(chunks, policy_result)
    
    if "KHÔNG CÓ DỮ LIỆU" in context:
        return {
            "answer": "Tôi xin lỗi, tôi không tìm thấy tài liệu nào liên quan đến yêu cầu này trong hệ thống nội bộ.",
            "sources": [],
            "confidence": 0.0
        }

    # Build prompt
    prompt = f"""Câu hỏi của User: {task}

Dưới đây là dữ liệu từ hệ thống Knowledge Base và Policy Tool:
-----------------
{context}
-----------------

Hãy trả lời câu hỏi của User một các chuyên nghiệp."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    answer = _call_llm(messages)
    sources = list({c.get("source", "unknown") for c in chunks})
    
    # Thêm sources từ policy_result nếu có
    if policy_result and policy_result.get("source"):
        if isinstance(policy_result["source"], list):
            sources.extend(policy_result["source"])
        else:
            sources.append(policy_result["source"])
    
    sources = list(set(sources)) # Unique

    # Ước tính confidence (Kết hợp heuristics + LLM check)
    confidence = _evaluate_groundedness(task, context, answer)

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
    }


def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    policy_result = state.get("policy_result", {})

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {
            "task": task,
            "chunks_count": len(chunks),
            "has_policy": bool(policy_result),
        },
        "output": None,
        "error": None,
    }

    try:
        result = synthesize(task, chunks, policy_result)
        state["final_answer"] = result["answer"]
        state["retrieved_sources"] = result["sources"] # Đồng bộ key với retrieval_worker
        state["confidence"] = result["confidence"]

        worker_io["output"] = {
            "answer_length": len(result["answer"]),
            "sources": result["sources"],
            "confidence": result["confidence"],
        }
        state["history"].append(
            f"[{WORKER_NAME}] confidence={result['confidence']}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "SYNTHESIS_FAILED", "reason": str(e)}
        state["final_answer"] = f"SYNTHESIS_ERROR: {e}"
        state["confidence"] = 0.0
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


if __name__ == "__main__":
    print("=" * 50)
    print("Synthesis Worker — Standalone Test")
    print("=" * 50)

    # Test Case 1: Standard FAQ
    test_state = {
        "task": "Thời gian xử lý ticket P1 là bao lâu?",
        "retrieved_chunks": [
            {
                "text": "Ticket P1 (Nghiêm trọng): Phàn hồi 15 phút. Xử lý khắc phục trong 4 giờ.",
                "source": "support/sla-p1-2026.pdf",
                "score": 0.95
            }
        ],
        "policy_result": {}
    }

    print("\n▶ Test Case 1: SLA query")
    res1 = run(test_state)
    print(f"Answer: {res1['final_answer']}")
    print(f"Confidence: {res1['confidence']}")

    # Test Case 2: Policy Exception
    test_state2 = {
        "task": "Hoàn tiền cho đơn hàng Flash Sale được không?",
        "retrieved_chunks": [
            {"text": "Chính sách hoàn tiền v4 áp dụng cho mọi đơn hàng từ 01/02/2026.", "source": "policy/refund-v4.pdf", "score": 0.8}
        ],
        "policy_result": {
            "policy_name": "Refund Policy v4",
            "policy_applies": False,
            "exceptions_found": [
                {"type": "Flash Sale", "rule": "Đơn hàng Flash Sale không được hoàn tiền.", "source": "Manual"}
            ]
        }
    }
    print("\n▶ Test Case 2: Policy Exception")
    res2 = run(test_state2)
    print(f"Answer: {res2['final_answer']}")
    print(f"Confidence: {res2['confidence']}")

    print("\n✅ synthesis_worker test done.")
