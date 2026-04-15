# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** ___________  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| ___ | Ingestion / Raw Owner | ___ |
| ___ | Cleaning & Quality Owner | ___ |
| ___ | Embed & Idempotency Owner | ___ |
| ___ | Monitoring / Docs Owner | ___ |

**Ngày nộp:** ___________  
**Repo:** ___________  
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Nộp tại:** `reports/group_report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (150–200 từ)

> Nguồn raw là gì (CSV mẫu / export thật)? Chuỗi lệnh chạy end-to-end? `run_id` lấy ở đâu trong log?

**Tóm tắt luồng:**

_________________

**Lệnh chạy một dòng (copy từ README thực tế của nhóm):**

_________________

---

## 2. Cleaning & expectation (150–200 từ)

> Baseline đã có nhiều rule (allowlist, ngày ISO, HR stale, refund, dedupe…). Nhóm thêm **≥3 rule mới** + **≥2 expectation mới**. Khai báo expectation nào **halt**.

### 2a. Bảng metric_impact (bắt buộc — chống trivial)

| Rule / Expectation mới | Trước (sprint1 baseline) | Sau (sprint2 + inject) | Chứng cứ |
|---|---|---|---|
| **R7** — Strip `[cleaned: ...]` tags | sprint1: chunk 3 cleaned chứa `[cleaned: stale_refund_window]` tag nội bộ → LLM đọc được marker này | sprint2: tag bị strip → chunk_text sạch, không còn marker nội bộ. Inject row 7: `"Chunk đã clean trước đó [cleaned: stale_refund_window]..."` → output = `"Chunk đã clean trước đó còn sót tag nội bộ."` | `cleaned_sprint1.csv` dòng 3 vs `cleaned_sprint2.csv` dòng 2 |
| **R8** — Quarantine migration/debug notes | sprint1: `quarantine=4`, `cleaned=6` — chunk 3 chứa "bản sync cũ policy-v3 — lỗi migration" **lọt qua** cleaned | sprint2: `quarantine=5`, `cleaned=5` — chunk 3 bị quarantine `reason=contains_migration_note`. Inject row 2,8 cũng bị catch (+2 quarantine) | `quarantine_sprint2.csv`, `quarantine_inject-new-rules.csv` dòng 2-3 |
| **R9** — Validate `exported_at` ISO format | sprint1: row 11 (`01/02/2026`) chỉ fix `effective_date`, `exported_at` không được kiểm | inject row 9: `exported_at="10/04/2026 08:00"` → quarantine `reason=invalid_exported_at_format` (+1 quarantine) | `quarantine_inject-new-rules.csv` dòng 4 |
| **E7** — `no_migration_notes_in_cleaned` (halt) | sprint1: không có expectation này → chunk chứa "bản sync cũ" đi vào embed mà không ai biết | sprint2: `migration_leak_count=0` (OK). Nếu disable R8 thì E7 **sẽ FAIL halt** → pipeline dừng, chống migration note lọt embed | `run_sprint2.log` dòng `expectation[no_migration_notes_in_cleaned]` |
| **E8** — `exported_at_within_30d` (warn) | sprint1: không có expectation này → stale export không bị cảnh báo | inject-new-rules: `stale_export_count=1` **FAIL (warn)** — row 10 có `exported_at=2025-03-01` (>13 tháng) | `run_inject-new-rules.log` dòng `expectation[exported_at_within_30d] FAIL` |

**Tổng hợp trước/sau trên bộ gốc (`policy_export_dirty.csv`):**

| Metric | sprint1 (baseline) | sprint2 (+ new rules) | Delta |
|---|---|---|---|
| `raw_records` | 10 | 10 | 0 |
| `cleaned_records` | **6** | **5** | **−1** (chunk migration note bị quarantine) |
| `quarantine_records` | **4** | **5** | **+1** (R8 catch chunk 3) |
| Expectations tổng | 6 | **8** | **+2** (E7, E8) |

**Rule chính (baseline + mở rộng):**

- **Baseline (6 rule):** allowlist doc_id, normalize effective_date, quarantine HR stale (<2026), quarantine empty text/date, dedupe chunk_text, fix refund 14→7 ngày
- **R7 (NEW):** Strip `[cleaned: ...]` tags — chống tag accumulation khi re-ingest. *metric_impact*: faithfulness giảm nếu LLM đọc marker nội bộ
- **R8 (NEW):** Quarantine migration/debug notes ("bản sync cũ", "lỗi migration"). *metric_impact*: answer_relevance giảm do retrieval trả chunk chứa noise nội bộ. **Đã đo: quarantine +1 trên bộ gốc**
- **R9 (NEW):** Validate exported_at ISO datetime. *metric_impact*: freshness_sla check sai nếu exported_at lỗi format. **Đã đo: quarantine +1 khi inject**

**Ví dụ 1 lần expectation fail và cách xử lý:**

Khi chạy `inject-new-rules`, expectation **E8 `exported_at_within_30d` FAIL (warn)**: `stale_export_count=1` — row 10 có `exported_at=2025-03-01T08:00:00` (cũ >13 tháng). Vì severity = `warn`, pipeline không halt mà tiếp tục embed. Hành động: nhóm cần liên hệ source owner để re-export chunk mới hơn.

---

## 3. Before / after ảnh hưởng retrieval hoặc agent (200–250 từ)

> Bắt buộc: inject corruption (Sprint 3) — mô tả + dẫn `artifacts/eval/…` hoặc log.

**Kịch bản inject:**

_________________

**Kết quả định lượng (từ CSV / bảng):**

_________________

---

## 4. Freshness & monitoring (100–150 từ)

> SLA bạn chọn, ý nghĩa PASS/WARN/FAIL trên manifest mẫu.

_________________

---

## 5. Liên hệ Day 09 (50–100 từ)

> Dữ liệu sau embed có phục vụ lại multi-agent Day 09 không? Nếu có, mô tả tích hợp; nếu không, giải thích vì sao tách collection.

_________________

---

## 6. Rủi ro còn lại & việc chưa làm

- …
