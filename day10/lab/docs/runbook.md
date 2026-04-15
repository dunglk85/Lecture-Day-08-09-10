# Runbook — Lab Day 10 (incident tối giản)

---

## Symptom

**User / agent thấy gì:**

- Chatbot trả lời "khách hàng có **14 ngày** để yêu cầu hoàn tiền" thay vì đúng **7 ngày** (policy refund v4)
- Agent trả lời "nhân viên được **10 ngày** phép năm" thay vì **12 ngày** (HR policy 2026)
- Retrieval trả về chunk chứa ghi chú nội bộ ("bản sync cũ policy-v3 — lỗi migration") → LLM bao gồm noise trong câu trả lời
- User hỏi về policy mới nhưng nhận được thông tin cũ (stale data)

---

## Detection

| Metric / Alert | Nguồn | Mức độ |
|---|---|---|
| `refund_no_stale_14d_window` FAIL | `run_*.log` — expectation suite | **halt** — pipeline dừng, không embed |
| `no_migration_notes_in_cleaned` FAIL | `run_*.log` — expectation E7 | **halt** — pipeline dừng |
| `exported_at_within_30d` FAIL | `run_*.log` — expectation E8 | **warn** — pipeline tiếp tục nhưng cảnh báo |
| `freshness_check=FAIL` | `manifest_*.json` → `freshness_sla_exceeded` | SLA vi phạm — dữ liệu cũ > 24h |
| `hits_forbidden=yes` | `artifacts/eval/eval_*.csv` — eval retrieval | Retrieval trả về forbidden content |
| `quarantine_records` tăng đột biến | So sánh `run_*.log` giữa các run | Source quality degradation |

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Kiểm tra `artifacts/logs/run_<run_id>.log` | Tìm dòng `expectation[...] FAIL` — xác định expectation nào fail, severity halt hay warn |
| 2 | Mở `artifacts/manifests/manifest_<run_id>.json` | Kiểm tra `latest_exported_at`, `no_refund_fix`, `skipped_validate` — xác nhận pipeline config |
| 3 | Mở `artifacts/quarantine/quarantine_<run_id>.csv` | Kiểm tra cột `reason` — phân loại: `contains_migration_note`, `duplicate_chunk_text`, `stale_hr_policy_effective_date`, etc. |
| 4 | Mở `artifacts/cleaned/cleaned_<run_id>.csv` | Verify chunk_text không chứa thông tin sai (search "14 ngày", "10 ngày phép", "bản sync cũ") |
| 5 | Chạy `python eval_retrieval.py --out artifacts/eval/eval_debug.csv` | Kiểm tra `hits_forbidden`, `contains_expected`, `top1_doc_expected` cho 4 câu hỏi golden |
| 6 | So sánh ChromaDB: `col.get(include=[])` → count IDs | Verify số vectors = số dòng trong cleaned CSV |

---

## Mitigation

### Kịch bản 1: Stale refund window (14 ngày) trong embed

```bash
# Rerun pipeline với fix enabled (mặc định)
python etl_pipeline.py run --run-id hotfix-refund

# Verify fix
python eval_retrieval.py --out artifacts/eval/eval_hotfix.csv
# Kiểm tra: q_refund_window → hits_forbidden=no
```

### Kịch bản 2: Migration notes lọt vào cleaned

```bash
# Pipeline mới sẽ tự quarantine (R8) + block (E7 halt nếu lọt)
python etl_pipeline.py run --run-id hotfix-migration

# Verify: quarantine CSV phải có reason=contains_migration_note
```

### Kịch bản 3: Freshness SLA exceeded

```bash
# Kiểm tra freshness
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_<run_id>.json

# Nếu FAIL: yêu cầu source owner re-export CSV mới
# Tạm thời: thêm banner "Dữ liệu có thể chưa cập nhật" trong UI chatbot
```

### Kịch bản 4: Rollback embed

```bash
# Chạy lại pipeline với cleaned CSV cũ (đã biết tốt)
python etl_pipeline.py run --raw <path_to_known_good_csv> --run-id rollback-<timestamp>

# Prune tự động sẽ xóa IDs không còn trong cleaned mới
# Upsert sẽ ghi đè vectors hiện tại
```

---

## Prevention

| Biện pháp | Đã làm | Cần làm thêm |
|-----------|--------|--------------|
| Expectation halt cho refund window | ✅ E3 `refund_no_stale_14d_window` | — |
| Quarantine migration notes | ✅ R8 + E7 (defense-in-depth) | — |
| Validate exported_at format | ✅ R9 `validate_exported_at_iso` | — |
| Stale export warning | ✅ E8 `exported_at_within_30d` (warn) | Nâng lên halt nếu production |
| Freshness SLA check | ✅ Manifest check 24h | Kết nối Slack alert channel `#data-quality-alerts` |
| Strip internal tags | ✅ R7 strip `[cleaned:...]` tags | — |
| Automated re-export | ❌ | Cron job gọi CMS API export hàng đêm |
| LLM-as-Judge eval | ❌ | Tích hợp faithfulness/relevance scoring từ Day 09 |
| Guardrail layer | ❌ | Day 11: thêm output guardrail kiểm tra answer vs canonical trước khi trả user |
