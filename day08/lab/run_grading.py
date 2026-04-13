import json
import os
from datetime import datetime
from rag_answer import rag_answer

grading_file = "data/grading_questions.json"
test_file = "data/test_questions.json"

target_file = grading_file if os.path.exists(grading_file) else test_file

print(f"Reading questions from: {target_file}")
with open(target_file, encoding='utf-8') as f:
    questions = json.load(f)

log = []
for q in questions:
    print(f"Processing query: {q.get('id')} - {q.get('question')[:50]}...")
    result = rag_answer(q["question"], retrieval_mode="hybrid", use_rerank=True, transform_strategy=None, verbose=False)
    log.append({
        "id": q["id"],
        "question": q["question"],
        "answer": result["answer"],
        "sources": result["sources"],
        "chunks_retrieved": len(result["chunks_used"]),
        "retrieval_mode": result["config"]["retrieval_mode"],
        "timestamp": datetime.now().isoformat(),
    })

os.makedirs("logs", exist_ok=True)
output_file = "logs/grading_run.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

print(f"Báo cáo chấm điểm đã được lưu tại {output_file}")
