# Data contract — Lab Day 10

> Bắt đầu từ `contracts/data_contract.yaml` — mở rộng và đồng bộ file này.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `policy_refund_v4` | CSV batch export từ CMS mỗi đêm | **Duplicate chunk** (chunk 1 = chunk 2); **Chunk rỗng** (`chunk_text = ""`); **Stale migration note** trong nội dung (ghi chú "bản sync cũ policy-v3") | `duplicate_rate > 0` → alert; `empty_chunk_count > 0` → block ingest; `text LIKE '%sync cũ%'` → quarantine |
| `hr_leave_policy` | Pull từ HRIS qua API, schedule weekly | **Version conflict**: cùng `doc_id` có 2 phiên bản (10 ngày phép 2025 vs 12 ngày phép 2026) dẫn đến LLM trả lời không nhất quán | `conflicting_versions_per_doc_id > 1` → alert; kiểm tra `MAX(effective_date)` làm canonical |
| `it_helpdesk_faq` | Ingest thủ công từ file FAQ SharePoint | **Sai format ngày**: `01/02/2026` thay vì `2026-02-01` (ISO 8601) gây lỗi parse hoặc sort sai thứ tự | `date_format_error_rate > 0` → fail validation; regex check `^\d{4}-\d{2}-\d{2}$` trên `effective_date` |
| `legacy_catalog_xyz_zzz` | Import one-off từ hệ thống cũ | **Non-standard `doc_id`**: không theo pattern `<domain>_<name>_<version>` → không map được vào policy registry | `doc_id_format_violation_count > 0` → quarantine; naming regex: `^[a-z]+_[a-z0-9]+_[a-z0-9]+$` |
| `sla_p1_2026` | CSV export từ ticketing system | *(chưa phát hiện lỗi trong batch hiện tại)* | `null_effective_date_count > 0` → alert; xác nhận SLA values với ops team định kỳ |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| chunk_id | string | Có | … |
| doc_id | string | Có | … |
| chunk_text | string | Có | … |
| effective_date | date | Có | … |
| exported_at | datetime | Có | … |

---

## 3. Quy tắc quarantine vs drop

> Record bị flag đi đâu? Ai approve merge lại?

---

## 4. Phiên bản & canonical

> Source of truth cho policy refund: file nào / version nào?
