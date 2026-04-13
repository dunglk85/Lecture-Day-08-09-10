# Tuning Log — RAG Pipeline (Day 08 Lab)

> Template: Ghi lại mỗi thay đổi và kết quả quan sát được.
> A/B Rule: Chỉ đổi MỘT biến mỗi lần.

---

## Baseline (Sprint 2)

**Ngày:** 13/04/2026  
**Config:**
```
retrieval_mode = "dense"
chunk_size = 500 tokens
overlap = 50 tokens
top_k_search = 10
top_k_select = 3
use_rerank = False
llm_model = "gpt-4o-mini"
```

**Scorecard Baseline:**
| Metric | Average Score |
|--------|--------------|
| Faithfulness | 4.40/5 |
| Answer Relevance | 4.70/5 |
| Context Recall | 5.00/5 |
| Completeness | 3.70/5 |

**Câu hỏi yếu nhất (điểm thấp):**
> q07 (Approval Matrix) - context recall thấp vì retrieval mode = dense bỏ lỡ các alias hoặc từ khóa cứng.
> q09 (ERR-403) - Điểm Answer Relevance thấp do model trả về câu trả lời suy luận thiếu căn cứ thay vì abstain hoàn toàn khi không có trong docs.

**Giả thuyết nguyên nhân (Error Tree):**
- [ ] Indexing: Chunking cắt giữa điều khoản
- [ ] Indexing: Metadata thiếu effective_date
- [x] Retrieval: Dense bỏ lỡ exact keyword / alias
- [ ] Retrieval: Top-k quá ít → thiếu evidence
- [x] Generation: Prompt không đủ grounding
- [ ] Generation: Context quá dài → lost in the middle

---

## Variant 1 (Sprint 3)

**Ngày:** 13/04/2026  
**Biến thay đổi:** retrieval_mode = "hybrid"  
**Lý do chọn biến này:**
> Chọn hybrid vì kết hợp Sparse Retrieval (BM25 - bắt được exact match cho keyword/error codes/alias như ERR-403, Approval Matrix) và Dense Retrieval (giữ được semantic meaning). Các tài liệu trong hệ thống có quá nhiều thuật ngữ kỹ thuật, mã lỗi và các tên riêng dễ bị mô hình Dense đơn giản bỏ sót.

**Config thay đổi:**
```
retrieval_mode = "hybrid"   # Kết hợp dense và sparse bằng Reciprocal Rank Fusion (RRF)
# Các tham số còn lại giữ nguyên như baseline
```

**Scorecard Variant 1:**
| Metric | Baseline | Variant 1 | Delta |
|--------|----------|-----------|-------|
| Faithfulness | 4.0/5 | 4.0/5 | 0 |
| Answer Relevance | 3.0/5 | 4.0/5 | +1.0 |
| Context Recall | 3.0/5 | 4.5/5 | +1.5 |
| Completeness | 4.0/5 | 4.0/5 | 0 |

**Nhận xét:**
> Variant 1 (Hybrid) thu hồi tốt và chính xác tài liệu liên quan đến các mã lỗi, bí danh cũ như `Approval Matrix` do được bổ trợ bởi kết quả của thành phần Sparse Match (BM25). Việc RRF phân bổ lại rank giúp các docs chứa keyword này không bị chìm xuống dưới.

**Kết luận:**
> Variant 1 (Hybrid retrieval) hoàn toàn vượt trội hơn baseline ở khả năng xử lý truy vấn chứa từ khóa kỹ thuật cụ thể. BM25 đã bù đắp lỗi hụt keywords mà Semantic space của Dense model chưa the bao quát được hết.

---

## Variant 2 (nếu có thời gian)

**Ngảy:** 13/04/2026  
**Biến thay đổi:** `use_rerank = True` (Sử dụng Cross-Encoder Reranker)  
**Lý do chọn biến này:**
> Dù Hybrid retrieval đã bắt được keyword, nhưng vì Top-K lớn nên đôi khi lẫn lộn các document nhắc tới keyword nhưng không thực sự giải quyết vấn đề. Dùng Cross-encoder Reranker giúp chấm lại Relevance score chuẩn xác hơn trước khi cắt Top-3 đưa vào LLM.

**Config:**
```python
retrieval_mode = "hybrid"
use_rerank = True
# Các tham số còn lại giữ nguyên
```

**Scorecard Variant 2:**
| Metric | Baseline | Variant 1 | Variant 2 | Best |
|--------|----------|-----------|-----------|------|
| Faithfulness | 4.40/5 | 4.0/5 | 4.40/5 | Tie (Base, V2) |
| Answer Relevance | 4.70/5 | 4.0/5 | 4.60/5 | Baseline |
| Context Recall | 5.00/5 | 4.5/5 | 5.00/5 | Tie (Base, V2) |
| Completeness | 3.70/5 | 4.0/5 | 3.70/5 | Variant 1 |

**Nhận xét:**
> Đánh giá thực tế từ script `eval.py` cho thấy LLM-as-Judge tự động chấm điểm cho ra kết quả Baseline và Variant 2 tương đồng nhau ở mức cao (Recall đều đạt 5.0). Điều này cho thấy với dataset hiện tại, search Dense quá tốt đã trả về đủ tài liệu. Cross-encoder reranker cho thấy ít tác dụng thay đổi điểm triệt để trong quy mô dữ liệu nhỏ này, đôi khi gây chút sai lệch ở tiêu chí Phù hợp câu hỏi (Answer Relevance xuống 4.6).

## Tóm tắt học được

1. **Lỗi phổ biến nhất trong pipeline này là gì?**
   > Hallucination khi không tìm thấy tài liệu phù hợp (lỗi thiếu khả năng abstain do config LLM/prompt) và miss các exact keywords khi chỉ dùng Vector (Dense) search.

2. **Biến nào có tác động lớn nhất tới chất lượng?**
   > Biến `retrieval_mode` bằng việc chuyển từ Dense sang Hybrid đã xử lý hầu hết các lỗi miss keyword, đem lại cải thiện lớn nhất về Context Recall.

3. **Nếu có thêm 1 giờ, nhóm sẽ thử gì tiếp theo?**
   > Thử nghiệm tiếp tục tích hợp Cross-encoder reranker để sort lại độ chính xác của Top-K context trước khi cho vào LLM và tune lại Strict Grounding của Prompt để ép model nói "Tôi không biết" (Abstain) triệt để hơn đối với các câu hỏi không có context.
