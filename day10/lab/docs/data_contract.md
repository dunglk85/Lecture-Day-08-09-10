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
| `chunk_id` | string | Có | ID ổn định: `{doc_id}_{seq}_{sha256[:16]}`. Deterministic — cùng input → cùng ID. Dùng làm key upsert trong ChromaDB |
| `doc_id` | string | Có | Khóa logic tài liệu nguồn. Phải thuộc allowlist (`ALLOWED_DOC_IDS` trong `cleaning_rules.py`). VD: `policy_refund_v4` |
| `chunk_text` | string | Có | Nội dung chunk sau clean. Min length = 8 chars (E4). Không chứa migration notes (R8), không chứa `[cleaned:...]` tags (R7) |
| `effective_date` | date (ISO 8601) | Có | Ngày hiệu lực chính sách. Format `YYYY-MM-DD`. DD/MM/YYYY tự động normalize. HR policy phải ≥ `2026-01-01` |
| `exported_at` | datetime (ISO 8601) | Có | Thời điểm export từ source. Format `YYYY-MM-DDTHH:MM:SS`. Dùng cho freshness SLA check. Phải ≤ 30 ngày tuổi (E8 warn) |

---

## 3. Quy tắc quarantine vs drop

### Quarantine (giữ lại trong `quarantine_*.csv` để review)

| Reason | Xử lý | Ai approve merge lại? |
|--------|--------|-----------------------|
| `unknown_doc_id` | Doc không thuộc allowlist → quarantine. Nếu cần thêm doc mới: cập nhật `ALLOWED_DOC_IDS` + `data_contract.yaml` | Data Engineering lead |
| `missing_effective_date` | Thiếu ngày hiệu lực → không xác định version → quarantine chờ source owner bổ sung | Source owner (theo canonical_sources) |
| `invalid_effective_date_format` | Không parse được format ngày → quarantine. Log `effective_date_raw` để debug | QA team review batch |
| `stale_hr_policy_effective_date` | HR policy cũ (< 2026-01-01) → quarantine vĩnh viễn (không merge lại) | HR Department confirm |
| `missing_chunk_text` | Chunk rỗng → quarantine. Thường do lỗi export CMS | Source owner re-export |
| `contains_migration_note` | Chunk chứa "bản sync cũ", "lỗi migration" → quarantine vĩnh viễn (noise nội bộ) | Không merge — drop sau 30 ngày |
| `invalid_exported_at_format` | `exported_at` không đúng ISO datetime → quarantine chờ fix format | QA team |
| `duplicate_chunk_text` | Text trùng lặp (normalize lowercase + whitespace) → quarantine bản sau, giữ bản đầu | Tự động — không cần approve |

### Drop (không giữ)

Hiện tại pipeline **không drop** — tất cả record không hợp lệ đều vào quarantine CSV để audit trail. Đây là design choice: ưu tiên traceability hơn auto-discard.

---

## 4. Phiên bản & canonical

### Source of truth

| doc_id | Canonical file | Version | Owner | Giá trị canonical |
|--------|---------------|---------|-------|--------------------|
| `policy_refund_v4` | `data/docs/policy_refund_v4.txt` | v4 | CS Operations | Cửa sổ hoàn tiền = **7 ngày làm việc** (không phải 14 ngày) |
| `sla_p1_2026` | `data/docs/sla_p1_2026.txt` | 2026 | IT Service Management | P1: first response 15 phút, resolution 4 giờ |
| `it_helpdesk_faq` | `data/docs/it_helpdesk_faq.txt` | latest (rolling) | IT Helpdesk | Lockout = 5 lần đăng nhập sai |
| `hr_leave_policy` | `data/docs/hr_leave_policy.txt` | 2026 | HR Department | 12 ngày phép/năm (< 3 năm KN). Bản 2025 (10 ngày) **đã hết hiệu lực** |

### Quy tắc versioning

- **Canonical = bản có `effective_date` mới nhất** trong allowlist
- HR policy: hard cutoff `effective_date >= 2026-01-01` (config trong `data_contract.yaml` → `policy_versioning.hr_leave_min_effective_date`)
- Refund window: pipeline tự fix "14 ngày" → "7 ngày" và gắn tag `[cleaned: stale_refund_window]` (sau đó R7 strip tag)
- Khi có version mới: cập nhật canonical file + `data_contract.yaml` + cleaning rules nếu cần thêm fix logic
